"""Image-only application update: preserve IAP/IAM, every runtime value and all data.

No secret/schema/grant migration, worker toggle, model/agent probe or case retry.
Uses small allowlisted build contexts and the existing runtime/build identity.
"""
from __future__ import annotations

import argparse
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
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from iam_authz import API, UI, PROJECT, REGION, ROOT, no_public_access, service_images
from browser_iap import canonical_bindings


def runtime_signature(record):
    template = record['spec']['template']
    spec = deepcopy(template['spec'])
    for container in spec['containers']:
        container.pop('image', None)
        container['env'] = sorted(container.get('env', []), key=lambda item: item['name'])
    annotations = {key:value for key,value in template.get('metadata', {}).get('annotations', {}).items()
        if not key.startswith(('client.knative.dev/', 'run.googleapis.com/client-'))}
    service_annotations = record.get('metadata', {}).get('annotations', {})
    security = {key:service_annotations.get(key) for key in ('run.googleapis.com/iap-enabled',
        'run.googleapis.com/invoker-iam-disabled','run.googleapis.com/ingress',
        'run.googleapis.com/default-url-disabled','run.googleapis.com/custom-audiences')}
    return {'runtimeSpec':spec,'runtimeAnnotations':annotations,'security':security,'traffic':record['spec'].get('traffic')}


