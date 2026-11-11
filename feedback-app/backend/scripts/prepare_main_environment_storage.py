"""Add the single additive main-environment pointer table; insert no feedback rows."""
from __future__ import annotations

import argparse
from datetime import datetime,timedelta,timezone
import json
import subprocess
import urllib.request

from google.cloud import bigquery
from google.oauth2.credentials import Credentials

from app.config import settings


def prepare(client):
    if settings.project_id != 'oa-apmena-techsandbox-ap-dv' or settings.dataset != 'agent_quality':
        raise ValueError('Main-environment storage is fixed to the existing feedback application dataset')
    table_id = f'{settings.project_id}.{settings.dataset}.feedback_main_environments'
    schema = [bigquery.SchemaField(name, kind) for name, kind in [
        ('feedback_id', 'STRING'), ('agent_id', 'STRING'), ('environment_id', 'STRING'),
        ('environment_kind', 'STRING'), ('environment_label', 'STRING'), ('source_environment_id', 'STRING'),
        ('promotion_batch_id', 'STRING'), ('revision', 'INT64'), ('selected_by', 'STRING'),
        ('created_at', 'TIMESTAMP'), ('updated_at', 'TIMESTAMP'),
    ]]
    try:
        existing = client.get_table(table_id)
    except Exception as error:
        from google.api_core.exceptions import NotFound
        if not isinstance(error, NotFound):
            raise RuntimeError('Could not inspect additive main-environment table; no creation attempted') from None
        existing = None
    if existing is None:
        table = bigquery.Table(table_id, schema=schema)
        table.description = 'Current main environment selected by an explicit linked promotion; original feedback source metadata is unchanged.'
        client.create_table(table, exists_ok=False)
        existing = client.get_table(table_id)
        created = True
    else:
        created = False
    actual = {field.name: {'INTEGER':'INT64','BOOLEAN':'BOOL','FLOAT':'FLOAT64'}.get(field.field_type,field.field_type) for field in existing.schema}
    if any(actual.get(field.name) != field.field_type for field in schema):
        raise ValueError('The main-environment pointer schema is incompatible; nothing was replaced')
    rows = list(client.query(f'SELECT COUNT(*) AS n FROM `{table_id}`', location=settings.location).result())
    return {'table': table_id, 'created': created, 'rowsBeforeBackfill': int(rows[0]['n']), 'schemaValidated': True,
        'feedbackRowsRewritten': 0, 'workflowRowsWritten': 0, 'modelCalls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({'applied': False, 'table': f'{settings.project_id}.{settings.dataset}.feedback_main_environments',
            'rowsWritten': 0, 'workflowChanges': 0})); return
    def cloud(parts):
        value=subprocess.run(['gcloud',*parts,'--project='+settings.project_id,'--quiet'],capture_output=True,text=True,timeout=90)
        if value.returncode:raise RuntimeError('Same-account Google reauthentication required; credentials were not printed')
        return value.stdout.strip()
    actor=cloud(['config','get-value','account']).lower()
    if actor!='dhruv.chawla@loreal.com':raise ValueError('Use the explicit operator; do not switch identities')
    token=cloud(['auth','print-access-token','--account='+actor])
    request=urllib.request.Request('https://www.googleapis.com/oauth2/v2/userinfo',headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
    with urllib.request.urlopen(request,timeout=60)as response:identity=json.load(response)
    if identity.get('email','').lower()!=actor or identity.get('verified_email')is not True:raise ValueError('The verified Google operator identity does not match')
    def refresh(_request,scopes=None):
        return cloud(['auth','print-access-token','--account='+actor]),datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(minutes=10)
    client=bigquery.Client(project=settings.project_id,credentials=Credentials(token,refresh_handler=refresh))
    print(json.dumps(prepare(client), indent=2))


if __name__ == '__main__':
    main()
