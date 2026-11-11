"""Auth-only upgrade of the existing IAM-private services; preserve all RCA/runtime configuration.

No secret creation/rotation, worker toggles, scaling changes, agent calls, RCA
probes, workflow migration or IAM-policy changes are performed by this command.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'oa-apmena-techsandbox-ap-dv'
REGION = 'europe-west1'
API, UI = 'neo-feedback-api', 'neo-feedback-ui'
AUTH_ENV = {'FEEDBACK_AUTH_MODE', 'FEEDBACK_AUTHZ_TABLE', 'FEEDBACK_AUTHZ_CACHE_TTL_SECONDS', 'FEEDBACK_GOOGLE_IAM_USERS_JSON', 'FEEDBACK_GOOGLE_IAP_AUDIENCE'}


def preserved_configuration(record):
    template = record['spec']['template']
    spec = deepcopy(template['spec'])
    for container in spec['containers']:
        container.pop('image', None)
        container['env'] = sorted([value for value in container.get('env', []) if value['name'] not in AUTH_ENV], key=lambda value: value['name'])
    annotations = template.get('metadata', {}).get('annotations', {})
    retained = {key: value for key, value in annotations.items() if not key.startswith(('client.knative.dev/', 'run.googleapis.com/client-'))}
    return {'runtimeSpec': spec, 'runtimeAnnotations': retained,
        'ingress': record.get('metadata', {}).get('annotations', {}).get('run.googleapis.com/ingress'),
        'iamDisabled': record.get('metadata', {}).get('annotations', {}).get('run.googleapis.com/invoker-iam-disabled')}


def bindings(policy):
    return sorted(json.dumps(value, sort_keys=True) for value in policy.get('bindings', []))


def auth_configuration(record):
    return {value['name']: value for value in record['spec']['template']['spec']['containers'][0].get('env', []) if value['name'] in AUTH_ENV}


def service_images(record):
    return [container['image'] for container in record['spec']['template']['spec']['containers']]


def no_public_access(policy):
    return not any(member in {'allUsers', 'allAuthenticatedUsers'} for binding in policy.get('bindings', []) for member in binding.get('members', []))


def update_arguments(service, image, table):
    args = ['run', 'services', 'update', service, '--image=' + image, '--region=' + REGION]
    if service == API:
        args += ['--update-env-vars=FEEDBACK_AUTH_MODE=google_iam,FEEDBACK_AUTHZ_TABLE=' + table + ',FEEDBACK_AUTHZ_CACHE_TTL_SECONDS=30',
            '--remove-env-vars=FEEDBACK_GOOGLE_IAM_USERS_JSON']
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True, help='Private directory containing the reviewed cloud-before.json snapshot')
    parser.add_argument('--access-management', action='store_true', help='Install only access-audit/control storage and deploy the People & access screen, without seeding or changing grants')
    args = parser.parse_args()
    artifacts = args.artifacts.resolve(); os.chmod(artifacts, 0o700)
    lock = os.open(artifacts / 'deployment.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('This reviewed deployment already has an active runner; no second build/deployment was started') from None
    completed = artifacts / 'deployment-result.json'
    if completed.exists():
        previous = json.loads(completed.read_text())
        if all(previous.get('checks', {}).values()) and previous.get('checks'):
            print(json.dumps(previous, indent=2), flush=True)
            return
    before = json.loads((artifacts / 'cloud-before.json').read_text())
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.access_repository import AccessGrantRepository, access_table_ref
    from scripts.init_access_grants import approved_grants, initialize, initialize_management
    from google.cloud import bigquery

    def cloud(arguments, *, label, sensitive=False):
        result = subprocess.run(['gcloud', *arguments, '--project=' + PROJECT, '--quiet'], capture_output=True, text=True)
        path = artifacts / (label + '.log')
        path.write_text('Credential output intentionally not recorded.\n' if sensitive else result.stdout + '\n' + result.stderr)
        os.chmod(path, 0o600)
        if result.returncode:
            raise RuntimeError('Cloud operation failed: ' + label + '; inspect its private log')
        return result.stdout.strip()

    def inspect(service):
        return {'service': json.loads(cloud(['run','services','describe',service,'--region=' + REGION,'--format=json'], label='inspect-' + service)),
            'iam': json.loads(cloud(['run','services','get-iam-policy',service,'--region=' + REGION,'--format=json'], label='iam-' + service))}

    for name in (API, UI):
        current = inspect(name)
        if not no_public_access(current['iam']) or current['service']['metadata'].get('labels', {}).get('app') != 'neo-feedback':
            raise RuntimeError('The target is not the expected IAM-private application')
        if (preserved_configuration(current['service']) != preserved_configuration(before[name]['service'])
                or auth_configuration(current['service']) != auth_configuration(before[name]['service'])
                or service_images(current['service']) != service_images(before[name]['service'])
                or bindings(current['iam']) != bindings(before[name]['iam'])):
            raise RuntimeError('Cloud configuration changed since the reviewed snapshot; do not overwrite it')

    account = cloud(['config','get-value','account'], label='deployer-identity').lower()
    if not account.endswith('@loreal.com'):
        raise RuntimeError('Use the intended existing company deployment identity')
    client = bigquery.Client(project=PROJECT)
    if not access_table_ref().startswith(PROJECT + '.agent_quality.'):
        raise RuntimeError('Authorization storage must stay in the reviewed application dataset')
    table = access_table_ref()
    if not args.access_management:
        legacy = json.loads((artifacts / 'legacy-approved-grants.json').read_text())
        grants = approved_grants(legacy)
        if not any(row['email'] == account and row['role'] == 'reviewer' and row['active'] for row in grants):
            raise RuntimeError('The deployer was not an already-approved reviewer; no implicit grant will be added')
        table = initialize(client, grants)
    grant = AccessGrantRepository(client).grant(account)
    if not grant or grant['role'] != 'reviewer':
        raise RuntimeError('The BigQuery grant is inactive or changed; it was not overwritten')
    if args.access_management:
        initialize_management(client)

    api_env = {value['name']: value for value in before[API]['service']['spec']['template']['spec']['containers'][0].get('env', [])}
    manifest_path = Path('/home/dhruv/loreal-neo/llm-graph-builder/output/rca_markdown_gcs_visual_analysis/manifest.json')
    manifest_bytes = manifest_path.read_bytes()
    corpus = 'neo-rca-visual-' + hashlib.sha256(manifest_bytes).hexdigest()[:20]
    if corpus != api_env.get('FEEDBACK_NEO4J_CORPUS_VERSION', {}).get('value'):
        raise RuntimeError('The build manifest differs from the deployed RCA pin; RCA configuration will not be changed')

    contexts = {}
    for service in (API, UI):
        folder = artifacts / (service + '-source'); folder.mkdir(exist_ok=True)
        if service == API:
            source = ROOT / 'backend'; files = ('Dockerfile', '.dockerignore', 'requirements.txt'); directories = ('app',)
        else:
            source = ROOT / 'agent-quality-console'; files = ('Dockerfile', '.dockerignore', 'package.json', 'package-lock.json', 'server.mjs', 'index.html', 'vite.config.ts', 'tsconfig.json'); directories = ('src',)
        for name in files: shutil.copy2(source / name, folder / name)
        for name in directories: shutil.copytree(source / name, folder / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.env', '.env.*'))
        if service == API: (folder / 'evidence-manifest.json').write_bytes(manifest_bytes)
        (folder / '.gcloudignore').write_text('.git\n.env\n.env.*\n.venv\nnode_modules\n__pycache__\n*.pyc\n')
        if any(path.name == '.env' or path.name.startswith('.env.') for path in folder.rglob('*')):
            raise RuntimeError('A private environment file entered a build context')
        contexts[service] = folder

    tag = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-authz-' + secrets.token_hex(3)
    registry = f'{REGION}-docker.pkg.dev/{PROJECT}/cloud-run-source-deploy'

    def build(service):
        image = f'{registry}/{service}:{tag}'
        sa = before[service]['service']['spec']['template']['spec']['serviceAccountName']
        docker_args = ['build'] + (['--build-arg','VITE_AUTH_MODE=google_iam'] if service == UI else []) + ['-t',image,'.']
        config = {'steps': [{'name':'gcr.io/cloud-builders/docker','args':docker_args}], 'images':[image],
            'serviceAccount': f'projects/{PROJECT}/serviceAccounts/{sa}', 'options':{'logging':'CLOUD_LOGGING_ONLY'}, 'timeout':'1200s'}
        path = artifacts / (service + '-build.json'); path.write_text(json.dumps(config, indent=2))
        result = subprocess.run(['gcloud','builds','submit',str(contexts[service]),'--config=' + str(path),'--project=' + PROJECT,
            '--region=' + REGION,'--suppress-logs','--format=json','--quiet'], capture_output=True, text=True)
        (artifacts / (service + '-build.log')).write_text(result.stdout + '\n' + result.stderr)
        if result.returncode: raise RuntimeError('Image build failed for ' + service)
        record = json.loads(result.stdout); (artifacts / (service + '-build-result.json')).write_text(json.dumps(record, indent=2))
        return service, image.rsplit(':',1)[0] + '@' + record['results']['images'][0]['digest']

    print(json.dumps({'phase':'building','authorizationTable':table,'accessManagement':args.access_management,
        'grantSeedingEnabled':not args.access_management,'rcaSettingsPreserved':True}), flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        images = dict(pool.map(build, (API, UI)))
    (artifacts / 'images.json').write_text(json.dumps(images, indent=2))
    for service in (API, UI):
        current = inspect(service)
        if (preserved_configuration(current['service']) != preserved_configuration(before[service]['service'])
                or auth_configuration(current['service']) != auth_configuration(before[service]['service'])
                or service_images(current['service']) != service_images(before[service]['service'])
                or bindings(current['iam']) != bindings(before[service]['iam'])):
            raise RuntimeError('The service changed during the build; deployment stopped without overwriting runtime settings')
        print(json.dumps({'phase':'deploying','service':service}), flush=True)
        cloud(update_arguments(service, images[service], table), label='deploy-' + service)

    after = {service: inspect(service) for service in (API, UI)}
    (artifacts / 'cloud-after.json').write_text(json.dumps(after, indent=2)); os.chmod(artifacts / 'cloud-after.json', 0o600)
    for service in (API, UI):
        if preserved_configuration(after[service]['service']) != preserved_configuration(before[service]['service']):
            raise RuntimeError('A non-auth runtime setting changed unexpectedly; inspect the snapshots, do not disable RCA')
        if bindings(after[service]['iam']) != bindings(before[service]['iam']) or not no_public_access(after[service]['iam']):
            raise RuntimeError('IAM policy changed unexpectedly')

    token = cloud(['auth','print-identity-token','--account=' + account], label='smoke-identity-token', sensitive=True)
    claims = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '=' * (-len(token.split('.')[1]) % 4)))
    if claims.get('email','').lower() != account or claims.get('email_verified') is not True:
        raise RuntimeError('The smoke identity does not match the approved account')

    def get(url, authenticated=True):
        headers = {'Cache-Control':'no-cache'}
        if authenticated: headers.update(Authorization='Bearer ' + token, **{'X-Feedback-User-Authorization':'Bearer ' + token})
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response: return response.status, response.read()
        except urllib.error.HTTPError as error: return error.code, error.read()

    frontend = after[UI]['service']['status']['url']; backend = after[API]['service']['status']['url']
    checks = {}
    for name, url in [('ui',frontend + '/'), ('api',backend + '/docs')]:
        code, _ = get(url, False); checks[name + 'AnonymousBlocked'] = code in {401,403}
    code, _ = get(frontend + '/'); checks['authenticatedUi'] = code == 200
    code, body = get(frontend + '/api/auth/me'); user = json.loads(body) if code == 200 else {}
    checks['verifiedIamIdentityAndBigQueryRole'] = code == 200 and user.get('email','').lower() == account and user.get('role') == grant['role'] and not user.get('demoMode')
    code, _ = get(frontend + '/api/feedback?page_size=1'); checks['authorizedDataRead'] = code == 200
    code, _ = get(frontend + '/api/auth/mock-users'); checks['hostedMockPickerDisabled'] = code == 404
    if args.access_management:
        code, body = get(frontend + '/api/access-grants?page_size=1')
        directory = json.loads(body) if code == 200 else {}
        checks['authorizedAccessDirectoryRead'] = code == 200 and isinstance(directory.get('items'), list)
    summary = {'project':PROJECT, 'region':REGION, 'authorizationTable':table, 'authMode':'google_iam',
        'services':{service:{'url':after[service]['service']['status']['url'],'revision':after[service]['service']['status']['latestReadyRevisionName'],'image':images[service]} for service in (API,UI)},
        'checks':checks,'iamPoliciesUnchanged':True,'nonAuthRuntimeConfigurationUnchanged':True,'secretBindingsUnchanged':True,
        'accessManagement':args.access_management,'applicationGrantsChanged':False if args.access_management else None,
        'rcaTested':False,'agentInvoked':False,'pilotCasesRetried':False,'workerToggled':False}
    (artifacts / 'deployment-result.json').write_text(json.dumps(summary, indent=2)); print(json.dumps(summary, indent=2), flush=True)
    if not all(checks.values()): raise RuntimeError('An auth/data smoke check failed; no RCA setting was changed as a workaround')


if __name__ == '__main__':
    main()