def image_update_arguments(service, image):
    return ['run','services','update',service,'--region=' + REGION,'--image=' + image]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts',type=Path,required=True,help='Private directory containing a fresh reviewed cloud-before.json')
    parser.add_argument('--apply',action='store_true')
    args = parser.parse_args()
    artifacts = args.artifacts.resolve(); artifacts.mkdir(exist_ok=True); os.chmod(artifacts,0o700)
    lock = os.open(artifacts / 'app-update.lock',os.O_CREAT | os.O_RDWR,0o600)
    try: fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('This reviewed application update already has an active runner') from None
    before = json.loads((artifacts / 'cloud-before.json').read_text())
    account = None

    def cloud(arguments,label,*,sensitive=False):
        result = subprocess.run(['gcloud',*arguments,'--project=' + PROJECT,*(['--account=' + account] if account else []),'--quiet'],capture_output=True,text=True)
        path = artifacts / (label + '.log')
        path.write_text('Credential output intentionally not recorded.\n' if sensitive else result.stdout + '\n' + result.stderr); os.chmod(path,0o600)
        if result.returncode: raise RuntimeError('Cloud operation failed: ' + label + '; inspect its private log')
        return result.stdout.strip()

    def inspect(name):
        return {'service':json.loads(cloud(['run','services','describe',name,'--region=' + REGION,'--format=json'],'inspect-' + name)),
            'iam':json.loads(cloud(['run','services','get-iam-policy',name,'--region=' + REGION,'--format=json'],'iam-' + name))}

    def unchanged(name):
        current = inspect(name)
        if (runtime_signature(current['service']) != runtime_signature(before[name]['service'])
                or service_images(current['service']) != service_images(before[name]['service'])
                or canonical_bindings(current['iam']) != canonical_bindings(before[name]['iam'])):
            raise RuntimeError('The reviewed service changed; do not overwrite another deployment or runtime configuration')
        return current

    account = cloud(['config','get-value','account'],'deployer').lower()
    if not account.endswith('@loreal.com') or account.endswith('.gserviceaccount.com'):
        raise RuntimeError('Use the intended real company deployment identity')
    for name in (API,UI):
        current = unchanged(name)
        if not no_public_access(current['iam']): raise RuntimeError('Unexpected public Cloud Run invocation binding')
        traffic = current['service']['spec'].get('traffic', [])
        if len(traffic) != 1 or traffic[0].get('latestRevision') is not True or traffic[0].get('percent') != 100:
            raise RuntimeError('Review the existing traffic split before deploying; no traffic override was applied')
    iap_args = ['iap','web','get-iam-policy','--region=' + REGION,'--resource-type=cloud-run','--service=' + UI,'--format=json']
    iap_before = json.loads(cloud(iap_args,'iap-before'))
    identity = cloud(['auth','print-identity-token'],'verification-identity',sensitive=True)
    backend = before[API]['service']['status']['url']; frontend = before[UI]['service']['status']['url']

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*_args,**_kwargs): return None

    def get(url,authenticated=True):
        headers = {'Cache-Control':'no-cache','Accept':'application/json'}
        if authenticated: headers.update({'Authorization':'Bearer ' + identity,'X-Feedback-User-Authorization':'Bearer ' + identity})
        try:
            with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url,headers=headers),timeout=120) as response:
                return response.status,response.read(),response.headers
        except urllib.error.HTTPError as error: return error.code,error.read(),error.headers

    code,body,_ = get(backend + '/api/auth/me'); user = json.loads(body) if code == 200 else {}
    if code != 200 or user.get('email','').lower() != account or user.get('role') != 'reviewer' or user.get('demoMode'):
        raise RuntimeError('A verified existing BigQuery reviewer grant is required; no grant will be seeded')
    api_env = {item['name']:item for item in before[API]['service']['spec']['template']['spec']['containers'][0].get('env', [])}
    manifest_path = Path('/home/dhruv/loreal-neo/llm-graph-builder/output/rca_markdown_gcs_visual_analysis/manifest.json')
    manifest = manifest_path.read_bytes()
    if 'neo-rca-visual-' + hashlib.sha256(manifest).hexdigest()[:20] != api_env.get('FEEDBACK_NEO4J_CORPUS_VERSION', {}).get('value'):
        raise RuntimeError('The local provenance manifest differs from the deployed pin; evidence configuration will not be changed')
    if not args.apply:
        print(json.dumps({'ready':True,'imageOnly':True,'runtimeAndIapConfigurationPreserved':True,'rcaOrAgentCalls':0,'applied':False},indent=2)); return

    contexts = {}
    for name in (API,UI):
        folder = artifacts / (name + '-source'); folder.mkdir(exist_ok=True)
        if name == API:
            source = ROOT / 'backend'; files = ('Dockerfile','.dockerignore','requirements.txt'); directories = ('app',)
        else:
            source = ROOT / 'agent-quality-console'; files = ('Dockerfile','.dockerignore','package.json','package-lock.json','server.mjs','index.html','vite.config.ts','tsconfig.json'); directories = ('src',)
        for item in files: shutil.copy2(source / item,folder / item)
        for item in directories: shutil.copytree(source / item,folder / item,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.env','.env.*'))
        if name == API: (folder / 'evidence-manifest.json').write_bytes(manifest)
        (folder / '.gcloudignore').write_text('.git\n.env\n.env.*\n.venv\nnode_modules\n__pycache__\n*.pyc\n')
        if any(path.name == '.env' or path.name.startswith('.env.') for path in folder.rglob('*')):
            raise RuntimeError('A private environment file entered a build context')
        contexts[name] = folder
    tag = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-taxonomy-triage-' + secrets.token_hex(3)

    def build(name):
        image = f'{REGION}-docker.pkg.dev/{PROJECT}/cloud-run-source-deploy/{name}:{tag}'
        sa = before[name]['service']['spec']['template']['spec']['serviceAccountName']
        config = {'steps':[{'name':'gcr.io/cloud-builders/docker','args':['build',*(['--build-arg','VITE_AUTH_MODE=google_iam'] if name == UI else []),'-t',image,'.']}],
            'images':[image],'serviceAccount':f'projects/{PROJECT}/serviceAccounts/{sa}','options':{'logging':'CLOUD_LOGGING_ONLY'},'timeout':'1200s'}
        path = artifacts / (name + '-build.json'); path.write_text(json.dumps(config,indent=2))
        value = json.loads(cloud(['builds','submit',str(contexts[name]),'--config=' + str(path),'--region=' + REGION,'--suppress-logs','--format=json'],'build-' + name))
        (artifacts / (name + '-build-result.json')).write_text(json.dumps(value,indent=2))
        return name,image.rsplit(':',1)[0] + '@' + value['results']['images'][0]['digest']

    print(json.dumps({'phase':'building','imageOnly':True,'workerToggled':False,'rcaOrAgentCalls':0}),flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool: images = dict(pool.map(build,(API,UI)))
    (artifacts / 'images.json').write_text(json.dumps(images,indent=2))
    for name in (API,UI):
        unchanged(name)
        print(json.dumps({'phase':'deploying','service':name}),flush=True)
        cloud(image_update_arguments(name,images[name]),'deploy-' + name)
    after = {name:inspect(name) for name in (API,UI)}
    (artifacts / 'cloud-after.json').write_text(json.dumps(after,indent=2))
    for name in (API,UI):
        if (runtime_signature(after[name]['service']) != runtime_signature(before[name]['service'])
                or canonical_bindings(after[name]['iam']) != canonical_bindings(before[name]['iam'])):
            raise RuntimeError('A runtime/IAM setting changed unexpectedly; do not change RCA as a workaround')
    if canonical_bindings(json.loads(cloud(iap_args,'iap-after'))) != canonical_bindings(iap_before):
        raise RuntimeError('IAP login policy changed unexpectedly')
    checks = {}
    for label,path,expected in [('verifiedReviewer','/api/auth/me',200),('authorizedDataRead','/api/feedback?page_size=1',200),
        ('taxonomyChoicesAvailable','/api/my/business-taxonomy',200),('hostedDemoPickerDisabled','/api/auth/mock-users',404)]:
        code,body,_ = get(backend + path); checks[label] = code == expected
        if label == 'taxonomyChoicesAvailable' and code == 200:
            options = json.loads(body); checks['taxonomyIncludesF2sLifecycleAndCustom'] = options.get('allowCustom') is True and 'Lifecycle Management' in options.get('subdomains', {}).get('F2S', [])
    code,body,_ = get(backend + '/openapi.json')
    schema = json.loads(body) if code == 200 else {}
    fields = schema.get('components', {}).get('schemas', {}).get('FeedbackCreate', {}).get('properties', {})
    checks['submissionApiAcceptsDomainAndSubdomain'] = {'business_domain','business_subdomain'}.issubset(fields)
    code,_,headers = get(frontend + '/',False)
    checks['frontendGoogleLoginPreserved'] = code in {302,303,307} and urlsplit(headers.get('Location','')).hostname in {'accounts.google.com','iap.googleapis.com'} or bool(code == 401 and headers.get('X-Goog-IAP-Generated-Response'))
    code,_,_ = get(backend + '/docs',False); checks['anonymousApiBlocked'] = code in {401,403}
    result = {'checks':checks,'passed':all(checks.values()),'services':{name:{'url':after[name]['service']['status']['url'],
        'revision':after[name]['service']['status']['latestReadyRevisionName'],'image':images[name]} for name in (API,UI)},
        'runtimeIapIamAndSecretBindingsUnchanged':True,'workerToggled':False,'applicationGrantsChanged':False,
        'workflowOrGoldenDataWritten':False,'rcaOrAgentCalls':0,'pilotRetries':0}
    (artifacts / 'app-update-result.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result,indent=2),flush=True)
    if not result['passed']: raise RuntimeError('An application/auth check failed; no request was replayed')


if __name__ == '__main__':
    main()
