"""Explicit, audited source-review metadata repair using saved RCA only. No model calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from google.cloud import bigquery

from app.access_repository import access_table_ref
from app.bigquery import BigQueryRepository
from app.config import settings
from app.rca_progress import RCA_TRIAGE_MESSAGE, source_answer_id_sql, source_triage_guard


def candidate_sql(repo) -> str:
    # Rank all current-source diagnoses before checking success/cutoff, so an
    # older success cannot hide a newer inconclusive/failed source analysis.
    return f"""WITH ranked AS (
        SELECT f.feedback_id,COALESCE(f.revision,1) AS revision,r.answer_id,r.id AS diagnosis_id,
            FARM_FINGERPRINT(TO_JSON_STRING(f)) AS row_fingerprint,
            TO_JSON_STRING(STRUCT(f.state AS state,f.public_status AS public_status,
                f.public_message AS public_message,f.updated_at AS updated_at)) AS before_json,
            r.created_at AS analysis_created_at,SAFE.PARSE_JSON(r.payload_json) AS diagnosis_json,j.status AS job_status,
            j.id AS job_id,f.rca_suggestion_status AS current_rca_status,f.suggested_rca AS current_category,
            ROW_NUMBER() OVER(PARTITION BY f.feedback_id ORDER BY r.created_at DESC,r.id DESC) AS position
        FROM `{repo.feedback_ref}` f
        JOIN `{repo.workflow_table('feedback_rca_versions')}` r ON r.feedback_id=f.feedback_id AND r.answer_id={source_answer_id_sql('f')}
        JOIN `{repo.workflow_table('feedback_answer_versions')}` a ON a.id=r.answer_id AND a.feedback_id=f.feedback_id
        LEFT JOIN `{repo.workflow_table('feedback_workflow_jobs')}` j ON j.id=r.attempt_id AND j.feedback_id=f.feedback_id
        WHERE {source_triage_guard('f')} AND (COALESCE(ARRAY_LENGTH(@feedback_ids),0)=0 OR f.feedback_id IN UNNEST(@feedback_ids))
            AND JSON_VALUE(SAFE.PARSE_JSON(a.payload_json),'$.kind') IN ('original','submission_edit')
            AND COALESCE(JSON_VALUE(SAFE.PARSE_JSON(a.payload_json),'$.question'),'')=COALESCE(f.question,'')
            AND COALESCE(JSON_VALUE(SAFE.PARSE_JSON(a.payload_json),'$.answer'),'')=COALESCE(f.answer,'')
            AND (j.id IS NULL OR (COALESCE(JSON_VALUE(SAFE.PARSE_JSON(j.payload_json),'$.prompt'),'')=COALESCE(f.question,'')
                AND COALESCE(JSON_VALUE(SAFE.PARSE_JSON(j.payload_json),'$.generatedAnswer'),'')=COALESCE(f.answer,'')))
            AND COALESCE(SAFE_CAST(JSON_VALUE(SAFE.PARSE_JSON(r.payload_json),'$.revision') AS INT64),j.revision,
                SAFE_CAST(JSON_VALUE(SAFE.PARSE_JSON(a.payload_json),'$.revision') AS INT64),0)=COALESCE(f.revision,1)
            AND (j.kind IN ('enrich','rca') OR (j.id IS NULL AND STARTS_WITH(r.id,'rca:direct:')))
    ) SELECT feedback_id,revision,answer_id,diagnosis_id,row_fingerprint,before_json FROM ranked
        WHERE position=1 AND (job_status='completed' OR job_id IS NULL)
            AND (@cutoff IS NULL OR analysis_created_at<=@cutoff)
            AND JSON_VALUE(diagnosis_json,'$.suggestionStatus') IN ('sonnet_suggested','auto_classified')
            AND JSON_VALUE(diagnosis_json,'$.category') NOT IN ('','insufficient_evidence','unknown')
            AND NULLIF(TRIM(JSON_VALUE(diagnosis_json,'$.rationale')),'') IS NOT NULL
            AND COALESCE(JSON_VALUE(diagnosis_json,'$.retrievalStatus'),'available') NOT IN ('unavailable','no_matches')
            AND EXISTS(SELECT 1 FROM UNNEST(JSON_QUERY_ARRAY(diagnosis_json,'$.evidence')) e
                WHERE NULLIF(COALESCE(JSON_VALUE(e,'$.evidence_id'),JSON_VALUE(e,'$.source')),'') IS NOT NULL)
            AND current_rca_status=JSON_VALUE(diagnosis_json,'$.suggestionStatus')
            AND current_category=JSON_VALUE(diagnosis_json,'$.category')
        ORDER BY feedback_id LIMIT 100"""


def preview(repo, feedback_ids=(), cutoff=None) -> dict:
    rows = repo.workflow_query(candidate_sql(repo), [bigquery.ArrayQueryParameter('feedback_ids','STRING',list(feedback_ids)),
        bigquery.ScalarQueryParameter('cutoff','TIMESTAMP',cutoff)])
    return {'version':1,'action':'reconcile_current_source_rca_triage','cutoff':cutoff.isoformat() if cutoff else None,
        'candidateCount':len(rows),'items':[{'feedbackId':row['feedback_id'],'revision':row['revision'],
            'answerId':row['answer_id'],'diagnosisId':row['diagnosis_id'],'rowFingerprint':str(row['row_fingerprint']),
            'before':json.loads(row['before_json'])} for row in rows], 'modelCalls':0,'databaseWrites':0}


def apply_reconciliation(repo, approved, actor, expected_count) -> dict:
    items = approved.get('items') or []
    if (approved.get('version') != 1 or approved.get('action') != 'reconcile_current_source_rca_triage'
            or not items or len(items) != expected_count or len({item['feedbackId'] for item in items}) != len(items)):
        raise ValueError('An exact, non-empty reviewed preview and expected count are required')
    structs = [bigquery.StructQueryParameter(None,
        bigquery.ScalarQueryParameter('feedback_id','STRING',item['feedbackId']),
        bigquery.ScalarQueryParameter('revision','INT64',item['revision']),
        bigquery.ScalarQueryParameter('answer_id','STRING',item['answerId']),
        bigquery.ScalarQueryParameter('diagnosis_id','STRING',item['diagnosisId']),
        bigquery.ScalarQueryParameter('fingerprint','INT64',int(item['rowFingerprint']))) for item in items]
    cutoff = datetime.fromisoformat(approved['cutoff'].replace('Z','+00:00')) if approved.get('cutoff') else None
    parameters = [bigquery.ArrayQueryParameter('feedback_ids','STRING',[item['feedbackId'] for item in items]),
        bigquery.ScalarQueryParameter('cutoff','TIMESTAMP',cutoff),bigquery.ArrayQueryParameter('approved','STRUCT',structs),
        bigquery.ScalarQueryParameter('actor','STRING',actor),bigquery.ScalarQueryParameter('message','STRING',RCA_TRIAGE_MESSAGE)]
    sql = f"""DECLARE changed INT64 DEFAULT 0;
        BEGIN TRANSACTION;
        ASSERT (SELECT COUNT(*) FROM `{access_table_ref()}` WHERE LOWER(TRIM(email))=@actor)=1 AS 'REVIEWER_REQUIRED';
        ASSERT EXISTS(SELECT 1 FROM `{access_table_ref()}` WHERE LOWER(TRIM(email))=@actor AND active IS TRUE
            AND role='reviewer' AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP())) AS 'REVIEWER_REQUIRED';
        CREATE TEMP TABLE chosen AS SELECT c.* FROM ({candidate_sql(repo)}) c JOIN UNNEST(@approved) p
            ON c.feedback_id=p.feedback_id AND c.revision=p.revision AND c.answer_id=p.answer_id
                AND c.diagnosis_id=p.diagnosis_id AND c.row_fingerprint=p.fingerprint;
        ASSERT (SELECT COUNT(*) FROM chosen)=ARRAY_LENGTH(@approved) AS 'RCA_TRIAGE_PREVIEW_STALE';
        ASSERT NOT EXISTS(SELECT 1 FROM `{repo.events_ref}` e JOIN chosen c
            ON e.event_id=CONCAT('rca-triage-reconcile:',c.diagnosis_id)) AS 'RCA_TRIAGE_ALREADY_RECORDED';
        UPDATE `{repo.feedback_ref}` f SET state='Triaged',public_status='In review',
            public_message=COALESCE(f.public_message,@message),updated_at=CURRENT_TIMESTAMP()
            FROM chosen c WHERE f.feedback_id=c.feedback_id AND COALESCE(f.revision,1)=c.revision
                AND FARM_FINGERPRINT(TO_JSON_STRING(f))=c.row_fingerprint AND {source_triage_guard('f')};
        SET changed=@@row_count;
        ASSERT changed=ARRAY_LENGTH(@approved) AS 'RCA_TRIAGE_CONCURRENT_CHANGE';
        INSERT INTO `{repo.events_ref}`(event_id,feedback_id,event_type,created_at,actor,payload_json)
            SELECT CONCAT('rca-triage-reconcile:',diagnosis_id),feedback_id,'rca_auto_triaged',CURRENT_TIMESTAMP(),@actor,
                TO_JSON_STRING(STRUCT('Triaged' AS state,'Submitted' AS previous_state,'In review' AS public_status,
                    @message AS public_message,revision AS revision,answer_id AS answer_id,diagnosis_id AS diagnosis_id,
                    FALSE AS assessment_verified,TRUE AS saved_rca_only,before_json AS previous_review_metadata))
            FROM chosen;
        COMMIT TRANSACTION;
        SELECT changed;"""
    digest = hashlib.sha256(json.dumps(approved,sort_keys=True).encode()).hexdigest()[:32]
    rows = list(repo.client.query(sql,job_config=bigquery.QueryJobConfig(query_parameters=parameters),location=settings.location,
        job_id='rca_triage_reconcile_' + digest,job_retry=None).result(job_retry=None))
    if not rows or rows[0]['changed'] != expected_count:
        raise RuntimeError('The guarded metadata repair did not confirm the expected count; verify state before another attempt')
    return {'applied':True,'updated':rows[0]['changed'],'feedbackIds':[item['feedbackId'] for item in items],
        'eventIds':['rca-triage-reconcile:' + item['diagnosisId'] for item in items],
        'onlyReviewMetadataChanged':True,'answerOrRcaVersionsChanged':False,'modelCalls':0,'jobsRetried':0}


def verified_operator() -> str:
    def cloud(args):
        result = subprocess.run(['gcloud',*args,'--quiet'],capture_output=True,text=True,timeout=60)
        if result.returncode: raise RuntimeError('A verified company Google operator is required; credentials were not logged')
        return result.stdout.strip()
    account = cloud(['config','get-value','account']).lower()
    token = cloud(['auth','print-identity-token','--account=' + account])
    claims = id_token.verify_oauth2_token(token,GoogleRequest(),audience=None)
    if claims.get('email','').lower() != account or claims.get('email_verified') is not True or not account.endswith('@loreal.com'):
        raise ValueError('Use the intended real company Google operator identity')
    return account


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feedback-id',action='append',default=[])
    parser.add_argument('--before',help='Only analysis saved at/before this UTC timestamp can qualify')
    parser.add_argument('--preview-out',type=Path)
    parser.add_argument('--approved-preview',type=Path)
    parser.add_argument('--expected-count',type=int)
    parser.add_argument('--result-out',type=Path)
    parser.add_argument('--apply',action='store_true')
    args = parser.parse_args()
    if settings.project_id != 'oa-apmena-techsandbox-ap-dv' or settings.dataset != 'agent_quality':
        raise ValueError('This reviewed repair targets only the existing feedback dataset')
    repo = BigQueryRepository()
    if not args.apply:
        cutoff = datetime.fromisoformat(args.before.replace('Z','+00:00')) if args.before else None
        result = preview(repo,args.feedback_id,cutoff)
        if args.preview_out: args.preview_out.write_text(json.dumps(result,indent=2))
    else:
        if not args.approved_preview or args.expected_count is None:
            parser.error('--apply requires --approved-preview and --expected-count')
        result = apply_reconciliation(repo,json.loads(args.approved_preview.read_text()),verified_operator(),args.expected_count)
        if args.result_out: args.result_out.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
