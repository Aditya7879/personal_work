from copy import deepcopy
from pathlib import Path
import sys
import json
from io import BytesIO

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy'))
try:
    import browser_iap as deploy
finally:
    sys.path.pop(0)

from test_auth_only_deploy import service


def test_browser_migration_only_enables_frontend_iap_and_exact_identity_audiences():
    api = ' '.join(deploy.browser_update_arguments(deploy.API, 'https://frontend.run.app', 'loreal.com'))
    ui = ' '.join(deploy.browser_update_arguments(deploy.UI, 'https://frontend.run.app', 'loreal.com'))
    assert '--iap' in ui and '--iap' not in api
    assert 'FEEDBACK_GOOGLE_IAP_AUDIENCE=' + deploy.AUDIENCE in api
    assert 'FEEDBACK_FRONTEND_ORIGIN=https://frontend.run.app' in ui
    for prohibited in ['--allow-unauthenticated','--no-invoker-iam-check','FEEDBACK_WORKER_ENABLED','FEEDBACK_AGENT_TARGETS_JSON',
        '--set-secrets','--service-account','--min-instances','--max-instances','--cpu','--image']:
        assert prohibited not in api and prohibited not in ui


def test_iap_preservation_guard_ignores_only_frontend_auth_settings_not_backend_domains_or_rca():
    before = service(); after = deepcopy(before)
    env = after['spec']['template']['spec']['containers'][0]['env']
    env += [{'name':'FEEDBACK_GOOGLE_IAP_AUDIENCE','value':deploy.AUDIENCE},
        {'name':'FEEDBACK_FRONTEND_ORIGIN','value':'https://frontend.run.app'},
        {'name':'FEEDBACK_GOOGLE_IAM_DOMAINS','value':'loreal.com'}]
    after['spec']['template']['metadata']['annotations']['run.googleapis.com/iap-enabled'] = 'true'
    assert deploy.browser_preserved_configuration(before, deploy.UI) == deploy.browser_preserved_configuration(after, deploy.UI)
    assert deploy.browser_preserved_configuration(before, deploy.API) != deploy.browser_preserved_configuration(after, deploy.API)
    changed = deepcopy(after)
    changed['spec']['template']['spec']['containers'][0]['env'][0]['value'] = 'false'
    assert deploy.browser_preserved_configuration(before, deploy.UI) != deploy.browser_preserved_configuration(changed, deploy.UI)


def test_fresh_image_revalidation_requires_capability_role_and_security_checks_and_immutable_digests(tmp_path):
    names = ['authenticatedFrontend','frontendIapModeSupported','verifiedGoogleIdentityAndBigQueryReviewer',
        'authorizedDataRead','authorizedAccessDirectoryRead','backendIapCredentialPathSupported',
        'hostedDemoPickerDisabled','anonymousApiBlocked','backendRegressionTests','frontendRegressionTests','frontendTypecheck']
    images = {name: f'{deploy.REGION}-docker.pkg.dev/{deploy.PROJECT}/cloud-run-source-deploy/{name}@sha256:' + 'a' * 64 for name in (deploy.API, deploy.UI)}
    review = {'verificationMode':'existing_immutable_images_revalidated','images':images,'checks':dict.fromkeys(names, True)}
    path = tmp_path / 'image-review.json'; path.write_text(json.dumps(review))
    assert deploy.reviewed_image_pins(tmp_path, path) == images
    for changes in [{'checks': {}}, {'checks': {**review['checks'], 'verifiedGoogleIdentityAndBigQueryReviewer': False}},
        {'images': {**images, deploy.UI: 'unreviewed:latest'}}, {'verificationMode':'unchecked_current_images'}]:
        path.write_text(json.dumps({**review, **changes}))
        with pytest.raises(RuntimeError): deploy.reviewed_image_pins(tmp_path, path)


def test_frontend_policy_adds_only_google_iap_edge_invocation_and_preserves_existing_members_and_conditions():
    old = {'bindings': [{'role':'roles/run.invoker','members':['serviceAccount:runtime@example.test']},
        {'role':'roles/run.viewer','members':['user:existing@example.test'],'condition':{'title':'existing','expression':'true'}}]}
    expected = deploy.expected_frontend_policy(old)
    assert old['bindings'][0]['members'] == ['serviceAccount:runtime@example.test']
    assert expected['bindings'][0]['members'] == ['serviceAccount:runtime@example.test', 'serviceAccount:' + deploy.IAP_AGENT]
    assert expected['bindings'][1] == old['bindings'][1]
    assert deploy.expected_frontend_policy(expected) == expected
    reordered = deepcopy(expected); reordered['bindings'].reverse(); reordered['bindings'][1]['members'].reverse()
    assert deploy.canonical_bindings(reordered) == deploy.canonical_bindings(expected)


def test_iap_initialization_creates_only_google_managed_identity_not_runtime_account_or_keys():
    calls = []
    operation = {'done': True, 'response': {'email': deploy.IAP_AGENT}}
    def opener(request, **kwargs):
        calls.append((request, kwargs))
        return BytesIO(json.dumps(operation).encode())
    assert deploy.create_iap_service_identity('test-user-token', opener=opener) == operation
    request, kwargs = calls[0]
    assert request.full_url == f'https://serviceusage.googleapis.com/v1beta1/projects/{deploy.PROJECT_NUMBER}/services/iap.googleapis.com:generateServiceIdentity'
    assert request.method == 'POST' and request.data == b'{}'
    assert request.get_header('Authorization') == 'Bearer test-user-token'
    assert kwargs['timeout'] == 90
    assert len(calls) == 1 and 'keys' not in request.full_url


def test_iap_initialization_rejects_an_incomplete_or_different_identity():
    for operation in [{'done': False}, {'done': True, 'response': {'email': 'unrelated@example.test'}}]:
        with pytest.raises(RuntimeError):
            deploy.create_iap_service_identity('test-token', opener=lambda *_args, **_kwargs: BytesIO(json.dumps(operation).encode()))
