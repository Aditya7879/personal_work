"""Prepare only the sample tenant and retire the known obsolete password prototype.

Never assigns application roles, copies live feedback, edits IAM, or calls AI.
The requested first Demo Admin grant is a separate, audited post-deployment step.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess

from google.cloud import bigquery
from google.oauth2.credentials import Credentials

from app.bigquery import BigQueryRepository
from app.config import settings
from app.demo_context import demo_scope
from app.demo_simulation import reset_demo
from app.role_demo import require_enabled


AUDIT_SCHEMA = [bigquery.SchemaField(name, kind) for name, kind in [
    ('id', 'STRING'), ('admin_id', 'STRING'), ('action', 'STRING'), ('persona_email', 'STRING'), ('created_at', 'TIMESTAMP'),
]]


def retire_prototype(client, reviewed_ids: list[str]) -> dict:
    if (not reviewed_ids or len(reviewed_ids) > 20 or len(set(reviewed_ids)) != len(reviewed_ids)
            or any(not re.fullmatch(r'[A-Za-z0-9-]{10,100}', value) for value in reviewed_ids)):
        raise ValueError('Use the exact reviewed IDs of our bounded prototype accounts')
    base = f'{settings.project_id}.agent_quality_demo'
    parameters = [bigquery.ArrayQueryParameter('ids', 'STRING', reviewed_ids)]
    # Only the bootstrap/disposable accounts created by the superseded prototype
    # qualify. Unknown accounts are never disabled or overwritten.
    sql = f"""BEGIN TRANSACTION;
        ASSERT (SELECT COUNT(*) FROM `{base}.demo_admin_accounts` WHERE id IN UNNEST(@ids)
            AND (STARTS_WITH(id,'BROWSER-FIXTURE-') OR (username='demo-admin' AND display_name='Demo Administrator')))
            =ARRAY_LENGTH(@ids) AS 'PROTOTYPE_ACCOUNT_SCOPE_CHANGED';
        UPDATE `{base}.demo_admin_accounts` SET active=FALSE,password_hash='RETIRED-IN-APP-ROLE-DESIGN',updated_at=CURRENT_TIMESTAMP()
            WHERE id IN UNNEST(@ids);
        UPDATE `{base}.demo_admin_sessions` SET revoked_at=COALESCE(revoked_at,CURRENT_TIMESTAMP()) WHERE admin_id IN UNNEST(@ids);
        COMMIT TRANSACTION;"""
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=parameters), location=settings.location,
        job_id='retire_feedback_password_prototype_v1', job_retry=None).result(job_retry=None)
    rows = list(client.query(f"""SELECT
        (SELECT COUNT(*) FROM `{base}.demo_admin_accounts` WHERE id IN UNNEST(@ids) AND active IS TRUE) AS active,
        (SELECT COUNT(*) FROM `{base}.demo_admin_sessions` WHERE admin_id IN UNNEST(@ids) AND revoked_at IS NULL) AS sessions""",
        job_config=bigquery.QueryJobConfig(query_parameters=parameters), location=settings.location).result())
    if not rows or rows[0]['active'] or rows[0]['sessions']:
        raise RuntimeError('Prototype retirement needs inspection; do not replay writes')
    return {'knownPasswordAccountsDisabled': len(reviewed_ids), 'unrevokedKnownPasswordSessions': 0, 'unknownAccountsChanged': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviewed-prototype-ids', type=Path, required=True)
    parser.add_argument('--result-out', type=Path, required=True)
    parser.add_argument('--reset-samples', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    require_enabled()
    if settings.project_id != 'oa-apmena-techsandbox-ap-dv' or settings.dataset != 'agent_quality':
        raise ValueError('This reviewed preparation targets only the existing feedback app and its new sample tenant')
    reviewed = json.loads(args.reviewed_prototype_ids.read_text())
    if not args.apply:
        print(json.dumps({'applied': False, 'retireKnownPrototypeAccounts': len(reviewed), 'resetSampleContent': args.reset_samples, 'liveDataOrGrantsChanged': False})); return
    if args.result_out.exists():
        raise RuntimeError('A preparation receipt already exists; inspect it instead of resetting or retiring again')

    def cloud(parts):
        value = subprocess.run(['gcloud', *parts, '--project=' + settings.project_id, '--quiet'], capture_output=True, text=True, timeout=90)
        if value.returncode:
            raise RuntimeError('Reauthenticate the same company operator; no credentials were printed')
        return value.stdout.strip()

    actor = cloud(['config', 'get-value', 'account']).lower()
    if actor != 'dhruv.chawla@loreal.com':
        raise ValueError('The reviewed preparation operator changed; no alternate identity was selected')

    def refresh(_request, scopes=None):
        return cloud(['auth', 'print-access-token', '--account=' + actor]), datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)

    client = bigquery.Client(project=settings.project_id, credentials=Credentials(cloud(['auth', 'print-access-token', '--account=' + actor]), refresh_handler=refresh))
    client.get_dataset(f'{settings.project_id}.agent_quality_demo')  # Must already exist; do not create another resource.
    result = retire_prototype(client, reviewed)
    with demo_scope():
        repo = BigQueryRepository(client=client)
        repo.ensure_schema()
        client.create_table(bigquery.Table(f'{repo.dataset_ref}.demo_admin_events', schema=AUDIT_SCHEMA), exists_ok=True)
        if args.reset_samples:
            result.update(reset_demo(repo, actor))
    result.update(applied=True, liveDataOrGrantsChanged=False, liveProviderCalls=0, projectIamOrRuntimeIdentityChanged=False)
    args.result_out.write_text(json.dumps(result, indent=2)); args.result_out.chmod(0o600)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
