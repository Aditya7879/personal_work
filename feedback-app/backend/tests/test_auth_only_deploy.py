from copy import deepcopy
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location('iam_authz_deploy', Path(__file__).resolve().parents[2] / 'deploy/iam_authz.py')
deploy = importlib.util.module_from_spec(spec); spec.loader.exec_module(deploy)


def service():
    return {'metadata':{'annotations':{'run.googleapis.com/ingress':'all'}},'spec':{'template':{
        'metadata':{'annotations':{'autoscaling.knative.dev/maxScale':'1','run.googleapis.com/cpu-throttling':'false'}},
        'spec':{'serviceAccountName':'existing-runtime','containerConcurrency':16,'containers':[{'image':'old-image',
            'env':[{'name':'FEEDBACK_WORKER_ENABLED','value':'true'},{'name':'FEEDBACK_AUTH_MODE','value':'private_demo'},
                {'name':'FEEDBACK_NEO4J_PASSWORD','valueFrom':{'secretKeyRef':{'name':'existing-secret','key':'1'}}}],
            'resources':{'limits':{'cpu':'1','memory':'1Gi'}}}]}}}}


def test_auth_update_only_changes_image_and_the_explicit_auth_environment_fields():
    args = deploy.update_arguments(deploy.API, 'new-image', 'project.dataset.application_access_grants')
    combined = ' '.join(args)
    assert 'FEEDBACK_AUTH_MODE=google_iam' in combined and 'FEEDBACK_AUTHZ_TABLE=' in combined
    for prohibited in ['FEEDBACK_WORKER_ENABLED','--set-secrets','--service-account','--min-instances','--max-instances','--cpu','--env-vars-file','--allow-unauthenticated','FEEDBACK_AGENT_TARGETS_JSON']:
        assert prohibited not in combined
    assert deploy.update_arguments(deploy.UI, 'new-ui', 'table') == ['run','services','update',deploy.UI,'--image=new-ui','--region=europe-west1']


def test_preservation_comparison_ignores_only_image_and_auth_but_detects_rca_worker_secret_and_scaling_changes():
    before = service(); after = deepcopy(before)
    after['spec']['template']['spec']['containers'][0]['image'] = 'new-image'
    after['spec']['template']['spec']['containers'][0]['env'][1]['value'] = 'google_iam'
    assert deploy.preserved_configuration(before) == deploy.preserved_configuration(after)
    for path in ['worker','secret','scaling']:
        changed = deepcopy(after)
        if path == 'worker': changed['spec']['template']['spec']['containers'][0]['env'][0]['value'] = 'false'
        if path == 'secret': changed['spec']['template']['spec']['containers'][0]['env'][2]['valueFrom']['secretKeyRef']['key'] = '2'
        if path == 'scaling': changed['spec']['template']['metadata']['annotations']['autoscaling.knative.dev/maxScale'] = '2'
        assert deploy.preserved_configuration(before) != deploy.preserved_configuration(changed)


def test_reviewed_image_guard_detects_a_concurrent_application_deployment():
    before = service(); after = deepcopy(before)
    after['spec']['template']['spec']['containers'][0]['image'] = 'another-users-new-image'
    assert deploy.service_images(before) != deploy.service_images(after)
