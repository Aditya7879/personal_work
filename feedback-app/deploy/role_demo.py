"""Enable in-app role demo on the existing services, preserving everything else.

No grant assignment, IAM/IAP policy edit, worker toggle, provider call or pilot
retry. Only reviewed images and the exact feature/origin flags may change.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from google.cloud import bigquery
from google.oauth2.credentials import Credentials

from app_update import runtime_signature
from browser_iap import canonical_bindings
from iam_authz import API, UI, PROJECT, REGION, ROOT, no_public_access, service_images


def feature_flags(service: str, origin: str) -> dict[str, str]:
    if service not in {API, UI}:
        raise ValueError('Only the existing feedback API/UI are in scope')
    url = urlsplit(origin)
    if url.scheme != 'https' or not url.hostname or not url.hostname.endswith('.run.app') or origin != f'https://{url.hostname}':
        raise ValueError('Use the exact existing hosted UI origin')
    result = {'FEEDBACK_ROLE_DEMO_ENABLED': 'true'}
    if service == API:
        result['FEEDBACK_DEMO_FRONTEND_ORIGIN'] = origin
    return result


def expected_service(record: dict, service: str, origin: str) -> dict:
    result = deepcopy(record)
    containers = result['spec']['template']['spec']['containers']
    if len(containers) != 1:
        raise ValueError('Review a multi-container deployment explicitly')
    env = containers[0].setdefault('env', [])
    for name, value in feature_flags(service, origin).items():
        old = [item for item in env if item['name'] == name]
        if old and old != [{'name': name, 'value': value}]:
            raise ValueError('A reviewed feature flag conflicts with an existing value or secret binding')
        if not old:
            env.append({'name': name, 'value': value})
    return result


def update_arguments(service: str, image: str, origin: str) -> list[str]:
    flags = ','.join(key + '=' + value for key, value in feature_flags(service, origin).items())
    return ['run', 'services', 'update', service, '--region=' + REGION, '--image=' + image, '--update-env-vars=' + flags]


def source_files():
    for folder, files, directory in [
        ('backend', ('Dockerfile', '.dockerignore', 'requirements.txt'), 'app'),
        ('agent-quality-console', ('Dockerfile', '.dockerignore', 'package.json', 'package-lock.json', 'server.mjs', 'index.html', 'vite.config.ts', 'tsconfig.json'), 'src'),
    ]:
        for name in files:
            yield ROOT / folder / name
        for path in sorted((ROOT / folder / directory).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc' and not path.name.startswith('.env'):
                yield path


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in source_files():
        digest.update(str(path.relative_to(ROOT)).encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    artifacts = args.artifacts.resolve(); os.chmod(artifacts, 0o700)
    lock = os.open(artifacts / 'role-demo-deploy.lock', os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def save(name, value):
        path = artifacts / name; path.write_text(json.dumps(value, indent=2, default=str)); path.chmod(0o600)

    before = json.loads((artifacts / 'cloud-before.json').read_text())
    origin = before[UI]['service']['status']['url']
    fingerprint = source_fingerprint()
    validation = json.loads((artifacts / 'test-validation.json').read_text())
    browser = json.loads((artifacts / 'local-role-demo-browser-result.json').read_text())
    guard = json.loads((artifacts / 'local-role-demo-guard-result.json').read_text())
    access = json.loads((artifacts / 'runtime-demo-access-result.json').read_text())
    retired = json.loads((artifacts / 'demo-preparation-result.json').read_text())
    layout = json.loads((artifacts / 'demo-control-layout-result.json').read_text())
    if not (validation.get('passed') and validation.get('sourceFingerprint') == fingerprint
            and validation.get('backendTests', 0) >= 533 and validation.get('frontendTests', 0) >= 100
            and validation.get('typecheck') and validation.get('build') and browser.get('passed') and browser.get('sourceFingerprint') == fingerprint
            and browser.get('fullPromotionPostCompleted') and browser.get('promotedTargetBecomesMainEnvironment')
            and browser.get('originalSourceAndCaptureRemainUnchanged') and browser.get('staleTabCannotSendLiveMutation')
            and guard.get('shutdownCompleted') and guard.get('sampleDataRestoredToThreeFictionalCases')
            and all(guard.get(name) == 0 for name in ('forbiddenProviderAttempts', 'forbiddenLiveStorageAttempts', 'liveFixtureMutations'))
            and access.get('checks', {}).get('readDemoFeedback') and access.get('checks', {}).get('demoUpdatePermissionDryRun')
            and retired.get('knownPasswordAccountsDisabled') == 3 and retired.get('unrevokedKnownPasswordSessions') == 0
            and layout.get('allFirstClicksAndBoundsPass') is True):
        raise RuntimeError('Fresh role/context/browser/runtime-access and prototype-retirement proofs are required before rollout')
    account = None

    def cloud(parts, label, *, sensitive=False):
        value = subprocess.run(['gcloud', *parts, '--project=' + PROJECT, *(['--account=' + account] if account else []), '--quiet'], capture_output=True, text=True, timeout=1800)
        path = artifacts / (label + '.log')
        path.write_text('Credential output intentionally not recorded.\n' if sensitive else value.stdout + '\n' + value.stderr); path.chmod(0o600)
        if value.returncode:
            raise RuntimeError('Role-demo cloud operation failed: ' + label + '; inspect its private log, no mutation was replayed')
        return value.stdout.strip()

    account = cloud(['config', 'get-value', 'account'], 'deployer').lower()
    if account != 'dhruv.chawla@loreal.com':
        raise RuntimeError('Use the same explicitly requested company operator; do not switch identities')

    def inspect(name):
        return {'service': json.loads(cloud(['run', 'services', 'describe', name, '--region=' + REGION, '--format=json'], 'inspect-' + name)),
            'iam': json.loads(cloud(['run', 'services', 'get-iam-policy', name, '--region=' + REGION, '--format=json'], 'iam-' + name))}

    def unchanged(name):
        current = inspect(name)
        if (runtime_signature(current['service']) != runtime_signature(before[name]['service'])
                or service_images(current['service']) != service_images(before[name]['service'])
                or canonical_bindings(current['iam']) != canonical_bindings(before[name]['iam'])):
            raise RuntimeError('The reviewed existing service changed; do not overwrite another deployment or setting')
        return current

    for name in (API, UI):
        current = unchanged(name)
        if not no_public_access(current['iam']):
            raise RuntimeError('Unexpected public invocation policy')
        if current['service'].get('metadata', {}).get('annotations', {}).get('run.googleapis.com/invoker-iam-disabled') == 'true':
            raise RuntimeError('Invoker IAM checks must remain enabled')
        traffic = current['service']['spec'].get('traffic', [])
        if len(traffic) != 1 or traffic[0].get('latestRevision') is not True or traffic[0].get('percent') != 100:
            raise RuntimeError('Review the traffic split before deploying; no traffic override is allowed')
        expected_service(current['service'], name, origin)
    if before[UI]['service'].get('metadata', {}).get('annotations', {}).get('run.googleapis.com/iap-enabled') != 'true':
        raise RuntimeError('The existing UI must remain IAP protected')
    api_env = {item['name']: item for item in before[API]['service']['spec']['template']['spec']['containers'][0].get('env', [])}
    if api_env.get('FEEDBACK_WORKER_ENABLED', {}).get('value') != 'false' or api_env.get('FEEDBACK_AUTH_MODE', {}).get('value') != 'google_iam':
        raise RuntimeError('The live worker/auth mode must remain unchanged')
    runtime = before[API]['service']['spec']['template']['spec']['serviceAccountName']
    if access.get('runtimeAccount') != runtime:
        raise RuntimeError('Sample access was not verified as the unchanged existing API runtime')
    policy_args = ['iap', 'web', 'get-iam-policy', '--region=' + REGION, '--resource-type=cloud-run', '--service=' + UI, '--format=json']
    iap_before = json.loads(cloud(policy_args, 'iap-before'))
    reviewed_iap = json.loads((artifacts / 'iap-before.json').read_text())
    if canonical_bindings(iap_before) != canonical_bindings(reviewed_iap):
        raise RuntimeError('The reviewed IAP policy changed')

    def refresh(_request, scopes=None):
        return cloud(['auth', 'print-access-token'], 'bq-credential', sensitive=True), datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)

    client = bigquery.Client(project=PROJECT, credentials=Credentials(cloud(['auth', 'print-access-token'], 'bq-credential', sensitive=True), refresh_handler=refresh))
    baseline_data = json.loads((artifacts / 'live-data-before.json').read_text())

    def fingerprints():
        names = sorted(table.table_id for table in client.list_tables(PROJECT + '.agent_quality') if not table.table_id.startswith('_'))
        if names != sorted(baseline_data):
            raise RuntimeError('The reviewed live table set changed')
        sql = ' UNION ALL '.join(f"SELECT '{name}' AS name,COUNT(*) AS n,BIT_XOR(FARM_FINGERPRINT(TO_JSON_STRING(t))) AS checksum FROM `{PROJECT}.agent_quality.{name}` t" for name in names)
        return {row['name']: {'count': row['n'], 'checksum': row['checksum']} for row in client.query(sql, location=REGION).result()}

    if fingerprints() != baseline_data:
        raise RuntimeError('Live data changed since review; obtain an explicit fresh baseline instead of overwriting it')
    manifest = Path('/home/dhruv/loreal-neo/llm-graph-builder/output/rca_markdown_gcs_visual_analysis/manifest.json').read_bytes()
    if 'neo-rca-visual-' + hashlib.sha256(manifest).hexdigest()[:20] != api_env.get('FEEDBACK_NEO4J_CORPUS_VERSION', {}).get('value'):
        raise RuntimeError('The metadata manifest differs from the existing corpus pin')
    if not args.apply:
        print(json.dumps({'ready': True, 'sameExistingApp': True, 'reviewedFlags': {name: feature_flags(name, origin) for name in (API, UI)},
            'runtimeIamIapSecretsWorkerAndScalingPreserved': True, 'grantsChanged': False, 'providerCalls': 0, 'applied': False}, indent=2)); return
    if (artifacts / 'role-demo-deployment-result.json').exists():
        raise RuntimeError('A deployment receipt already exists; inspect it rather than replaying the rollout')
    contexts = {}
    for name in (API, UI):
        folder = artifacts / (name + '-source'); folder.mkdir(exist_ok=True)
        source = ROOT / ('backend' if name == API else 'agent-quality-console')
        files = ('Dockerfile', '.dockerignore', 'requirements.txt') if name == API else ('Dockerfile', '.dockerignore', 'package.json', 'package-lock.json', 'server.mjs', 'index.html', 'vite.config.ts', 'tsconfig.json')
        for item in files:
            shutil.copy2(source / item, folder / item)
        directory = 'app' if name == API else 'src'
        shutil.copytree(source / directory, folder / directory, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.env', '.env.*'))
        if name == API:
            (folder / 'evidence-manifest.json').write_bytes(manifest)
        (folder / '.gcloudignore').write_text('.git\n.env\n.env.*\n.venv\nnode_modules\n__pycache__\n*.pyc\n')
        if any(path.name == '.env' or path.name.startswith('.env.') or 'credentials' in path.name for path in folder.rglob('*')):
            raise RuntimeError('A private environment/credential file entered a build context')
        contexts[name] = folder
    tag = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-role-demo-' + secrets.token_hex(3)

    def build(name):
        image = f'{REGION}-docker.pkg.dev/{PROJECT}/cloud-run-source-deploy/{name}:{tag}'
        sa = before[name]['service']['spec']['template']['spec']['serviceAccountName']
        config = {'steps': [{'name': 'gcr.io/cloud-builders/docker', 'args': ['build', *(['--build-arg', 'VITE_AUTH_MODE=google_iam'] if name == UI else []), '-t', image, '.']}],
            'images': [image], 'serviceAccount': f'projects/{PROJECT}/serviceAccounts/{sa}', 'options': {'logging': 'CLOUD_LOGGING_ONLY'}, 'timeout': '1200s'}
        save(name + '-build.json', config)
        value = json.loads(cloud(['builds', 'submit', str(contexts[name]), '--config=' + str(artifacts / (name + '-build.json')), '--region=' + REGION, '--suppress-logs', '--format=json'], 'build-' + name))
        save(name + '-build-result.json', value)
        return name, image.rsplit(':', 1)[0] + '@' + value['results']['images'][0]['digest']

    print(json.dumps({'phase': 'building_existing_app', 'authMode': 'google_iam', 'workerToggled': False, 'providerCalls': 0}), flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        images = dict(pool.map(build, (API, UI)))
    save('role-demo-images.json', images)
    if source_fingerprint() != fingerprint:
        raise RuntimeError('Runtime source changed while building; review it before deployment')
    for name in (API, UI):
        unchanged(name)
        print(json.dumps({'phase': 'deploying_existing_service', 'service': name}), flush=True)
        cloud(update_arguments(name, images[name], origin), 'deploy-' + name)
    after = {name: inspect(name) for name in (API, UI)}
    save('cloud-after.json', after)
    checks = {
        'onlyReviewedFeatureFlagsAndImagesChanged': all(runtime_signature(after[name]['service']) == runtime_signature(expected_service(before[name]['service'], name, origin)) for name in (API, UI)),
        'runtimeAndSecretBindingsIamIapWorkerAndScalingPreserved': all(canonical_bindings(after[name]['iam']) == canonical_bindings(before[name]['iam']) and no_public_access(after[name]['iam']) for name in (API, UI)),
        'iapPolicyUnchanged': canonical_bindings(json.loads(cloud(policy_args, 'iap-after'))) == canonical_bindings(iap_before),
        'allLiveTableFingerprintsUnchanged': fingerprints() == baseline_data,
        'deployedExactlyReviewedImages': all(service_images(after[name]['service']) == [images[name]] for name in (API, UI)),
    }
    identity = cloud(['auth', 'print-identity-token'], 'verification-identity', sensitive=True)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs): return None

    def get(url, authenticated=True):
        headers = {'Accept': 'application/json', 'Cache-Control': 'no-cache'}
        if authenticated:
            headers.update(Authorization='Bearer ' + identity, **{'X-Feedback-User-Authorization': 'Bearer ' + identity})
        try:
            with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url, headers=headers), timeout=120) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    backend = after[API]['service']['status']['url']
    code, body, _ = get(backend + '/api/auth/me'); user = json.loads(body) if code == 200 else {}
    has_capability=user.get('accessRole')=='demo_admin' and user.get('canSwitchDemoViews') is True
    checks['realPrimaryActorUsesReviewerWorkflowPermissions'] = code == 200 and user.get('email', '').lower() == account and user.get('role') == 'reviewer' and not user.get('demoMode')
    checks['demoCapabilityMatchesTheSeparatelyAuditedGrant'] = has_capability == (json.loads((artifacts/'initial-demo-admin-grant-result.json').read_text()).get('newRole')=='demo_admin') if (artifacts/'initial-demo-admin-grant-result.json').exists() else not has_capability
    for label, path, status in [('liveFeedbackReadable', '/api/feedback?page_size=1', 200), ('passwordLoginAbsent', '/api/demo-admin/login', 404), ('hostedMockPickerDisabled', '/api/auth/mock-users', 404)]:
        code, _, _ = get(backend + path); checks[label] = code == status
    code,body,_=get(backend+'/api/demo-admin/session')
    controller=json.loads(body)if code==200 else{}
    checks['demoRoleControllerFollowsCurrentGrant']=code==(200 if has_capability else 403) and (not has_capability or controller.get('realUser',{}).get('email','').lower()==account)
    code, body, _ = get(backend + '/openapi.json'); schema = json.loads(body) if code == 200 else {}
    checks['storedRoleAcceptedByDeployedCode'] = 'demo_admin' in schema.get('components', {}).get('schemas', {}).get('AccessGrantInput', {}).get('properties', {}).get('role', {}).get('enum', []) or any(
        'demo_admin' in value.get('properties', {}).get('role', {}).get('enum', []) for key, value in schema.get('components', {}).get('schemas', {}).items() if key in {'AccessGrantCreate', 'AccessGrantUpdate'})
    code, _, headers = get(origin + '/', False)
    checks['existingFrontendStillRequiresIap'] = code in {302, 303, 307} and urlsplit(headers.get('Location', '')).hostname in {'accounts.google.com', 'iap.googleapis.com'} or bool(code == 401 and headers.get('X-Goog-IAP-Generated-Response'))
    code, _, _ = get(backend + '/api/demo-admin/session', False); checks['anonymousApiStillBlocked'] = code in {401, 403}
    result = {'passed': all(checks.values()), 'checks': checks, 'services': {name: {'url': after[name]['service']['status']['url'],
        'revision': after[name]['service']['status']['latestReadyRevisionName'], 'image': images[name]} for name in (API, UI)},
        'sourceFingerprint': fingerprint, 'sameExistingApp': True, 'initialRoleAssignmentAlreadyAudited': (artifacts/'initial-demo-admin-grant-result.json').exists(),
        'applicationGrantsChanged': False, 'providerCalls': 0, 'pilotRetries': 0}
    save('role-demo-deployment-result.json', result)
    print(json.dumps(result, indent=2), flush=True)
    if not result['passed']:
        raise RuntimeError('Deployment verification needs attention; do not assign the special role until it passes')


if __name__ == '__main__':
    main()
