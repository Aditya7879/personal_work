"""One explicitly approved Reviewer → Demo Admin bootstrap, after code deployment.

This is not a general self-role-change API. Target, operator, old/new role and
approval provenance are fixed; all other grants and target fields are preserved.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import urllib.request

from google.cloud import bigquery
from google.oauth2.credentials import Credentials

from app.access_repository import access_management_tables, access_table_ref
from app.config import settings


TARGET = 'dhruv.chawla@loreal.com'
EVENT_ID = 'explicit-demo-admin-bootstrap:dhruv.chawla:2026-10-30:v1'
JOB_ID = 'explicit_feedback_demo_admin_bootstrap_20261030_v1'
PROVENANCE = 'explicit_user_request_in_app_demo_admin_2026_10_29'


def reviewed_grants(rows: list[dict]) -> list[dict]:
    if len(rows) != 26 or len({row['email'].strip().lower() for row in rows}) != len(rows):
        raise ValueError('The exact reviewed application directory changed; obtain a new review')
    target = [row for row in rows if row['email'].strip().lower() == TARGET]
    if (len(target) != 1 or target[0]['role'] != 'reviewer' or target[0]['active'] is not True
            or target[0]['expires_at'] is not None or any('fingerprint' not in row for row in rows)):
        raise ValueError('Only the explicitly requested existing active non-expiring Reviewer may be bootstrapped')
    return rows


def apply_bootstrap(client, rows: list[dict], actor: str) -> dict:
    reviewed_grants(rows)
    if actor != TARGET or settings.project_id != 'oa-apmena-techsandbox-ap-dv' or settings.dataset != 'agent_quality':
        raise ValueError('This is a fixed single-user bootstrap, not a general promotion mechanism')
    table = access_table_ref(); events, control = access_management_tables()
    if table != f'{settings.project_id}.agent_quality.application_access_grants':
        raise ValueError('Only the live application grant table is in scope')
    values = [bigquery.StructQueryParameter(None,
        bigquery.ScalarQueryParameter('email', 'STRING', row['email'].strip().lower()),
        bigquery.ScalarQueryParameter('fingerprint', 'INT64', int(row['fingerprint']))) for row in rows]
    parameters = [bigquery.ArrayQueryParameter('reviewed', 'STRUCT', values),
        bigquery.ScalarQueryParameter('actor', 'STRING', actor),
        bigquery.ScalarQueryParameter('event', 'STRING', EVENT_ID),
        bigquery.ScalarQueryParameter('provenance', 'STRING', PROVENANCE)]
    sql = f"""DECLARE before_state STRING; DECLARE after_state STRING;
        BEGIN TRANSACTION;
        ASSERT @actor='{TARGET}' AS 'EXPLICIT_BOOTSTRAP_ACTOR_REQUIRED';
        ASSERT (SELECT COUNT(*) FROM `{control}` WHERE scope='application-access')=1 AS 'ACCESS_CONTROL_INVALID';
        UPDATE `{control}` SET revision=revision+1 WHERE scope='application-access';
        ASSERT NOT EXISTS(SELECT 1 FROM `{table}` GROUP BY LOWER(TRIM(email)) HAVING COUNT(*)>1) AS 'DUPLICATE_ACCESS_GRANTS';
        ASSERT (SELECT COUNT(*) FROM `{table}`)=26 AND ARRAY_LENGTH(@reviewed)=26 AS 'BOOTSTRAP_DIRECTORY_CHANGED';
        ASSERT NOT EXISTS(SELECT 1 FROM `{table}` g LEFT JOIN UNNEST(@reviewed) r ON LOWER(TRIM(g.email))=r.email
            WHERE r.email IS NULL OR FARM_FINGERPRINT(TO_JSON_STRING(g))!=r.fingerprint) AS 'BOOTSTRAP_PREVIEW_STALE';
        ASSERT (SELECT COUNT(*) FROM `{table}` WHERE LOWER(TRIM(email))=@actor AND role='reviewer'
            AND active IS TRUE AND expires_at IS NULL)=1 AS 'BOOTSTRAP_REVIEWER_CHANGED';
        ASSERT NOT EXISTS(SELECT 1 FROM `{events}` WHERE id=@event) AS 'BOOTSTRAP_ALREADY_APPLIED';
        SET before_state=(SELECT TO_JSON_STRING(g) FROM `{table}` g WHERE LOWER(TRIM(email))=@actor);
        UPDATE `{table}` SET role='demo_admin',updated_at=CURRENT_TIMESTAMP(),updated_by=@actor
            WHERE LOWER(TRIM(email))=@actor AND role='reviewer' AND active IS TRUE AND expires_at IS NULL;
        ASSERT @@row_count=1 AS 'BOOTSTRAP_REVIEWER_CHANGED';
        SET after_state=(SELECT TO_JSON_STRING((SELECT AS STRUCT g.*,@provenance AS approval_provenance,
            'one_explicitly_requested_initial_grant' AS bootstrap_scope)) FROM `{table}` g WHERE LOWER(TRIM(email))=@actor);
        INSERT INTO `{events}`(id,email,actor,action,before_json,after_json,created_at)
            VALUES(@event,@actor,@actor,'updated',before_state,after_state,CURRENT_TIMESTAMP());
        COMMIT TRANSACTION;
        SELECT after_state AS grant_json;"""
    result = list(client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=parameters), location=settings.location,
        job_id=JOB_ID, job_retry=None).result(job_retry=None))
    if len(result) != 1:
        raise RuntimeError('Bootstrap outcome is unconfirmed; inspect the stable job ID, never replay the write')
    saved = json.loads(result[0]['grant_json'])
    if saved.get('email', '').lower() != TARGET or saved.get('role') != 'demo_admin' or saved.get('approval_provenance') != PROVENANCE:
        raise RuntimeError('Bootstrap did not return the exact intended grant')
    return {'applied': True, 'email': TARGET, 'oldRole': 'reviewer', 'newRole': 'demo_admin',
        'effectiveRoleUnchanged': 'reviewer', 'otherGrantsChanged': 0, 'targetActiveDisplayExpiryAndCreatedFieldsPreserved': True,
        'accessAuditId': EVENT_ID, 'approvalProvenance': PROVENANCE, 'normalSelfRoleChangeSafeguardUnchanged': True,
        'feedbackOrWorkflowWrites': 0, 'providerCalls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(); root = args.artifacts.resolve()
    deployed = json.loads((root / 'role-demo-deployment-result.json').read_text())
    if not deployed.get('passed') or not deployed.get('checks', {}).get('storedRoleAcceptedByDeployedCode') or not deployed.get('sameExistingApp'):
        raise RuntimeError('Deploy and verify compatible code on the existing app before the initial role assignment')
    if (root / 'initial-demo-admin-grant-result.json').exists():
        raise RuntimeError('An initial role-assignment receipt already exists; inspect it rather than changing the grant again')
    rows = reviewed_grants(json.loads((root / 'private-grants-before.json').read_text()))
    if not args.apply:
        print(json.dumps({'applied': False, 'email': TARGET, 'transition': 'reviewer -> demo_admin', 'otherUsersInScope': 0,
            'requiresDeployedCompatibleCode': True, 'normalSelfRoleChangeSafeguardUnchanged': True}, indent=2)); return

    def cloud(parts):
        value = subprocess.run(['gcloud', *parts, '--project=' + settings.project_id, '--quiet'], capture_output=True, text=True, timeout=90)
        if value.returncode:
            raise RuntimeError('Same-account Google reauthentication required; credentials were not printed')
        return value.stdout.strip()

    actor = cloud(['config', 'get-value', 'account']).lower()
    if actor != TARGET:
        raise ValueError('The exact approved operator is required; no alternate identity was selected')
    # A saved success receipt is not enough if another deployment or security
    # change happened afterward. Do not assign a role that the current app may
    # no longer understand, and never overwrite another operator's changes.
    approved_cloud = json.loads((root / 'cloud-after.json').read_text())
    for service in ('neo-feedback-api', 'neo-feedback-ui'):
        current = json.loads(cloud(['run', 'services', 'describe', service, '--region=europe-west1', '--format=json']))
        approved = approved_cloud[service]['service']
        security_keys = ('run.googleapis.com/iap-enabled', 'run.googleapis.com/invoker-iam-disabled', 'run.googleapis.com/ingress')
        if (current['spec'] != approved['spec']
                or current['status']['latestReadyRevisionName'] != deployed['services'][service]['revision']
                or any(current.get('metadata', {}).get('annotations', {}).get(key) != approved.get('metadata', {}).get('annotations', {}).get(key) for key in security_keys)):
            raise RuntimeError('The deployed compatible app changed; review it before the single initial role assignment')
        policy = json.loads(cloud(['run', 'services', 'get-iam-policy', service, '--region=europe-west1', '--format=json']))
        canonical = lambda value: sorted(json.dumps({**binding, 'members': sorted(binding.get('members', []))}, sort_keys=True) for binding in value.get('bindings', []))
        if canonical(policy) != canonical(approved_cloud[service]['iam']):
            raise RuntimeError('The reviewed service invocation policy changed; no role was assigned')
    token = cloud(['auth', 'print-access-token', '--account=' + actor])
    request = urllib.request.Request('https://www.googleapis.com/oauth2/v2/userinfo', headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        identity = json.load(response)
    if identity.get('email', '').lower() != TARGET or identity.get('verified_email') is not True:
        raise ValueError('The verified Google caller does not match the explicitly approved target')

    def refresh(_request, scopes=None):
        return cloud(['auth', 'print-access-token', '--account=' + actor]), datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)

    client = bigquery.Client(project=settings.project_id, credentials=Credentials(token, refresh_handler=refresh))
    result = apply_bootstrap(client, rows, actor)
    path = root / 'initial-demo-admin-grant-result.json'; path.write_text(json.dumps(result, indent=2)); path.chmod(0o600)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
