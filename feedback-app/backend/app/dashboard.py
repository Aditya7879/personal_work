"""Environment-aware reporting: cases are distinct, checks follow their saved answer."""
import json

from google.cloud import bigquery
from .config import settings


def load_overview(repo, environment_id: str | None = None) -> dict:
    selected = repo.get_agent_environment(environment_id) if environment_id else None
    source_kind = repo._source_environment_kind('f')
    parameters = [bigquery.ScalarQueryParameter('environment_id', 'STRING', environment_id), *repo._environment_parameters()]
    sql = f"""
        WITH source_feedback AS (
            SELECT f.*,COALESCE(JSON_VALUE(f.run_context_json,'$.environment_id'),
                CASE {source_kind} WHEN 'nonprod' THEN @legacy_nonprod WHEN 'prod' THEN @legacy_prod END) AS origin_environment_id
            FROM `{repo.feedback_ref}` f WHERE f.agent_id=@legacy_agent
        ), scoped_feedback AS (
            SELECT * FROM source_feedback f WHERE @environment_id IS NULL OR origin_environment_id=@environment_id
                OR f.feedback_id IN (SELECT feedback_id FROM `{repo.workflow_table('feedback_workflow_jobs')}` WHERE kind='retest' AND target_id=@environment_id)
        ), scoped_jobs AS (
            SELECT j.* FROM `{repo.workflow_table('feedback_workflow_jobs')}` j JOIN scoped_feedback f ON f.feedback_id=j.feedback_id
            WHERE j.kind='retest' AND (@environment_id IS NULL OR j.target_id=@environment_id)
        ), case_environments AS (
            SELECT feedback_id,origin_environment_id AS environment_id FROM scoped_feedback
            UNION DISTINCT SELECT feedback_id,target_id FROM scoped_jobs
        ), latest_saved_answers AS (
            SELECT v.feedback_id,v.id,v.created_at,j.target_id AS environment_id,j.result_json
            FROM `{repo.workflow_table('feedback_answer_versions')}` v JOIN scoped_jobs j ON v.attempt_id=j.id
            JOIN scoped_feedback f ON f.feedback_id=v.feedback_id
            WHERE JSON_VALUE(v.payload_json,'$.kind')='retest' AND j.revision=COALESCE(f.revision,1)
                AND JSON_VALUE(v.payload_json,'$.question')=f.question
            QUALIFY ROW_NUMBER() OVER(PARTITION BY v.feedback_id,j.target_id ORDER BY v.created_at DESC,v.id DESC)=1
        ), latest_diagnoses AS (
            SELECT v.* FROM `{repo.workflow_table('feedback_rca_versions')}` v
            WHERE v.feedback_id IN (SELECT feedback_id FROM scoped_feedback)
            QUALIFY ROW_NUMBER() OVER(PARTITION BY v.feedback_id,v.answer_id ORDER BY v.created_at DESC,v.id DESC)=1
        ), assessments AS (
            SELECT c.feedback_id,c.environment_id,
                CASE WHEN a.id IS NOT NULL THEN JSON_VALUE(v.payload_json,'$.category')
                    WHEN c.environment_id IS NOT DISTINCT FROM f.origin_environment_id THEN COALESCE(f.confirmed_rca,f.suggested_rca,JSON_VALUE(o.payload_json,'$.category')) END AS category,
                CASE WHEN a.id IS NOT NULL THEN JSON_VALUE(v.payload_json,'$.defect')
                    WHEN c.environment_id IS NOT DISTINCT FROM f.origin_environment_id THEN COALESCE(f.subcategory,f.rca_suggested_subcategory,JSON_VALUE(o.payload_json,'$.defect')) END AS subcategory,
                CASE WHEN a.id IS NOT NULL THEN COALESCE(JSON_VALUE(v.payload_json,'$.suggestionStatus')='auto_classified',FALSE)
                    ELSE COALESCE(f.rca_suggestion_status='auto_classified',FALSE) END AS auto_classified,
                CASE WHEN a.id IS NOT NULL THEN NOT COALESCE(SAFE_CAST(JSON_VALUE(v.payload_json,'$.verified') AS BOOL),FALSE)
                    ELSE COALESCE(f.rca_review_required,TRUE) END AS review_required,
                JSON_VALUE(a.result_json,'$.assessment') AS verdict,
                CASE WHEN a.id IS NOT NULL THEN COALESCE(v.created_at,a.created_at)
                    ELSE COALESCE(o.created_at,f.rca_suggested_at,f.created_at) END AS assessed_at
            FROM case_environments c JOIN scoped_feedback f ON f.feedback_id=c.feedback_id
            LEFT JOIN latest_saved_answers a ON a.feedback_id=c.feedback_id AND a.environment_id IS NOT DISTINCT FROM c.environment_id
            LEFT JOIN latest_diagnoses v ON v.answer_id=a.id AND v.feedback_id=c.feedback_id
            LEFT JOIN latest_diagnoses o ON o.feedback_id=f.feedback_id AND o.answer_id=COALESCE(JSON_VALUE(f.run_context_json,'$.submission_answer_id'),CONCAT('original:',f.feedback_id))
            WHERE @environment_id IS NULL OR c.environment_id=@environment_id
        ), days AS (
            SELECT day FROM UNNEST(GENERATE_DATE_ARRAY(DATE_SUB(CURRENT_DATE(),INTERVAL 29 DAY),CURRENT_DATE())) day
        ), feedback_trend AS (
            SELECT FORMAT_DATE('%Y-%m-%d',days.day) AS date,COUNT(f.feedback_id) AS feedback_count,
                COUNTIF(f.user_verdict IN ('Incorrect','Unsafe or misleading')) AS issue_count
            FROM days LEFT JOIN scoped_feedback f ON DATE(f.created_at)=days.day
                AND (@environment_id IS NULL OR f.origin_environment_id=@environment_id) GROUP BY days.day
        ), state_breakdown AS (
            SELECT COALESCE(state,'Unknown') AS state,COUNT(*) AS count FROM scoped_feedback GROUP BY state
        ), verdict_breakdown AS (
            SELECT COALESCE(user_verdict,'Not specified') AS verdict,COUNT(*) AS count FROM scoped_feedback GROUP BY verdict
        ), root_cause_breakdown AS (
            SELECT category,COUNT(*) AS count,COUNTIF(auto_classified) AS auto_count,COUNTIF(review_required) AS review_count
            FROM assessments WHERE category IS NOT NULL GROUP BY category ORDER BY count DESC,category LIMIT 8
        ), subcategory_breakdown AS (
            SELECT category,subcategory,COUNT(*) AS count FROM assessments WHERE category IS NOT NULL AND subcategory IS NOT NULL
            GROUP BY category,subcategory ORDER BY count DESC,subcategory LIMIT 6
        ), assessment_breakdown AS (
            SELECT verdict,COUNT(*) AS count FROM assessments WHERE verdict IS NOT NULL GROUP BY verdict ORDER BY verdict
        ), evaluation_trend AS (
            SELECT evaluation_id,label,completed_at,pass_rate,passed_cases,total_cases FROM `{repo.evaluations_ref}`
            WHERE status='completed' AND pass_rate IS NOT NULL ORDER BY completed_at DESC LIMIT 10
        ), latest_case_assessment AS (
            SELECT * FROM assessments QUALIFY ROW_NUMBER() OVER(PARTITION BY feedback_id ORDER BY assessed_at DESC,environment_id)=1
        ), recent_feedback AS (
            SELECT f.feedback_id,f.title,f.state,f.severity,f.user_verdict,a.category AS root_cause,
                GREATEST(f.updated_at,COALESCE((SELECT MAX(j.updated_at) FROM scoped_jobs j WHERE j.feedback_id=f.feedback_id),f.updated_at)) AS updated_at
            FROM scoped_feedback f LEFT JOIN latest_case_assessment a ON a.feedback_id=f.feedback_id
            ORDER BY updated_at DESC,f.feedback_id LIMIT 6
        )
        SELECT
            (SELECT COUNT(*) FROM scoped_feedback) AS feedback_total,
            (SELECT COUNTIF(state NOT IN ('Review complete','Approved for dataset','Rejected','Duplicate') AND COALESCE(public_status,'Received') NOT IN ('Resolved','Not planned','Duplicate')) FROM scoped_feedback) AS feedback_needing_review,
            (SELECT COUNT(*) FROM source_feedback) AS all_feedback_total,
            (SELECT COUNTIF(@environment_id IS NULL OR origin_environment_id=@environment_id) FROM scoped_feedback) AS native_feedback_count,
            (SELECT COUNTIF(@environment_id IS NOT NULL AND origin_environment_id IS DISTINCT FROM @environment_id) FROM scoped_feedback) AS promoted_feedback_count,
            (SELECT COUNTIF(origin_environment_id IS NULL) FROM scoped_feedback) AS unassigned_feedback_count,
            (SELECT COUNT(*) FROM scoped_jobs) AS retest_count,
            (SELECT COUNTIF(status='queued') FROM scoped_jobs) AS queued_retest_count,
            (SELECT COUNTIF(status='running') FROM scoped_jobs) AS running_retest_count,
            (SELECT COUNTIF(status='failed') FROM scoped_jobs) AS failed_retest_count,
            (SELECT COUNTIF(category IS NOT NULL) FROM assessments) AS rca_runs_count,
            (SELECT COUNTIF(category IS NOT NULL AND auto_classified) FROM assessments) AS auto_classified_count,
            (SELECT COUNTIF(category IS NOT NULL AND review_required) FROM assessments) AS rca_review_count,
            (SELECT COUNT(*) FROM `{repo.golden_datasets_ref}`) AS golden_dataset_count,
            (SELECT COUNTIF(c.state='approved') FROM `{repo.golden_datasets_ref}` d LEFT JOIN `{repo.golden_cases_ref}` c ON c.dataset_id=d.dataset_id AND c.dataset_version=d.current_version) AS approved_case_count,
            (SELECT pass_rate FROM evaluation_trend ORDER BY completed_at DESC LIMIT 1) AS latest_pass_rate,
            (SELECT evaluation_id FROM evaluation_trend ORDER BY completed_at DESC LIMIT 1) AS latest_evaluation_id,
            TO_JSON_STRING(ARRAY(SELECT AS STRUCT * FROM feedback_trend ORDER BY date)) AS feedback_trend_json,
            TO_JSON_STRING(ARRAY(SELECT AS STRUCT * FROM state_breakdown ORDER BY count DESC,state)) AS state_breakdown_json,
            TO_JSON_STRING(ARRAY(SELECT AS STRUCT * FROM verdict_breakdown ORDER BY count DESC,verdict)) AS verdict_breakdown_json,
            TO_JSON_STRING(ARRAY(SELECT AS STRUCT * FROM root_cause_breakdown ORDER BY count DESC,category)) AS root_cause_breakdown_json,
            TO_JSON_STRING(ARRAY(SELECT AS STRUCT * FROM subcategory_breakdown ORDER BY count DESC,subcategory)) AS subcategory_breakdown_json,
            TO_JSON_STRING(ARRAY(SELECT AS STRUCT * FROM assessment_breakdown ORDER BY verdict)) AS assessment_breakdown_json,
            TO_JSON_STRING(ARRAY(SELECT AS STRUCT * FROM evaluation_trend ORDER BY completed_at DESC)) AS evaluation_trend_json,
            TO_JSON_STRING(ARRAY(SELECT AS STRUCT * FROM recent_feedback ORDER BY updated_at DESC,feedback_id)) AS recent_feedback_json
    """
    row = next(iter(repo.client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=parameters), location=settings.location).result()), {})
    result = dict(row)
    for field in ('feedback_trend', 'state_breakdown', 'verdict_breakdown', 'root_cause_breakdown', 'subcategory_breakdown', 'assessment_breakdown', 'evaluation_trend', 'recent_feedback'):
        result[field] = json.loads(result.pop(field + '_json', '[]') or '[]')
    result['evaluation_trend'].reverse()
    result['scope'] = {'environmentId': environment_id, 'environmentName': selected['name'] if selected else 'All environments',
        'assets': 'agent_wide', 'evaluations': 'agent_wide_legacy', 'quality': 'latest_saved_answer_per_environment', 'reviewProgress': 'source_report_workflow'}
    return result
