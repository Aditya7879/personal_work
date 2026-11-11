from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'deploy'))
try: import app_update as deploy
finally: sys.path.pop(0)
from test_auth_only_deploy import service


def test_update_arguments_change_only_an_image_not_any_runtime_security_or_worker_setting():
    assert deploy.image_update_arguments(deploy.UI,'reviewed-image') == ['run','services','update',deploy.UI,'--region=europe-west1','--image=reviewed-image']


def test_image_only_signature_preserves_even_auth_settings_secret_versions_and_iap_flags():
    before = service(); after = deepcopy(before)
    after['spec']['template']['spec']['containers'][0]['image'] = 'new-image'
    assert deploy.runtime_signature(before) == deploy.runtime_signature(after)
    for field in ('auth','worker','secret','iap','scaling'):
        changed = deepcopy(after)
        if field == 'auth': changed['spec']['template']['spec']['containers'][0]['env'][1]['value'] = 'mock'
        if field == 'worker': changed['spec']['template']['spec']['containers'][0]['env'][0]['value'] = 'false'
        if field == 'secret': changed['spec']['template']['spec']['containers'][0]['env'][2]['valueFrom']['secretKeyRef']['key'] = '2'
        if field == 'iap': changed['metadata']['annotations']['run.googleapis.com/iap-enabled'] = 'false'
        if field == 'scaling': changed['spec']['template']['metadata']['annotations']['autoscaling.knative.dev/maxScale'] = '2'
        assert deploy.runtime_signature(before) != deploy.runtime_signature(changed)
