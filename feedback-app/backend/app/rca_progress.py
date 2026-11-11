"""Processing progress never implies a verified RCA, reviewed truth or resolution."""
import re


RCA_TRIAGE_MESSAGE = 'Automated RCA is ready for human review. The diagnosis is not verified and this feedback is not resolved.'


def completed_rca(suggestion: dict) -> bool:
    return (suggestion.get('rca_suggestion_status') in {'sonnet_suggested', 'auto_classified'}
        and suggestion.get('suggested_rca') not in {None, '', 'insufficient_evidence', 'unknown'}
        and bool(str(suggestion.get('rca_rationale') or '').strip())
        and suggestion.get('rca_retrieval_status') not in {'unavailable', 'no_matches'}
        and any(isinstance(item, dict) and (item.get('evidence_id') or item.get('source'))
            for item in (suggestion.get('rca_evidence') or [])))


def current_source_answer_id(record) -> str:
    value = str(record.runContext.get('submission_answer_id') or '')
    return value if value.startswith(f'submission:{record.id}:r') else f'original:{record.id}'


def source_answer_id_sql(alias: str = '') -> str:
    if alias and not re.fullmatch(r'[a-z_]+', alias):
        raise ValueError('Internal SQL alias required')
    p = alias + '.' if alias else ''
    value = f"JSON_VALUE({p}run_context_json,'$.submission_answer_id')"
    return f"IF(STARTS_WITH({value},CONCAT('submission:',{p}feedback_id,':r')),{value},CONCAT('original:',{p}feedback_id))"


def source_triage_guard(alias: str = '') -> str:
    if alias and not re.fullmatch(r'[a-z_]+', alias):
        raise ValueError('Internal SQL alias required')
    p = alias + '.' if alias else ''
    return (f"{p}state='Submitted' AND COALESCE(NULLIF({p}public_status,''),'Received') IN ('Received','In review') "
        f"AND {p}resolved_at IS NULL AND NULLIF(TRIM({p}confirmed_rca),'') IS NULL")
