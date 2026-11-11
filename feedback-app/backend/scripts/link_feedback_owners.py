"""Apply an explicitly reviewed legacy owner/email map without rewriting feedback."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import urllib.request

from google.cloud import bigquery
from google.oauth2.credentials import Credentials

from app.access_repository import access_management_tables, access_table_ref, normalize_principal
from app.config import settings
from app.feedback_ownership import ensure_ownership_tables


METHODS = {'user_approved_private_mapping_preview', 'user_supplied_owner_email'}


def validated_approval(value: dict) -> dict:
    actual = hashlib.sha256(json.dumps({key: item for key, item in value.items() if key != 'approvalHash'}, sort_keys=True).encode()).hexdigest()
    if value.get('mode') != 'user_reviewed_legacy_ownership_links' or value.get('approvalHash') != actual:
        raise ValueError('The reviewed owner mapping changed; obtain a new approval')
    links = value.get('approvedLinks') or []
    if not links or len(links) > 500 or len({row['feedback_id'] for row in links}) != len(links):
        raise ValueError('A bounded, non-duplicate per-feedback owner map is required')
    for row in links:
        if (not re.fullmatch(r'FDB-[A-Za-z0-9-]+', row['feedback_id']) or row.get('agent_id') != settings.default_agent_id
                or not row.get('source_reporter') or '@' in row['source_reporter']
                or row['source_reporter'] != row['source_reporter'].strip().lower()
                or row.get('verification_method') not in METHODS):
            raise ValueError('Only reviewed non-empty legacy names may be linked; existing email ownership is not reassigned')
        if normalize_principal(row['owner_email']) != row['owner_email']:
            raise ValueError('Approved owner emails must be normalized company principals')
    new_users = value.get('newReporterEmails') or []
    if len(new_users) != len(set(new_users)) or len(new_users) > 20:
        raise ValueError('New Reporter onboarding scope must be explicit and non-duplicate')
    for email in new_users:
        if normalize_principal(email) != email or email not in {row['owner_email'] for row in links}:
            raise ValueError('A requested new Reporter must be an explicitly reviewed linked owner')
    return value


def build_preview(client, approved: dict) -> dict:
    approved = validated_approval(approved)
    ids = [row['feedback_id'] for row in approved['approvedLinks']]
    rows = list(client.query(f'SELECT feedback_id,agent_id,reporter FROM `{settings.project_id}.{settings.dataset}.feedback_items` WHERE feedback_id IN UNNEST(@ids)',
        job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter('ids', 'STRING', ids)]), location=settings.location).result())
    by_id = {row['feedback_id']: dict(row) for row in rows}
    if len(rows) != len(ids) or len(by_id) != len(ids):
        raise ValueError('The reviewed feedback selection is missing or duplicated')
    for row in approved['approvedLinks']:
        source = by_id[row['feedback_id']]
        if source['agent_id'] != row['agent_id'] or str(source.get('reporter') or '').strip().lower() != row['source_reporter']:
            raise ValueError('Original ownership changed after review; no links were applied')
    grants = [dict(row) for row in client.query(f'SELECT email,role,active,expires_at,FARM_FINGERPRINT(TO_JSON_STRING(t)) AS fingerprint FROM `{access_table_ref()}` t', location=settings.location).result()]
    by_email = {}
    for row in grants:
        email = normalize_principal(row['email'])
        if email in by_email or row['role'] not in {'reporter', 'reviewer'} or not isinstance(row['active'], bool):
            raise ValueError('Duplicate/malformed grants must be reviewed before linking historical ownership')
        by_email[email] = row
    new = [email for email in approved['newReporterEmails'] if email not in by_email]
    now = datetime.now(timezone.utc)
    for email in {row['owner_email'] for row in approved['approvedLinks']}:
        grant = by_email.get(email)
        if grant is None and email not in new:
            raise ValueError('A reviewed owner is not onboarded; do not silently create access')
        if grant:
            expiry = grant.get('expires_at')
            if expiry and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if not grant['active'] or expiry and expiry <= now:
                raise ValueError('An existing owner grant is inactive/expired; it was not reactivated')
    return {'version': 1, 'approval': approved, 'newReporterEmails': new,
        'existingGrantFingerprints': [{'email': email, 'fingerprint': int(row['fingerprint'])} for email, row in sorted(by_email.items())],
        'counts': {'links': len(ids), 'newReporters': len(new), 'existingGrantsPreserved': len(grants),
            'linkedOwnerPrincipals': len({row['owner_email'] for row in approved['approvedLinks']})}}


def apply_links(client, preview: dict, actor: str, expected_links: int, expected_new: int):
    approved = validated_approval(preview['approval'])
    if preview.get('version') != 1 or preview['counts']['links'] != expected_links or preview['counts']['newReporters'] != expected_new:
        raise ValueError('The exact reviewed mapping/onboarding counts changed')
    values = [bigquery.StructQueryParameter(None, *[
        bigquery.ScalarQueryParameter(key, 'STRING', row[key])
        for key in ('feedback_id', 'agent_id', 'source_reporter', 'owner_email', 'verification_method')]) for row in approved['approvedLinks']]
    old = [bigquery.StructQueryParameter(None, bigquery.ScalarQueryParameter('email', 'STRING', row['email']),
        bigquery.ScalarQueryParameter('fingerprint', 'INT64', row['fingerprint'])) for row in preview['existingGrantFingerprints']]
    parameters = [bigquery.ArrayQueryParameter('links', 'STRUCT', values), bigquery.ArrayQueryParameter('old_grants', 'STRUCT', old),
        bigquery.ArrayQueryParameter('new_users', 'STRING', preview['newReporterEmails']),
        bigquery.ScalarQueryParameter('actor', 'STRING', normalize_principal(actor)),
        bigquery.ScalarQueryParameter('batch', 'STRING', approved['approvalHash']),
        bigquery.ScalarQueryParameter('expected_links', 'INT64', expected_links),
        bigquery.ScalarQueryParameter('expected_new', 'INT64', expected_new)]
    base = f'{settings.project_id}.{settings.dataset}'
    grants = access_table_ref(); grant_events, control = access_management_tables()
    sql = f"""DECLARE linked INT64 DEFAULT 0; DECLARE added INT64 DEFAULT 0;
        BEGIN TRANSACTION;
        ASSERT (SELECT COUNT(*) FROM `{control}` WHERE scope='application-access')=1 AS 'OWNERSHIP_CONTROL_INVALID';
        UPDATE `{control}` SET revision=revision+1 WHERE scope='application-access';
        ASSERT (SELECT COUNT(*) FROM `{grants}` WHERE LOWER(TRIM(email))=@actor)=1 AS 'OWNERSHIP_REVIEWER_REQUIRED';
        ASSERT EXISTS(SELECT 1 FROM `{grants}` WHERE LOWER(TRIM(email))=@actor AND active IS TRUE AND role='reviewer'
            AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP())) AS 'OWNERSHIP_REVIEWER_REQUIRED';
        ASSERT (SELECT COUNT(*) FROM `{grants}`)=ARRAY_LENGTH(@old_grants) AS 'OWNERSHIP_ACCESS_PREVIEW_STALE';
        ASSERT NOT EXISTS(SELECT 1 FROM `{grants}` g LEFT JOIN UNNEST(@old_grants) o ON LOWER(TRIM(g.email))=o.email
            WHERE o.email IS NULL OR FARM_FINGERPRINT(TO_JSON_STRING(g))!=o.fingerprint) AS 'OWNERSHIP_ACCESS_PREVIEW_STALE';
        ASSERT NOT EXISTS(SELECT 1 FROM `{grants}` GROUP BY LOWER(TRIM(email)) HAVING COUNT(*)>1) AS 'OWNERSHIP_DUPLICATE_GRANTS';
        ASSERT (SELECT COUNT(*) FROM `{base}.feedback_items` f JOIN UNNEST(@links) l ON f.feedback_id=l.feedback_id
            WHERE f.agent_id=l.agent_id AND LOWER(TRIM(f.reporter))=l.source_reporter
            AND NULLIF(TRIM(f.reporter),'') IS NOT NULL AND STRPOS(f.reporter,'@')=0)=@expected_links AS 'OWNERSHIP_SOURCE_CHANGED';
        ASSERT NOT EXISTS(SELECT 1 FROM `{base}.feedback_owner_links` WHERE feedback_id IN (SELECT feedback_id FROM UNNEST(@links))) AS 'OWNERSHIP_LINK_EXISTS';
        ASSERT NOT EXISTS(SELECT 1 FROM `{grants}` WHERE LOWER(TRIM(email)) IN UNNEST(@new_users)) AS 'OWNERSHIP_NEW_USER_EXISTS';
        INSERT INTO `{grants}`(email,display_name,role,active,expires_at,created_at,updated_at,updated_by)
            SELECT email,'','reporter',TRUE,NULL,CURRENT_TIMESTAMP(),CURRENT_TIMESTAMP(),@actor FROM UNNEST(@new_users) email;
        SET added=@@row_count;
        ASSERT added=@expected_new AS 'OWNERSHIP_NEW_USER_COUNT_CHANGED';
        INSERT INTO `{grant_events}`(id,email,actor,action,before_json,after_json,created_at)
            SELECT CONCAT('owner-onboarding:',@batch,':',TO_HEX(SHA256(g.email))),g.email,@actor,'granted',NULL,
                TO_JSON_STRING((SELECT AS STRUCT g.*, 'user_requested_owner_linking' AS provenance)),CURRENT_TIMESTAMP()
                FROM `{grants}` g WHERE LOWER(TRIM(g.email)) IN UNNEST(@new_users);
        ASSERT NOT EXISTS(SELECT 1 FROM UNNEST(@links) l WHERE
            (SELECT COUNT(*) FROM `{grants}` g WHERE LOWER(TRIM(g.email))=l.owner_email AND g.active IS TRUE
                AND g.role IN ('reporter','reviewer') AND (g.expires_at IS NULL OR g.expires_at>CURRENT_TIMESTAMP()))!=1) AS 'OWNERSHIP_TARGET_ACCESS_INVALID';
        INSERT INTO `{base}.feedback_owner_links`(id,feedback_id,agent_id,source_reporter,owner_email,active,verified,verification_method,approved_by,approval_hash,created_at,updated_at)
            SELECT CONCAT('OWNER:',TO_HEX(SHA256(feedback_id))),feedback_id,agent_id,source_reporter,owner_email,TRUE,TRUE,
                verification_method,@actor,@batch,CURRENT_TIMESTAMP(),CURRENT_TIMESTAMP() FROM UNNEST(@links);
        SET linked=@@row_count;
        ASSERT linked=@expected_links AS 'OWNERSHIP_LINK_COUNT_CHANGED';
        INSERT INTO `{base}.feedback_owner_events`(id,feedback_id,actor,action,before_json,after_json,created_at)
            SELECT CONCAT('owner-link:',@batch,':',TO_HEX(SHA256(l.feedback_id))),l.feedback_id,@actor,'legacy_owner_linked',NULL,
                TO_JSON_STRING(l),CURRENT_TIMESTAMP() FROM `{base}.feedback_owner_links` l WHERE l.approval_hash=@batch;
        COMMIT TRANSACTION;
        SELECT linked,added;"""
    rows = list(client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=parameters), location=settings.location,
        job_id='link_feedback_owners_' + approved['approvalHash'][:40], job_retry=None).result(job_retry=None))
    if not rows or rows[0]['linked'] != expected_links or rows[0]['added'] != expected_new:
        raise RuntimeError('Owner linking outcome needs inspection; do not replay this transaction')
    return {'applied': True, 'linksAdded': expected_links, 'newReporterAccounts': expected_new,
        'existingGrantsPreserved': len(old), 'feedbackOrHistoryRowsRewritten': 0, 'modelOrAgentCalls': 0,
        'approvalHash': approved['approvalHash']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-mapping', type=Path, required=True)
    parser.add_argument('--preview-out', type=Path)
    parser.add_argument('--result-out', type=Path)
    parser.add_argument('--expected-links', type=int)
    parser.add_argument('--expected-new-users', type=int)
    parser.add_argument('--initialize-storage', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    def cloud(parts):
        response = subprocess.run(['gcloud', *parts, '--project=' + settings.project_id, '--quiet'], capture_output=True, text=True, timeout=90)
        if response.returncode:
            raise RuntimeError('The intended Google operator credential is unavailable; no credentials were printed')
        return response.stdout.strip()
    actor = cloud(['config', 'get-value', 'account']).lower()
    actor = normalize_principal(actor)
    token = cloud(['auth', 'print-access-token', '--account=' + actor])
    request = urllib.request.Request('https://www.googleapis.com/oauth2/v2/userinfo',
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        identity = json.load(response)
    if identity.get('email', '').lower() != actor or identity.get('verified_email') is not True:
        raise ValueError('The verified Google caller does not match the reviewed operator')
    client = bigquery.Client(project=settings.project_id, credentials=Credentials(token))
    approved = validated_approval(json.loads(args.approved_mapping.read_text()))
    preview = build_preview(client, approved)
    if args.initialize_storage:
        ensure_ownership_tables(client, f'{settings.project_id}.{settings.dataset}')
    if args.apply:
        if args.expected_links is None or args.expected_new_users is None:
            parser.error('--apply requires both exact expected counts')
        result = apply_links(client, preview, actor, args.expected_links, args.expected_new_users)
    else:
        result = {'applied': False, **preview['counts'], 'storageInitialized': args.initialize_storage}
    if args.preview_out:
        args.preview_out.write_text(json.dumps(preview, indent=2)); args.preview_out.chmod(0o600)
    if args.result_out:
        args.result_out.write_text(json.dumps(result, indent=2)); args.result_out.chmod(0o600)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
