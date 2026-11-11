"""One-time, insert-only Google-group member import. No directory/IAM/schedule changes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from google.auth.transport.requests import Request as GoogleRequest
from google.cloud import bigquery
from google.oauth2 import id_token

from app.access_repository import APPLICATION_ROLES, access_management_tables, access_table_ref, normalize_principal
from app.config import settings


PROJECT = 'oa-apmena-techsandbox-ap-dv'
MAX_MEMBERS = 5000


class DirectoryReadError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class GroupDirectory:
    def __init__(self, access_token: str, *, opener=None, now=lambda: datetime.now(timezone.utc)):
        self._token = access_token
        self._opener = opener or urllib.request.build_opener(NoRedirect).open
        self._now = now

    def get(self, path, parameters=None):
        url = 'https://cloudidentity.googleapis.com/v1/' + path
        if parameters:
            url += '?' + urllib.parse.urlencode(parameters)
        request = urllib.request.Request(url, headers={'Authorization':'Bearer ' + self._token,
            'Accept':'application/json','X-Goog-User-Project':PROJECT})
        try:
            with self._opener(request, timeout=60) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise DirectoryReadError(f'Google group directory read failed with HTTP {error.code}; no app grants were changed') from None
        if not isinstance(result, dict) or result.get('error'):
            raise DirectoryReadError('Google directory returned an invalid response')
        return result

    def snapshot(self, group_email: str) -> dict:
        requested = normalize_principal(group_email)
        resource = self.get('groups:lookup', {'groupKey.id':requested}).get('name')
        if not isinstance(resource, str) or not re.fullmatch(r'groups/[A-Za-z0-9_-]+', resource):
            raise DirectoryReadError('The requested group could not be resolved to a Google group resource')
        group = self.get(resource)
        key = group.get('groupKey') or {}
        aliases = {str(item.get('id') or '').strip().lower() for item in group.get('additionalGroupKeys', [])}
        canonical = str(key.get('id') or '').strip().lower()
        if (group.get('name') != resource or key.get('namespace') or not str(group.get('parent') or '').startswith('customers/')
                or requested not in {canonical, *aliases}):
            raise DirectoryReadError('The resolved Google group does not match the requested company group')
        canonical = normalize_principal(canonical)
        members, seen_tokens, page_token, entries, expired = {}, set(), None, 0, 0
        now = self._now()
        for _page in range(20):
            parameters = {'pageSize':500,'view':'FULL'}
            if page_token:
                parameters['pageToken'] = page_token
            data = self.get(resource + '/memberships', parameters)
            rows = data.get('memberships', [])
            if not isinstance(rows, list):
                raise DirectoryReadError('Group membership response is incomplete or malformed')
            entries += len(rows)
            if entries > MAX_MEMBERS:
                raise DirectoryReadError('Group import exceeds the reviewed member limit')
            for row in rows:
                member_key = row.get('preferredMemberKey') or {}
                if row.get('type') != 'USER' or member_key.get('namespace'):
                    raise DirectoryReadError('This one-time import requires direct Google user members; nested groups/non-user entries need separate review')
                email = normalize_principal(member_key.get('id') or '')
                expiry_values = []
                for role in row.get('roles') or [{'name':'MEMBER'}]:
                    if role.get('name') not in {'OWNER','MANAGER','MEMBER'}:
                        raise DirectoryReadError('A membership contains an unrecognized role')
                    value = (role.get('expiryDetail') or {}).get('expireTime')
                    expiry = datetime.fromisoformat(value.replace('Z','+00:00')) if value else None
                    if expiry is not None and expiry.tzinfo is None:
                        raise DirectoryReadError('A membership expiration has no timezone')
                    if expiry is None or expiry > now:
                        expiry_values.append(expiry)
                if not expiry_values:
                    expired += 1
                    continue
                expiry = None if None in expiry_values else max(expiry_values)
                existing = members.get(email)
                if existing and existing['expiresAt'] != (expiry.isoformat() if expiry else None):
                    raise DirectoryReadError('Conflicting duplicate memberships require review')
                members[email] = {'email':email,'expiresAt':expiry.isoformat() if expiry else None}
            next_token = data.get('nextPageToken')
            if not next_token:
                break
            if not isinstance(next_token, str) or next_token in seen_tokens:
                raise DirectoryReadError('Group membership pagination did not complete')
            seen_tokens.add(next_token); page_token = next_token
        else:
            raise DirectoryReadError('Group membership pagination exceeded its bound')
        values = sorted(members.values(), key=lambda item:item['email'])
        fingerprint = hashlib.sha256(json.dumps({'groupId':resource,'canonicalEmail':canonical,'members':values},sort_keys=True).encode()).hexdigest()
        return {'requestedEmail':requested,'canonicalEmail':canonical,'resourceName':resource,'members':values,
            'membershipHash':fingerprint,'fetchedAt':now.isoformat(),'complete':True,'directoryEntryCount':entries,
            'expiredMembershipsExcluded':expired}


def build_preview(client, snapshot: dict) -> dict:
    if snapshot.get('complete') is not True:
        raise ValueError('A complete verified group membership snapshot is required')
    emails = [member['email'] for member in snapshot['members']]
    rows = list(client.query(f"""SELECT email,role,active,expires_at,FARM_FINGERPRINT(TO_JSON_STRING(t)) AS fingerprint
        FROM `{access_table_ref()}` t WHERE LOWER(TRIM(email)) IN UNNEST(@emails)""",
        job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter('emails','STRING',emails)]),location=settings.location).result())
    existing = {}
    now = datetime.now(timezone.utc)
    denied = 0
    for row in rows:
        email = normalize_principal(row['email'])
        if email in existing or row['role'] not in APPLICATION_ROLES or not isinstance(row['active'], bool):
            raise ValueError('Duplicate or malformed existing grants must be reviewed before import')
        expiry = row['expires_at']
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if row['active'] is False or expiry and expiry <= now:
            denied += 1
        existing[email] = {'email':email,'fingerprint':str(row['fingerprint'])}
    return {'version':1,'mode':'one_time_group_reporter_import','group':snapshot,
        'existingRows':sorted(existing.values(),key=lambda item:item['email']),
        'counts':{'currentUserMembers':len(emails),'newReporterGrants':len(emails)-len(existing),
            'existingGrantsPreserved':len(existing),'existingInactiveOrExpiredPreserved':denied,
            'expiredMembershipsExcluded':snapshot['expiredMembershipsExcluded']},
        'roleForNewUsers':'reporter','automaticSync':False,'grantChangesApplied':False}


def apply_import(client, preview, fresh_snapshot, actor, expected_new):
    if (expected_new < 0 or preview.get('version') != 1 or preview.get('mode') != 'one_time_group_reporter_import'
            or preview.get('roleForNewUsers') != 'reporter' or fresh_snapshot.get('complete') is not True
            or preview['group']['resourceName'] != fresh_snapshot['resourceName']
            or preview['group']['membershipHash'] != fresh_snapshot['membershipHash']
            or preview['counts']['newReporterGrants'] != expected_new):
        raise ValueError('Group membership or reviewed import scope changed; obtain a fresh preview')
    if expected_new == 0:
        return {'applied':False,'added':0,'existingGrantsPreserved':preview['counts']['existingGrantsPreserved'],
            'automaticSync':False,'reason':'All current members already have an access record; no roles or revocations were changed'}
    members = [bigquery.StructQueryParameter(None,bigquery.ScalarQueryParameter('email','STRING',member['email']),
        bigquery.ScalarQueryParameter('expires_at','TIMESTAMP',datetime.fromisoformat(member['expiresAt']) if member['expiresAt'] else None))
        for member in fresh_snapshot['members']]
    existing = [bigquery.StructQueryParameter(None,bigquery.ScalarQueryParameter('email','STRING',row['email']),
        bigquery.ScalarQueryParameter('fingerprint','INT64',int(row['fingerprint']))) for row in preview['existingRows']]
    # An empty STRUCT-array needs its explicit element type for BigQuery.
    existing_type = bigquery.StructQueryParameterType(bigquery.ScalarQueryParameterType('STRING',name='email'),
        bigquery.ScalarQueryParameterType('INT64',name='fingerprint'))
    digest = hashlib.sha256(json.dumps(preview,sort_keys=True).encode()).hexdigest()[:32]
    parameters = [bigquery.ArrayQueryParameter('members','STRUCT',members),
        bigquery.ArrayQueryParameter('existing',existing_type,existing),
        bigquery.ScalarQueryParameter('expected_new','INT64',expected_new),
        bigquery.ScalarQueryParameter('actor','STRING',actor),bigquery.ScalarQueryParameter('batch','STRING',digest),
        bigquery.ScalarQueryParameter('group_email','STRING',fresh_snapshot['canonicalEmail']),
        bigquery.ScalarQueryParameter('group_id','STRING',fresh_snapshot['resourceName']),
        bigquery.ScalarQueryParameter('membership_hash','STRING',fresh_snapshot['membershipHash'])]
    table = access_table_ref(); events, control = access_management_tables()
    sql = f"""DECLARE added INT64 DEFAULT 0;
        BEGIN TRANSACTION;
        ASSERT (SELECT COUNT(*) FROM `{control}` WHERE scope='application-access')=1 AS 'ACCESS_CONTROL_INVALID';
        UPDATE `{control}` SET revision=revision+1 WHERE scope='application-access';
        ASSERT (SELECT COUNT(*) FROM `{table}` WHERE LOWER(TRIM(email))=@actor)=1 AS 'REVIEWER_REQUIRED';
        ASSERT EXISTS(SELECT 1 FROM `{table}` WHERE LOWER(TRIM(email))=@actor AND active IS TRUE AND role IN ('reviewer','demo_admin')
            AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP())) AS 'REVIEWER_REQUIRED';
        ASSERT NOT EXISTS(SELECT 1 FROM `{table}` GROUP BY LOWER(TRIM(email)) HAVING COUNT(*)>1) AS 'DUPLICATE_ACCESS_GRANTS';
        ASSERT (SELECT COUNT(*) FROM `{table}` WHERE LOWER(TRIM(email)) IN (SELECT email FROM UNNEST(@members)))
            =COALESCE(ARRAY_LENGTH(@existing),0) AS 'ACCESS_PREVIEW_STALE';
        ASSERT NOT EXISTS(SELECT 1 FROM `{table}` t JOIN UNNEST(@members) m ON LOWER(TRIM(t.email))=m.email
            LEFT JOIN UNNEST(@existing) e ON e.email=m.email
            WHERE e.email IS NULL OR FARM_FINGERPRINT(TO_JSON_STRING(t))!=e.fingerprint) AS 'ACCESS_PREVIEW_STALE';
        CREATE TEMP TABLE additions AS SELECT m.email,m.expires_at FROM UNNEST(@members) m
            WHERE NOT EXISTS(SELECT 1 FROM `{table}` t WHERE LOWER(TRIM(t.email))=m.email);
        ASSERT (SELECT COUNT(*) FROM additions)=@expected_new AS 'ACCESS_IMPORT_SCOPE_CHANGED';
        ASSERT NOT EXISTS(SELECT 1 FROM additions WHERE expires_at<=CURRENT_TIMESTAMP()) AS 'MEMBERSHIP_EXPIRED';
        INSERT INTO `{table}`(email,display_name,role,active,expires_at,created_at,updated_at,updated_by)
            SELECT email,'','reporter',TRUE,expires_at,CURRENT_TIMESTAMP(),CURRENT_TIMESTAMP(),@actor FROM additions;
        SET added=@@row_count;
        ASSERT added=@expected_new AS 'ACCESS_IMPORT_COUNT_CHANGED';
        INSERT INTO `{events}`(id,email,actor,action,before_json,after_json,created_at)
            SELECT CONCAT('group-import:',@batch,':',TO_HEX(SHA256(email))),email,@actor,'granted',NULL,
                TO_JSON_STRING(STRUCT(email AS email,'' AS display_name,'reporter' AS role,TRUE AS active,
                    expires_at AS expires_at,CURRENT_TIMESTAMP() AS created_at,CURRENT_TIMESTAMP() AS updated_at,@actor AS updated_by,
                    STRUCT(@group_email AS email,@group_id AS resource_name,@membership_hash AS membership_hash,
                        'one_time' AS mode) AS group_import)),CURRENT_TIMESTAMP() FROM additions;
        COMMIT TRANSACTION;
        SELECT added;"""
    rows = list(client.query(sql,job_config=bigquery.QueryJobConfig(query_parameters=parameters),location=settings.location,
        job_id='access_group_import_' + digest,job_retry=None).result(job_retry=None))
    if not rows or rows[0]['added'] != expected_new:
        raise RuntimeError('Import result is not confirmed; inspect saved state before any new attempt')
    return {'applied':True,'group':fresh_snapshot['canonicalEmail'],'currentUserMembers':len(fresh_snapshot['members']),
        'added':rows[0]['added'],'roleForNewUsers':'reporter','existingGrantsPreserved':len(preview['existingRows']),
        'existingInactiveOrExpiredPreserved':preview['counts']['existingInactiveOrExpiredPreserved'],
        'automaticSync':False,'directoryOrIamChanges':False,'feedbackOrWorkflowWrites':False,'modelCalls':0,'batchId':digest}


def operator_credentials():
    def cloud(args):
        result = subprocess.run(['gcloud',*args,'--project=' + PROJECT,'--quiet'],capture_output=True,text=True,timeout=60)
        if result.returncode:
            raise RuntimeError('The intended Google-user operator credential is unavailable; credentials were not logged')
        return result.stdout.strip()
    actor = cloud(['config','get-value','account']).lower()
    token = cloud(['auth','print-identity-token','--account=' + actor])
    claims = id_token.verify_oauth2_token(token,GoogleRequest(),audience=None)
    if claims.get('email','').lower() != actor or claims.get('email_verified') is not True or not actor.endswith('@loreal.com'):
        raise ValueError('A verified real company Google operator is required')
    return actor,cloud(['auth','print-access-token','--account=' + actor])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group',required=True)
    parser.add_argument('--preview-out',type=Path)
    parser.add_argument('--approved-preview',type=Path)
    parser.add_argument('--expected-new',type=int)
    parser.add_argument('--result-out',type=Path)
    parser.add_argument('--apply',action='store_true')
    args = parser.parse_args()
    if settings.project_id != PROJECT or settings.dataset != 'agent_quality':
        raise ValueError('This import targets only the existing feedback application dataset')
    actor,access = operator_credentials(); snapshot = GroupDirectory(access).snapshot(args.group)
    client = bigquery.Client(project=PROJECT)
    if args.apply:
        if not args.approved_preview or args.expected_new is None:
            parser.error('--apply requires --approved-preview and --expected-new')
        result = apply_import(client,json.loads(args.approved_preview.read_text()),snapshot,actor,args.expected_new)
        if args.result_out:
            args.result_out.write_text(json.dumps(result,indent=2)); args.result_out.chmod(0o600)
    else:
        review = build_preview(client,snapshot)
        if args.preview_out:
            args.preview_out.write_text(json.dumps(review,indent=2)); args.preview_out.chmod(0o600)
        result = {'group':snapshot['canonicalEmail'],**review['counts'],'roleForNewUsers':'reporter',
            'automaticSync':False,'applied':False,'directoryReadComplete':True}
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
