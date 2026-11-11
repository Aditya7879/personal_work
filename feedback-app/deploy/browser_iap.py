"""Enable direct browser sign-in using Google's managed IAP OAuth client.

Run only after deploying the IAP-capable application images. A failed IAP policy
preflight stops before any mutation. This never builds images, creates OAuth
clients, changes application grants, exposes the API, or invokes RCA/agents.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from iam_authz import API, UI, PROJECT, REGION, ROOT, auth_configuration, bindings, no_public_access, preserved_configuration, service_images


PROJECT_NUMBER = '411502743425'
IAP_AGENT = f'service-{PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com'
AUDIENCE = f'/projects/{PROJECT_NUMBER}/locations/{REGION}/services/{UI}'


def browser_update_arguments(service: str, origin: str, domains: str) -> list[str]:
    args = ['run', 'services', 'update', service, '--region=' + REGION,
        '--update-env-vars=FEEDBACK_GOOGLE_IAP_AUDIENCE=' + AUDIENCE]
    if service == UI:
        args[-1] += ',FEEDBACK_FRONTEND_ORIGIN=' + origin + ',FEEDBACK_GOOGLE_IAM_DOMAINS=' + domains
        args.append('--iap')
    return args


def browser_preserved_configuration(record, service):
    result = preserved_configuration(record)
    if service == UI:
        for container in result['runtimeSpec']['containers']:
            container['env'] = [item for item in container['env'] if item['name'] not in {'FEEDBACK_FRONTEND_ORIGIN','FEEDBACK_GOOGLE_IAM_DOMAINS'}]
        result['runtimeAnnotations'].pop('run.googleapis.com/iap-enabled', None)
    return result


def reviewed_image_pins(artifacts, reviewed_images=None):
    if reviewed_images:
        review = json.loads(Path(reviewed_images).read_text())
        required = {'authenticatedFrontend','frontendIapModeSupported','verifiedGoogleIdentityAndBigQueryReviewer',
            'authorizedDataRead','authorizedAccessDirectoryRead','backendIapCredentialPathSupported',
            'hostedDemoPickerDisabled','anonymousApiBlocked','backendRegressionTests','frontendRegressionTests','frontendTypecheck'}
        if (review.get('verificationMode') != 'existing_immutable_images_revalidated'
                or not all(review.get('checks', {}).get(name) is True for name in required)):
            raise RuntimeError('Existing images require successful live identity, role, capability and regression checks')
        images = review.get('images', {})
    else:
        staged = json.loads((artifacts / 'deployment-result.json').read_text())
        if not staged.get('accessManagement') or not staged.get('checks') or not all(value is True for value in staged['checks'].values()):
            raise RuntimeError('First deploy and verify the IAP-capable People & access images')
        images = {name: staged['services'][name]['image'] for name in (API, UI)}
    if set(images) != {API, UI}:
        raise RuntimeError('Review exactly the existing frontend and backend images')
    for name, image in images.items():
        prefix = f'{REGION}-docker.pkg.dev/{PROJECT}/cloud-run-source-deploy/{name}@sha256:'
        if not isinstance(image, str) or not re.fullmatch(re.escape(prefix) + r'[0-9a-f]{64}', image):
            raise RuntimeError('An immutable image digest in the existing application repository is required')
    return images


def canonical_bindings(policy):
    return sorted(json.dumps({**binding, 'members': sorted(set(binding.get('members', [])))}, sort_keys=True)
        for binding in policy.get('bindings', []))


def expected_frontend_policy(before):
    expected = deepcopy(before)
    member = 'serviceAccount:' + IAP_AGENT
    entries = expected.setdefault('bindings', [])
    binding = next((item for item in entries if item['role'] == 'roles/run.invoker' and not item.get('condition')), None)
    if binding is None:
        entries.append({'role':'roles/run.invoker','members':[member]})
    elif member not in binding.get('members', []):
        binding.setdefault('members', []).append(member)
    return expected


def create_iap_service_identity(access_token, *, opener=urllib.request.urlopen):
    # Use the documented API rather than implicitly installing gcloud beta
    # components. The project/service identity is idempotent; no SA key is created.
    url = f'https://serviceusage.googleapis.com/v1beta1/projects/{PROJECT_NUMBER}/services/iap.googleapis.com:generateServiceIdentity'
    request = urllib.request.Request(url, data=b'{}', method='POST',
        headers={'Authorization':'Bearer ' + access_token,'Content-Type':'application/json'})
    try:
        with opener(request, timeout=90) as response:
            operation = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'IAP service identity initialization failed with HTTP {error.code}; no app configuration was changed') from None
    identity = operation.get('response', operation)
    if operation.get('done') is False or identity.get('email') != IAP_AGENT:
        raise RuntimeError('Google did not return the completed, expected IAP service identity; no app configuration was changed')
    return operation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Apply the reviewed frontend-only IAP configuration after permission preflight')
    parser.add_argument('--reviewed-images', type=Path, help='Explicit fresh revalidation of the existing immutable images when old temporary build records are unavailable')
    args = parser.parse_args()
    artifacts = args.artifacts.resolve(); artifacts.mkdir(exist_ok=True); os.chmod(artifacts, 0o700)
    lock = os.open(artifacts / 'browser-iap.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('This reviewed IAP migration already has an active runner') from None
    account = None

    def cloud(arguments, label, *, allow_failure=False, sensitive=False):
        selected = ['--account=' + account] if account else []
        result = subprocess.run(['gcloud', *arguments, '--project=' + PROJECT, *selected, '--quiet'], capture_output=True, text=True)
        path = artifacts / (label + '.log')
        path.write_text('Credential output intentionally not recorded.\n' if sensitive else result.stdout + '\n' + result.stderr)
        os.chmod(path, 0o600)
        if result.returncode and not allow_failure:
            raise RuntimeError('Cloud operation failed: ' + label + '; inspect its private log')
        return result

    def inspect(name):
        return {'service': json.loads(cloud(['run','services','describe',name,'--region=' + REGION,'--format=json'], 'iap-inspect-' + name).stdout),
            'iam': json.loads(cloud(['run','services','get-iam-policy',name,'--region=' + REGION,'--format=json'], 'iap-invocation-' + name).stdout)}

    account = cloud(['config','get-value','account'], 'iap-deployer').stdout.strip().lower()
    if not account.endswith('@loreal.com') or account.endswith('.gserviceaccount.com'):
        raise RuntimeError('Use the intended existing company Google-user deployment account')
    before = {name: inspect(name) for name in (API, UI)}
    snapshot = artifacts / 'cloud-before.json'
    if snapshot.exists():
        reviewed = json.loads(snapshot.read_text())
        for name in (API, UI):
            if (preserved_configuration(before[name]['service']) != preserved_configuration(reviewed[name]['service'])
                    or auth_configuration(before[name]['service']) != auth_configuration(reviewed[name]['service'])
                    or service_images(before[name]['service']) != service_images(reviewed[name]['service'])
                    or canonical_bindings(before[name]['iam']) != canonical_bindings(reviewed[name]['iam'])):
                raise RuntimeError('The application changed since the reviewed preflight; do not overwrite it')
    for row in before.values():
        if not no_public_access(row['iam']):
            raise RuntimeError('Unexpected public Cloud Run binding; do not broaden it further')
    api_env = {item['name']: item for item in before[API]['service']['spec']['template']['spec']['containers'][0].get('env', [])}
    if api_env.get('FEEDBACK_AUTH_MODE', {}).get('value') != 'google_iam':
        raise RuntimeError('The API must already use real Google identity and BigQuery authorization')
    domains = api_env.get('FEEDBACK_GOOGLE_IAM_DOMAINS', {}).get('value', 'loreal.com').strip().lower()
    if domains != 'loreal.com':
        raise RuntimeError('Review the exact company login domains before configuring IAP')
    origin = before[UI]['service']['status']['url']
    policy_args = ['iap','web','get-iam-policy','--region=' + REGION,'--resource-type=cloud-run','--service=' + UI,'--format=json']
    policy = cloud(policy_args, 'iap-policy-preflight', allow_failure=True)
    plan = {'status': 'ready_for_review' if policy.returncode == 0 else 'blocked_iap_policy_access',
        'frontend': origin, 'iapAudience': AUDIENCE, 'googleManagedOAuthClient': True,
        'customOAuthClientRequired': False, 'loginDomain': domains, 'applicationAuthorization': 'BigQuery explicit grants only',
        'apiRemainsIamPrivate': True, 'applicationGrantsChanged': False, 'rcaOrAgentChecks': 0,
        'requiredIapPermissions': ['iap.webServices.getIamPolicy', 'iap.webServices.setIamPolicy'], 'applied': False}
    (artifacts / 'browser-iap-plan.json').write_text(json.dumps(plan, indent=2))
    if not args.apply or policy.returncode:
        print(json.dumps(plan, indent=2))
        if args.apply and policy.returncode:
            raise SystemExit('IAP policy access is unavailable; no cloud configuration was changed')
        return

    images = reviewed_image_pins(artifacts, args.reviewed_images)
    for name in (API, UI):
        current_image = before[name]['service']['spec']['template']['spec']['containers'][0]['image']
        if current_image != images[name]:
            raise RuntimeError('The running image differs from the verified IAP-capable image; review it before enabling IAP')

    # Confirm the real deployer is already an active application reviewer. Do not
    # turn cloud IAM permission into an implicit application role.
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.access_repository import AccessGrantRepository
    if not (AccessGrantRepository().grant(account) or {}).get('role') == 'reviewer':
        raise RuntimeError('The deployer must have an existing active application reviewer grant')
    (artifacts / 'browser-iap-before.json').write_text(json.dumps(before, indent=2))

    # Google creates this managed IAP edge identity on first use. It is not the
    # application's runtime/build identity, and no key or application role is issued.
    token = cloud(['auth','print-access-token'], 'iap-bootstrap-credential', sensitive=True).stdout.strip()
    identity = create_iap_service_identity(token)
    identity_path = artifacts / 'iap-service-identity.json'
    identity_path.write_text(json.dumps(identity, indent=2)); os.chmod(identity_path, 0o600)

    # This is a login boundary only: company sign-in does not grant application
    # access. Reviewers continue to manage individual grants in BigQuery via UI.
    cloud(['iap','web','add-iam-policy-binding','--region=' + REGION,'--resource-type=cloud-run','--service=' + UI,
        '--member=domain:' + domains,'--role=roles/iap.httpsResourceAccessor'], 'iap-company-login')
    cloud(['run','services','add-iam-policy-binding',UI,'--region=' + REGION,
        '--member=serviceAccount:' + IAP_AGENT,'--role=roles/run.invoker'], 'iap-edge-invocation')
    for name in (API, UI):
        # Re-read before each update rather than replacing a stale service spec.
        current = inspect(name)
        if (preserved_configuration(current['service']) != preserved_configuration(before[name]['service'])
                or auth_configuration(current['service']) != auth_configuration(before[name]['service'])
                or service_images(current['service']) != service_images(before[name]['service'])):
            raise RuntimeError('Non-auth runtime configuration changed; migration stopped without overwriting it')
        cloud(browser_update_arguments(name, origin, domains), 'iap-enable-' + name)

    after = {name: inspect(name) for name in (API, UI)}
    (artifacts / 'browser-iap-after.json').write_text(json.dumps(after, indent=2))
    for name in (API, UI):
        if browser_preserved_configuration(after[name]['service'], name) != browser_preserved_configuration(before[name]['service'], name):
            raise RuntimeError('An unexpected non-auth runtime change occurred; inspect snapshots, do not change RCA as a workaround')
        if not no_public_access(after[name]['iam']):
            raise RuntimeError('Unexpected public invocation binding')
        if service_images(after[name]['service']) != service_images(before[name]['service']):
            raise RuntimeError('The running application image changed unexpectedly during IAP configuration')
    if bindings(after[API]['iam']) != bindings(before[API]['iam']):
        raise RuntimeError('The API invocation policy changed unexpectedly')
    if canonical_bindings(after[UI]['iam']) != canonical_bindings(expected_frontend_policy(before[UI]['iam'])):
        raise RuntimeError('The frontend invocation policy changed beyond the single IAP edge grant')
    after_policy = json.loads(cloud(policy_args, 'iap-policy-after').stdout)
    expected_policy = json.loads(policy.stdout)
    entries = expected_policy.setdefault('bindings', [])
    member = 'domain:' + domains
    entry = next((item for item in entries if item['role'] == 'roles/iap.httpsResourceAccessor' and not item.get('condition')), None)
    if entry is None:
        entries.append({'role':'roles/iap.httpsResourceAccessor','members':[member]})
    elif member not in entry.get('members', []):
        entry.setdefault('members', []).append(member)
    if canonical_bindings(after_policy) != canonical_bindings(expected_policy):
        raise RuntimeError('The IAP access policy changed beyond the reviewed company-login grant')

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs): return None

    def probe(url):
        request = urllib.request.Request(url, headers={'Accept':'text/html','Cache-Control':'no-cache'})
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=90) as response:
                return response.status, response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.headers

    code, headers = probe(origin + '/')
    location = urlsplit(headers.get('Location', '')).hostname
    login_challenge = (code in {302,303,307} and location in {'accounts.google.com','iap.googleapis.com'}) or (code == 401 and headers.get('X-Goog-IAP-Generated-Response'))
    api_code, _ = probe(after[API]['service']['status']['url'] + '/docs')
    result = {**plan, 'status': 'deployed' if login_challenge and api_code in {401,403} else 'verification_required',
        'applied': True, 'googleBrowserLoginChallenge': bool(login_challenge), 'anonymousApiBlocked': api_code in {401,403},
        'actualUserBrowserSessionVerified': False, 'nonAuthRuntimeConfigurationUnchanged': True,
        'secretBindingsUnchanged': True, 'runtimeAndBuildIdentitiesUnchanged': True,
        'onlyIapEdgeInvocationAdded': True, 'imagesUnchanged': True, 'newBuildPerformed': False,
        'workerToggled': False, 'pilotRetried': False}
    (artifacts / 'browser-iap-result.json').write_text(json.dumps(result, indent=2)); print(json.dumps(result, indent=2))
    if result['status'] != 'deployed':
        raise RuntimeError('Browser auth verification needs attention; no request was replayed and no RCA setting was changed')


if __name__ == '__main__':
    main()
