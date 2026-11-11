"""Audited one-time metadata pointer for feedback already sent to named targets.

The original feedback/source rows and answer/RCA history are never rewritten.
For each feedback ID, the latest explicitly confirmed promotion selection wins.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

from google.cloud import bigquery
from google.oauth2.credentials import Credentials

from app.access_repository import access_table_ref, normalize_principal
from app.config import settings


METHOD = 'latest_explicit_feedback_promotion'


def candidate_sql() -> str:
    dataset = f'{settings.project_id}.{settings.dataset}'
    return f"""WITH selections AS (
        SELECT b.id AS promotion_batch_id,b.requested_by AS selected_by,b.created_at AS selected_at,
            j.feedback_id,f.agent_id,COALESCE(f.revision,1) AS revision,j.target_id,
            COALESCE(JSON_VALUE(j.target_snapshot_json,'$.target.environment'),j.environment) AS environment_kind,
            COALESCE(JSON_VALUE(j.target_snapshot_json,'$.environmentName'),b.target_name) AS environment_label,
            COALESCE(JSON_VALUE(f.run_context_json,'$.environment_id'),
                CASE COALESCE(JSON_VALUE(f.run_context_json,'$.environment_kind'),f.environment)
                    WHEN 'nonprod' THEN @legacy_nonprod WHEN 'prod' THEN @legacy_prod END) AS source_environment_id,
            COALESCE(f.revision,1) AS current_feedback_revision
        FROM `{dataset}.feedback_promotion_batches` b
        JOIN `{dataset}.feedback_workflow_jobs` j ON j.batch_id=b.id AND j.kind='retest' AND j.target_id=b.target_id
        JOIN `{dataset}.feedback_items` f ON f.feedback_id=j.feedback_id AND f.agent_id=@agent
        JOIN `{dataset}.agent_environments` e ON e.id=j.target_id AND e.agent_id=f.agent_id
        WHERE j.target_id IS NOT NULL AND COALESCE(JSON_VALUE(j.target_snapshot_json,'$.target.environment'),j.environment) IN ('nonprod','prod')
        QUALIFY ROW_NUMBER() OVER(PARTITION BY j.feedback_id ORDER BY b.created_at DESC,b.id DESC,j.id DESC)=1
    )
    SELECT feedback_id,agent_id,target_id AS environment_id,environment_kind,environment_label,source_environment_id,
        promotion_batch_id,selected_by,revision FROM selections"""


def candidates(client) -> list[dict]:
    params = [bigquery.ScalarQueryParameter('agent', 'STRING', settings.default_agent_id),
        bigquery.ScalarQueryParameter('legacy_nonprod', 'STRING', None),
        bigquery.ScalarQueryParameter('legacy_prod', 'STRING', None)]
    from app.agent_targets import legacy_environment_id
    params[1] = bigquery.ScalarQueryParameter('legacy_nonprod', 'STRING', legacy_environment_id(settings.default_agent_id, 'nonprod'))
    params[2] = bigquery.ScalarQueryParameter('legacy_prod', 'STRING', legacy_environment_id(settings.default_agent_id, 'prod'))
    return [dict(row) for row in client.query(candidate_sql(), job_config=bigquery.QueryJobConfig(query_parameters=params), location=settings.location).result()]


def preview(client) -> dict:
    rows = candidates(client)
    if len({row['feedback_id'] for row in rows}) != len(rows):
        raise ValueError('Promotion history has duplicate feedback selections; stop for manual review')
    pointer = f'{settings.project_id}.{settings.dataset}.feedback_main_environments'
    existing = []
    for offset in range(0, len(rows), 400):
        ids = [row['feedback_id'] for row in rows[offset:offset+400]]
        if not ids: continue
        existing.extend(dict(row) for row in client.query(f'SELECT *,FARM_FINGERPRINT(TO_JSON_STRING(t)) AS fingerprint FROM `{pointer}` t WHERE feedback_id IN UNNEST(@ids)',
            job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter('ids', 'STRING', ids)]), location=settings.location).result())
    by_id = {row['feedback_id']: row for row in existing}
    updates, unchanged = [], []
    for row in rows:
        current = by_id.get(row['feedback_id'])
        if current:
            if any(current.get(key) != row.get(key) for key in (
                    'agent_id','environment_id','environment_kind','environment_label','source_environment_id',
                    'promotion_batch_id','selected_by')):
                updates.append(row)
            else:
                unchanged.append(row['feedback_id'])
        else:
            updates.append(row)
    update_ids={row['feedback_id']for row in updates}
    body = {'version': 1, 'method': METHOD, 'rows': updates,
        'existingRows': [{'feedback_id': row['feedback_id'], 'fingerprint': int(row['fingerprint'])} for row in existing if row['feedback_id']in update_ids],
        'counts': {'latestPromotedFeedback': len(rows), 'mainEnvironmentPointersToAddOrUpdate': len(updates),
            'alreadyCurrent': len(unchanged)}, 'feedbackOrAnswerOrRcaRowsRewritten': 0}
    body['approvalHash'] = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    return body


def apply(client, reviewed: dict, actor: str, expected_hash: str, expected_count: int) -> dict:
    if reviewed.get('version') != 1 or reviewed.get('method') != METHOD or reviewed.get('approvalHash') != expected_hash:
        raise ValueError('Main-environment review hash/method changed; produce a fresh preview')
    rows = reviewed['rows']
    if len(rows) != expected_count or not rows or len(rows) > 5000:
        raise ValueError('The exact reviewed update count is required')
    values = [bigquery.StructQueryParameter(None,*[
        bigquery.ScalarQueryParameter(key,kind,row[key]) for key,kind in [
            ('feedback_id','STRING'),('agent_id','STRING'),('environment_id','STRING'),('environment_kind','STRING'),
            ('environment_label','STRING'),('source_environment_id','STRING'),('promotion_batch_id','STRING'),
            ('selected_by','STRING'),('revision','INT64')]]) for row in rows]
    current = [bigquery.StructQueryParameter(None,bigquery.ScalarQueryParameter('feedback_id','STRING',row['feedback_id']),
        bigquery.ScalarQueryParameter('fingerprint','INT64',row['fingerprint'])) for row in reviewed['existingRows']]
    current_type = bigquery.StructQueryParameterType(bigquery.ScalarQueryParameterType('STRING',name='feedback_id'),
        bigquery.ScalarQueryParameterType('INT64',name='fingerprint'))
    base = f'{settings.project_id}.{settings.dataset}'
    table = access_table_ref()
    # Versioned once after an earlier pre-merge freshness assertion correctly
    # aborted but consumed the original BigQuery job ID. Retries of this reviewed
    # v2 transaction keep the same ID; the failed v1 job is never replayed.
    job = 'backfill_main_environment_v2_' + expected_hash[:32]
    params = [bigquery.ArrayQueryParameter('items','STRUCT',values),bigquery.ArrayQueryParameter('old',current_type,current),
        bigquery.ScalarQueryParameter('actor','STRING',normalize_principal(actor)),
        bigquery.ScalarQueryParameter('expected','INT64',expected_count),
        bigquery.ScalarQueryParameter('hash','STRING',expected_hash)]
    sql = f"""DECLARE updated INT64 DEFAULT 0;
        BEGIN TRANSACTION;
        ASSERT (SELECT COUNT(*) FROM `{table}` WHERE LOWER(TRIM(email))=@actor)=1 AS 'MAIN_ENV_MANAGER_MISSING';
        ASSERT EXISTS(SELECT 1 FROM `{table}` WHERE LOWER(TRIM(email))=@actor AND active IS TRUE
            AND role IN ('reviewer','demo_admin') AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP())) AS 'MAIN_ENV_MANAGER_REQUIRED';
        ASSERT NOT EXISTS(SELECT 1 FROM `{table}` GROUP BY LOWER(TRIM(email)) HAVING COUNT(*)>1) AS 'MAIN_ENV_DUPLICATE_ACCESS';
        ASSERT NOT EXISTS(SELECT 1 FROM `{base}.feedback_main_environments` GROUP BY feedback_id,agent_id HAVING COUNT(*)>1) AS 'MAIN_ENV_DUPLICATE_POINTERS';
        ASSERT NOT EXISTS(SELECT 1 FROM UNNEST(@items) i JOIN `{base}.feedback_promotion_batches` selected
            ON selected.id=i.promotion_batch_id JOIN `{base}.feedback_promotion_batches` newer
            ON newer.id!=selected.id AND (newer.created_at>selected.created_at OR (newer.created_at=selected.created_at AND newer.id>selected.id))
            JOIN `{base}.feedback_workflow_jobs` newer_job ON newer_job.batch_id=newer.id AND newer_job.feedback_id=i.feedback_id
            AND newer_job.kind='retest' AND newer_job.target_id=newer.target_id) AS 'MAIN_ENV_PROMOTION_PREVIEW_STALE';
        ASSERT (SELECT COUNT(*) FROM `{base}.feedback_items` f JOIN UNNEST(@items) i ON f.feedback_id=i.feedback_id
            JOIN `{base}.feedback_promotion_batches` b ON b.id=i.promotion_batch_id AND b.target_id=i.environment_id
            WHERE f.agent_id=i.agent_id AND COALESCE(f.revision,1)=i.revision
                AND i.environment_kind IN ('nonprod','prod'))=@expected AS 'MAIN_ENV_SOURCE_OR_PROMOTION_CHANGED';
        ASSERT (SELECT COUNT(*) FROM `{base}.feedback_main_environments` WHERE feedback_id IN (SELECT feedback_id FROM UNNEST(@items)))
            =COALESCE(ARRAY_LENGTH(@old),0) AS 'MAIN_ENV_PREVIEW_STALE';
        ASSERT NOT EXISTS(SELECT 1 FROM `{base}.feedback_main_environments` m JOIN UNNEST(@old) o ON m.feedback_id=o.feedback_id
            WHERE FARM_FINGERPRINT(TO_JSON_STRING(m))!=o.fingerprint) AS 'MAIN_ENV_PREVIEW_STALE';
        MERGE `{base}.feedback_main_environments` m USING UNNEST(@items) i
            ON m.feedback_id=i.feedback_id AND m.agent_id=i.agent_id
            WHEN MATCHED THEN UPDATE SET environment_id=i.environment_id,environment_kind=i.environment_kind,
                environment_label=i.environment_label,source_environment_id=i.source_environment_id,
                promotion_batch_id=i.promotion_batch_id,revision=COALESCE(m.revision,0)+1,
                selected_by=i.selected_by,updated_at=CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT(feedback_id,agent_id,environment_id,environment_kind,environment_label,
                source_environment_id,promotion_batch_id,revision,selected_by,created_at,updated_at)
                VALUES(i.feedback_id,i.agent_id,i.environment_id,i.environment_kind,i.environment_label,
                    i.source_environment_id,i.promotion_batch_id,1,i.selected_by,CURRENT_TIMESTAMP(),CURRENT_TIMESTAMP());
        SET updated=@@row_count;
        ASSERT updated=@expected AS 'MAIN_ENV_UPDATE_COUNT_CHANGED';
        INSERT INTO `{base}.feedback_events`(event_id,feedback_id,event_type,created_at,actor,payload_json)
            SELECT CONCAT('main-environment-backfill:',@hash,':',i.feedback_id),i.feedback_id,'main_environment_selected',
                CURRENT_TIMESTAMP(),@actor,TO_JSON_STRING(STRUCT(i.source_environment_id AS original_environment_id,
                    i.environment_id AS main_environment_id,i.environment_kind AS main_environment_kind,
                    i.environment_label AS main_environment_label,i.promotion_batch_id AS promotion_batch_id,
                    i.revision AS feedback_revision,@hash AS reviewed_hash)) FROM UNNEST(@items) i;
        COMMIT TRANSACTION;
        SELECT updated;"""
    result = list(client.query(sql,job_config=bigquery.QueryJobConfig(query_parameters=params),location=settings.location,
        job_id=job,job_retry=None).result(job_retry=None))
    if not result or result[0]['updated'] != expected_count:
        raise RuntimeError('Main-environment backfill result is unconfirmed; never replay the write')
    return {'applied': True, 'mainEnvironmentPointersAddedOrUpdated': expected_count,
        'otherRecordsChanged': 0, 'originalFeedbackAndAnswerRcaRowsRewritten': 0,
        'auditEventsAdded': expected_count, 'promotionResultsOrAgentJobsCreated': 0,
        'providerCalls': 0, 'reviewedHash': expected_hash,'stableJobId':job}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview-out',type=Path,required=True)
    parser.add_argument('--result-out',type=Path)
    parser.add_argument('--expected-hash')
    parser.add_argument('--expected-count',type=int)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    def cloud(parts):
        value=subprocess.run(['gcloud',*parts,'--project='+settings.project_id,'--quiet'],capture_output=True,text=True,timeout=90)
        if value.returncode:raise RuntimeError('Same-account Google reauthentication required; credentials were not printed')
        return value.stdout.strip()
    actor=normalize_principal(cloud(['config','get-value','account']).lower())
    if actor!='dhruv.chawla@loreal.com':raise ValueError('Use the explicit reviewed operator; no identity switch is allowed')
    token=cloud(['auth','print-access-token','--account='+actor])
    request=urllib.request.Request('https://www.googleapis.com/oauth2/v2/userinfo',headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
    with urllib.request.urlopen(request,timeout=60)as response:identity=json.load(response)
    if identity.get('email','').lower()!=actor or identity.get('verified_email')is not True:raise ValueError('Verified Google operator identity mismatch')
    def refresh(_request,scopes=None):return cloud(['auth','print-access-token','--account='+actor]),datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(minutes=10)
    client=bigquery.Client(project=settings.project_id,credentials=Credentials(token,refresh_handler=refresh))
    review=preview(client);args.preview_out.write_text(json.dumps(review,indent=2,default=str));args.preview_out.chmod(0o600)
    if not args.apply:
        print(json.dumps({'applied':False,**review['counts'],'reviewedHash':review['approvalHash'],'feedbackRowsRewritten':0},indent=2));return
    if not args.expected_hash or args.expected_count is None or args.result_out is None:parser.error('--apply requires --expected-hash --expected-count and --result-out')
    if args.result_out.exists():raise RuntimeError('A backfill receipt already exists; inspect it rather than replaying')
    result=apply(client,review,actor,args.expected_hash,args.expected_count)
    args.result_out.write_text(json.dumps(result,indent=2));args.result_out.chmod(0o600)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
