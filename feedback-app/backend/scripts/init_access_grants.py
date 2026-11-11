"""Create only application access storage and optionally seed explicitly approved IAM grants."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from google.cloud import bigquery

from app.access_repository import APPLICATION_ROLES, access_management_tables, access_table_ref
from app.config import settings


SCHEMA = [bigquery.SchemaField(name, kind) for name, kind in [
    ('email', 'STRING'), ('display_name', 'STRING'), ('role', 'STRING'), ('active', 'BOOLEAN'),
    ('expires_at', 'TIMESTAMP'), ('created_at', 'TIMESTAMP'), ('updated_at', 'TIMESTAMP'), ('updated_by', 'STRING'),
]]

EVENT_SCHEMA = [bigquery.SchemaField(name, kind) for name, kind in [
    ('id', 'STRING'), ('email', 'STRING'), ('actor', 'STRING'), ('action', 'STRING'),
    ('before_json', 'STRING'), ('after_json', 'STRING'), ('created_at', 'TIMESTAMP'),
]]
CONTROL_SCHEMA = [bigquery.SchemaField('scope', 'STRING'), bigquery.SchemaField('revision', 'INTEGER')]


def initialize_management(client):
    """Add only administration audit/serialization storage. Never seed or edit grants."""
    events, control = access_management_tables()
    for name, schema in [(events, EVENT_SCHEMA), (control, CONTROL_SCHEMA)]:
        client.create_table(bigquery.Table(name, schema=schema), exists_ok=True)
        actual = {field.name: field.field_type for field in client.get_table(name).schema}
        if any(actual.get(field.name) != field.field_type for field in schema):
            raise ValueError('Existing access management storage has an incompatible schema')
    client.query(f"""MERGE `{control}` t USING (SELECT 'application-access' AS scope) s ON t.scope=s.scope
        WHEN NOT MATCHED THEN INSERT(scope,revision) VALUES(s.scope,0)""", location=settings.location).result()
    rows = list(client.query(f"SELECT COUNT(*) AS n FROM `{control}` WHERE scope='application-access'", location=settings.location).result())
    if rows[0]['n'] != 1:
        raise ValueError('Access administration serialization storage is invalid; nothing was replaced')
    return {'events': events, 'control': control}


def approved_grants(values):
    if not isinstance(values, list):
        raise ValueError('Approved grants must be a JSON array')
    result, seen = [], set()
    for row in values:
        if not isinstance(row, dict) or set(row) - {'email', 'displayName', 'role', 'active', 'expiresAt'}:
            raise ValueError('Unexpected grant fields; owner aliases and browser roles cannot be imported')
        email = str(row.get('email') or '').strip().lower()
        if '@' not in email or email.rsplit('@', 1)[1] not in settings.google_iam_domains or email in seen:
            raise ValueError('Invalid, non-company or duplicate principal')
        if row.get('role') not in APPLICATION_ROLES or not isinstance(row.get('active', True), bool):
            raise ValueError('Invalid grant role or active flag')
        seen.add(email)
        expires = datetime.fromisoformat(row['expiresAt'].replace('Z', '+00:00')) if row.get('expiresAt') else None
        result.append({'email': email, 'display_name': str(row.get('displayName') or '').strip()[:200],
            'role': row['role'], 'active': row.get('active', True), 'expires_at': expires})
    return result


def initialize(client, grants, actor='migration:existing-approved-iam-grants'):
    table = access_table_ref()
    client.create_table(bigquery.Table(table, schema=SCHEMA), exists_ok=True)
    actual = {field.name: field.field_type for field in client.get_table(table).schema}
    if any(actual.get(field.name) != field.field_type for field in SCHEMA):
        raise ValueError('Existing access storage has an incompatible schema; nothing was replaced')
    if grants:
        items = [bigquery.StructQueryParameter(None, *[bigquery.ScalarQueryParameter(key,
            'BOOL' if key == 'active' else 'TIMESTAMP' if key == 'expires_at' else 'STRING', value)
            for key, value in row.items()]) for row in grants]
        client.query(f"""MERGE `{table}` t USING UNNEST(@grants) s ON LOWER(TRIM(t.email))=s.email
            WHEN NOT MATCHED THEN INSERT(email,display_name,role,active,expires_at,created_at,updated_at,updated_by)
            VALUES(s.email,s.display_name,s.role,s.active,s.expires_at,CURRENT_TIMESTAMP(),CURRENT_TIMESTAMP(),@actor)""",
            job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter('grants','STRUCT',items),
                bigquery.ScalarQueryParameter('actor','STRING',actor)]), location=settings.location).result()
    # Existing rows, including revoked/changed roles, are deliberately never overwritten.
    return table


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-file', type=Path, help='Private JSON file containing existing explicitly approved Google grants')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--management', action='store_true', help='Add access-change audit and transaction-serialization storage')
    args = parser.parse_args()
    grants = approved_grants(json.loads(args.seed_file.read_text())) if args.seed_file else []
    if not args.apply:
        print(json.dumps({'table': access_table_ref(), 'approvedSeedCount': len(grants), 'applied': False}))
        return
    table = initialize(bigquery.Client(project=settings.project_id), grants)
    if args.management:
        initialize_management(bigquery.Client(project=settings.project_id))
    print(json.dumps({'table': table, 'approvedSeedCount': len(grants), 'applied': True,
        'existingRowsOverwritten': False, 'workflowTablesChanged': False}))


if __name__ == '__main__':
    main()
