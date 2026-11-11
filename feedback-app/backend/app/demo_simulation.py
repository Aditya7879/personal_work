"""Clearly labelled fixtures for the isolated demo; never a production fallback."""
from __future__ import annotations

from threading import Lock

from .config import settings
from .role_demo import require_demo_scope
from .demo_context import is_demo


_DRAIN = Lock()
CORPUS = 'isolated-demo-fixtures-v1'


def targets():
    from .agent_targets import AgentTarget
    require_demo_scope()
    return [AgentTarget('neo-'+kind,settings.default_agent_id,kind,'NEO · Demo '+label,
        url='https://demo.invalid/'+kind,auth='none',protocol='quality_json',timeout_seconds=1)
        for kind,label in [('nonprod','Non-production'),('prod','Production')]]


def generated_answer(target,question):
    require_demo_scope()
    return {'answer':'SIMULATED DEMO RESPONSE — This sample revised response is ready for its reporter to review. '
            'No NEO or model endpoint was called. Sample question: '+question,
        'agentVersion':'demo-simulated','modelVersion':'demo-simulated','corpusVersion':CORPUS,
        'runId':None,'conversationId':None,'sources':[],'latencyMs':0,'protocol':'demo_simulation'}


class DemoEvidence:
    backend_name='demo_fixture'
    corpus_version=CORPUS

    def search(self,*_args,**_kwargs):
        require_demo_scope()
        return [{'evidence_id':'DEMO-REFERENCE-1','source':'Isolated demo reference — synthetic',
            'page':'1','element_id':'demo-reference-1','origin':'demo_fixture','corpus_version':CORPUS,
            'context':'Synthetic demonstration reference: revised answers require the original reporter’s explicit confirmation. '
                      'This is not a real business rule or a retrieved company document.',
            'excerpt':'Synthetic demonstration reference only.','score':1.0}]

    def stats(self):
        require_demo_scope()
        return {'backend':'demo_fixture','connected':True,'simulated':True,'documents':1,'records':1,'corpusVersion':CORPUS}

    def close(self):pass


def rca_suggestion():
    require_demo_scope()
    return {'suggested_rca':'reasoning_error','suggested_rca_confidence':0.5,
        'rca_subcategory':'Simulated demo diagnosis','rca_rationale':'SIMULATION ONLY: this canned diagnosis demonstrates '
            'the review workflow. No graph, embedding service or LLM was consulted. Human review is still required.',
        'rca_required_claims':[],'rca_supported_claims':[],'rca_missing_claims':[],'rca_contradicted_claims':[],
        'rca_evidence':DemoEvidence().search(),'rca_review_required':True,'rca_auto_accepted':False,
        'rca_suggestion_status':'sonnet_suggested','rca_suggested_at':None,
        'rca_evidence_backend':'demo_fixture','rca_corpus_version':CORPUS,'rca_retrieval_status':'available'}


def comparison(original,updated):
    require_demo_scope()
    same = original.get('prompt')==updated.get('prompt') and bool(original.get('generatedAnswer'))
    return {'assessment':'appears_fixed'if same else'inconclusive',
        'reason':'SIMULATION ONLY: a canned comparison for the demo. This is not a correctness judgement from an AI service. '
                 'Only the original reporter can explicitly confirm a current, same-environment result.',
        'reviewRequired':True,'confidence':0.5,'evidenceIds':['DEMO-REFERENCE-1']}


def drain(repo):
    """Explicit demo actions finish their simulated work synchronously, with leases."""
    if not is_demo():return
    require_demo_scope()
    if repo.dataset_ref!=f'{settings.project_id}.agent_quality_demo':raise RuntimeError('Demo simulation cannot run against live storage')
    from .workflow_worker import process_feedback_job
    with _DRAIN:
        for _ in range(25):
            job=repo.claim_feedback_job()
            if not job:return
            try:process_feedback_job(repo,job)
            except Exception:
                repo.complete_feedback_job(job,error='The demo simulation did not finish. No real provider was called.')
                raise


def seed_feedback(repo):
    require_demo_scope()
    if repo.dataset_ref!=f'{settings.project_id}.agent_quality_demo':raise RuntimeError('Demo seed cannot target live storage')
    from .models import FeedbackCreate
    for email,title,question in [
        ('alex.requester@example.test','Demo: sample approval rule','Demo only: explain the fictional sample approval rule.'),
        ('alex.requester@example.test','Demo: incomplete sample answer','Demo only: list the steps of the fictional training process.'),
        ('sam.requester@example.test','Demo: second reporter’s case','Demo only: demonstrate a feedback case owned by another reporter.'),
    ]:
        row=repo.create_feedback(FeedbackCreate(title=title,agent_id=settings.default_agent_id,environment='nonprod',
            question=question,answer='SIMULATED ORIGINAL CAPTURE — a deliberately incomplete sample answer.',
            user_verdict='Incorrect',issue_categories=['demo_sample'],feedback_text='Synthetic sample feedback for an isolated role-switching demo.',
            expected_behavior='Show a revised sample response and ask its original demo reporter to confirm.',
            impact='Medium',reporter=email,business_domain='Demo Operations',business_subdomain='Synthetic training flow',
            source='isolated_demo_seed',run_context={'demo_simulated':True,'environment_id':'neo-nonprod',
                'environment_kind':'nonprod','environment_label':'Demo Non-production'}))
        repo.ensure_original(row)


def reset_demo(repo,actor):
    require_demo_scope()
    if repo.dataset_ref!=f'{settings.project_id}.agent_quality_demo':raise RuntimeError('Demo reset cannot target live storage')
    names=['feedback_notifications','feedback_workflow_jobs','feedback_rca_versions','feedback_answer_versions',
        'feedback_promotion_batches','feedback_main_environments','feedback_owner_events','feedback_owner_links','feedback_events','feedback_items',
        'evaluation_case_results','evaluation_runs','golden_cases','golden_datasets']
    # Reset only sample content, never access grants, controller audits or live tables.
    repo.workflow_query('BEGIN TRANSACTION;\n'+'\n'.join(f'DELETE FROM `{repo.dataset_ref}.{name}` WHERE TRUE;'for name in names)+'\nCOMMIT TRANSACTION;')
    seed_feedback(repo)
    from .cache import read_cache
    read_cache.invalidate()
    return {'reset':True,'dataset':'agent_quality_demo','simulatedAi':True,'seededFeedback':3}
