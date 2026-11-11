"""Audited, metadata-only assignment of existing feedback to a confirmed source environment."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import uuid

from google.cloud import bigquery

from app.agent_targets import stored_environment_kind
from app.bigquery import BigQueryRepository


def assignment_context(context: dict, target: dict, stamp: str) -> dict:
    return {**context, "environment_id": target["id"], "environment_kind": target["kind"],
        "environment_label": target["name"], "source_environment_confirmation": {
            "confirmedAt": stamp, "reason": "User confirmed these existing reports were originally tested in non-production",
            "previousEnvironmentId": context.get("environment_id"), "source": "explicit_user_confirmation"}}


def assign_existing(repo: BigQueryRepository, environment_id: str, apply: bool = False) -> dict:
    target = repo.get_agent_environment(environment_id)
    if target["kind"] != "nonprod":
        raise ValueError("This correction is authorized only for the confirmed non-production source")
    rows = repo.workflow_query(f"""SELECT feedback_id,agent_id,environment,run_context_json,revision,updated_at
        FROM `{repo.feedback_ref}` WHERE agent_id=@agent""", [bigquery.ScalarQueryParameter('agent', 'STRING', target['agent_id'])])
    stamp = datetime.now(timezone.utc).isoformat()
    changes, backup = [], []
    for row in rows:
        context = repo._json_object(row.get('run_context_json'))
        explicit = context.get('environment_id')
        kind = context.get('environment_kind') if explicit else row.get('environment') or 'unknown'
        if explicit and explicit != environment_id or kind not in {'unknown', 'nonprod'}:
            raise ValueError("An explicitly different source environment exists; refusing to overwrite it")
        if explicit == environment_id and context.get('environment_kind') == target['kind']:
            continue
        updated = assignment_context(context, target, stamp)
        changes.append(bigquery.StructQueryParameter(None,
            bigquery.ScalarQueryParameter('id', 'STRING', row['feedback_id']),
            bigquery.ScalarQueryParameter('revision', 'INT64', int(row.get('revision') or 1)),
            bigquery.ScalarQueryParameter('old_kind', 'STRING', row.get('environment')),
            bigquery.ScalarQueryParameter('old_context', 'STRING', row.get('run_context_json')),
            bigquery.ScalarQueryParameter('new_context', 'STRING', json.dumps(updated, ensure_ascii=False))))
        backup.append(row)
    result = {'totalExistingFeedback': len(rows), 'mappingUpdates': len(changes), 'targetId': target['id'],
              'targetName': target['name'], 'applied': False, 'agentCalls': 0, 'jobsQueued': 0}
    if not apply or not changes:
        return result
    directory = Path(tempfile.mkdtemp(prefix='feedback-source-environment-', dir='/tmp/opencode'))
    fd = os.open(directory / 'metadata-before.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(backup, output, indent=2, default=str)
    run_id = uuid.uuid4().hex
    parameters = [bigquery.ArrayQueryParameter('changes', 'STRUCT', changes),
        bigquery.ScalarQueryParameter('agent', 'STRING', target['agent_id']),
        bigquery.ScalarQueryParameter('kind', 'STRING', stored_environment_kind(target['agent_id'], target['kind'], target['id'])),
        bigquery.ScalarQueryParameter('target', 'STRING', target['id']), bigquery.ScalarQueryParameter('label', 'STRING', target['name']),
        bigquery.ScalarQueryParameter('expected', 'INT64', len(changes)), bigquery.ScalarQueryParameter('run', 'STRING', run_id)]
    repo.workflow_query(f"""BEGIN TRANSACTION;
        UPDATE `{repo.feedback_ref}` f SET environment=@kind,run_context_json=c.new_context,updated_at=CURRENT_TIMESTAMP()
        FROM UNNEST(@changes) c WHERE f.feedback_id=c.id AND f.agent_id=@agent AND COALESCE(f.revision,1)=c.revision
            AND COALESCE(f.environment,'')=COALESCE(c.old_kind,'') AND COALESCE(f.run_context_json,'')=COALESCE(c.old_context,'');
        ASSERT @@row_count=@expected AS 'Feedback context changed concurrently; source assignment rolled back';
        INSERT INTO `{repo.events_ref}` (event_id,feedback_id,event_type,created_at,actor,payload_json)
        SELECT CONCAT('source-environment:',@run,':',c.id),c.id,'source_environment_confirmed',CURRENT_TIMESTAMP(),
            'system:user_confirmed_nonprod_assignment',TO_JSON_STRING(STRUCT(@target AS environment_id,@label AS environment_label,
                c.old_kind AS previous_environment,JSON_VALUE(c.old_context,'$.environment_id') AS previous_environment_id,
                'User confirmed original testing was non-production; no question/answer or review state changed' AS reason)) FROM UNNEST(@changes) c;
        COMMIT TRANSACTION;""", parameters)
    result.update(applied=True, artifacts=str(directory), runId=run_id)
    (directory / 'result.json').write_text(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment-id', default='neo-nonprod')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(assign_existing(BigQueryRepository(), args.environment_id, args.apply), indent=2))


if __name__ == '__main__':
    main()
