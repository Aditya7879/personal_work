# Google-authenticated sandbox deployment

The frontend is directly browser-accessible through **Google-managed IAP** in
`oa-apmena-techsandbox-ap-dv`. The backend remains **IAM-private**. Neither Cloud
Run service has an `allUsers`/`allAuthenticatedUsers` invoker binding:

```text
Browser → neo-feedback-ui → Google/IAP sign-in → signed company identity
        → explicit individual BigQuery grant → UI runtime identity
        → IAM-private neo-feedback-api → BigQuery / Neo4j / configured agent
```

Runtime **and build** identity:
`411502743425-compute@developer.gserviceaccount.com` (the requested default compute
service account). Its existing broad project permissions are not removed or
expanded by this deployer. New invocation bindings are service-scoped.

The Cloud Run invoker check stays enabled. Google's managed IAP service agent can
invoke only the frontend; the UI's unchanged runtime identity invokes the private
API. Ingress stays `all`; this is **not** an internal-VPC-only deployment. Google
login alone never grants application access: the verified email must have an
active, unexpired individual BigQuery grant.

Open **https://neo-feedback-ui-n2st4354oa-ew.a.run.app** and sign in with the intended
company Google account. No gcloud installation or local proxy is needed. A user
without an application grant is denied data/actions after sign-in. Reviewers
manage individual access under **Settings → People & access**.

## Current authentication/authorization deployment

### Application feature updates after IAP

Use the image-only, IAP-aware updater for reviewed application-code changes:

```bash
backend/.venv/bin/python deploy/app_update.py --artifacts /private/reviewed-current-snapshot
backend/.venv/bin/python deploy/app_update.py --artifacts /private/reviewed-current-snapshot --apply
```

It builds allowlisted source contexts as the existing runtime/build identity and
updates only image digests. Every runtime value (including auth and all secret
version bindings), IAP/IAM policy, worker setting, scaling and traffic strategy is
compared before/after; concurrent changes stop the update. No workflow/taxonomy
schema migration, grant seed, RCA/evidence/agent probe, job retry or data repair is
part of image deployment. Any approved saved-result metadata repair is a separate,
explicit, audited operation. Do not use the historical bootstrap/IAM-only smoke
flow to work around Google-managed IAP's programmatic-client restrictions.

For the in-app **Demo Admin** feature, use the narrowly scoped
`deploy/role_demo.py` instead: it can add only the reviewed
`FEEDBACK_ROLE_DEMO_ENABLED=true` flags and the API's fixed existing UI demo
origin, alongside reviewed image digests. Every other runtime/secret/IAM/IAP/
worker/scaling value and all live table fingerprints remain guarded. The normal
image-only updater deliberately cannot add feature flags. See
[`../docs/demo-admin-role.md`](../docs/demo-admin-role.md) for role bootstrap,
sample isolation, prototype retirement and validation requirements. This feature
does not create another service, change login mode or require project IAM.

### People & access

Real Google reviewers can now open **Settings → People & access** to:

- Add an individual company email with **Reporter**, **Reviewer** or **Demo Admin** application access.
- Change a person's role, activate/revoke access, or set/clear an expiry.
- Search/page through grants and inspect append-only access-change history.

Reporters and mock/private-demo profiles cannot read or change the real access
directory. Reviewer remains an administrative application role. Demo Admin adds
only isolated demo-view switching to those same Reviewer rights, not real owner
impersonation or additional cloud/production access. Grant either only when needed.
A reviewer or Demo Admin cannot rewrite their
own grant; another active reviewer must do that. Changes use the exact saved
update timestamp, a fresh reviewer check inside the same BigQuery transaction,
and a singleton serialization row so concurrent creates cannot duplicate a
principal. Conflicts preserve the draft and are not automatically replayed.

The audit/control tables are `application_access_events` and
`application_access_control` in the same dataset. Revocation retains grants,
audit history and feedback ownership; no feedback/golden/evaluation tables are
changed. This screen does **not** send invitation emails, grant cloud IAM or
authorize upstream NEO/model access. Application-role changes propagate within
30 seconds; privileged access-management reads/writes recheck the reviewer role.

Deploy this feature to the existing IAM-private services without reseeding users:

```bash
backend/.venv/bin/python deploy/iam_authz.py \
  --artifacts /path/to/private/reviewed-snapshot --access-management
```

The explicit installer adds only audit/control storage. Existing grants are not
seeded, changed or revoked by this deployment.

### Direct browser sign-in with managed IAP (enabled)

For company users **in the same Google organization as the project**, Cloud Run
IAP can use a **Google-managed OAuth client**. No separately registered web client
ID, client secret, frontend session-signing secret or local proxy is needed.
Out-of-organization users can require custom OAuth configuration; do not broaden
this company-only deployment to work around that restriction.

The deployed application uses this path:

```text
Browser → internet-reachable neo-feedback-ui → Google-managed IAP sign-in
        → verified signed IAP assertion + individual BigQuery grant
        → UI workload identity → IAM-private neo-feedback-api
```

IAP is the login boundary, not the application role source. A company-domain IAP
login rule permits authentication only: a person with no active BigQuery grant
still cannot read feedback or act in the app. No public `allUsers` or
`allAuthenticatedUsers` binding is added to either Cloud Run service, and the API
does not get IAP enabled or become public. Users reach the normal frontend URL
in a browser rather than requiring individual Cloud Run invocation grants.

`deploy/browser_iap.py` preflights the existing frontend's IAP policy before any
mutation. The deployment operator needs `iap.webServices.getIamPolicy` and
`iap.webServices.setIamPolicy`, Cloud Run update/policy access, and `actAs` on the
unchanged runtime identity. These permissions were confirmed on the current
deployment account on 28 October 2026; normal app users do not need them. Do not
remove IAM authentication to work around a missing setup permission.

After the IAP-capable feature deployment, inspect the plan, then apply only with
the required IAP-policy permission and an already-approved reviewer identity:

```bash
backend/.venv/bin/python deploy/browser_iap.py --artifacts /private/current-deployment
backend/.venv/bin/python deploy/browser_iap.py --artifacts /private/current-deployment --apply
```

If old temporary build/deployment receipts are unavailable, revalidate the
**existing immutable image digests** and the live signed-identity/BigQuery-role,
IAP-capability and security/regression checks. Pass that explicit fresh review as
`--reviewed-images /private/image-review.json`. A matching current image is not
assumed to be IAP-capable merely because it is deployed. The helper does not
fabricate old build records or rebuild images to reconstruct a lost receipt.

On first use the helper initializes Google's managed **IAP service agent** via
the documented Service Usage `generateServiceIdentity` API. This needs the
corresponding Service Usage setup permission and does not create an app runtime
account, issue/download any key, add an application grant, read a secret, or
install optional gcloud SDK components. It then grants only that IAP edge identity
invocation of the existing frontend. The backend policy is not changed. Before/
after guards also ensure no unrelated frontend/IAP policy bindings are altered.

This changes only explicit auth fields, enables IAP on **the frontend only**,
permits company-domain login through IAP, and adds service-scoped UI invocation
for Google's IAP service agent. Runtime/build identities, all existing secret
bindings, model/evidence/agent/worker settings and scaling stay unchanged. It does
not build images, change application grants, run RCA/agent checks or retry pilot
cases. A failed IAP-policy preflight makes no configuration changes.

Both the UI proxy and backend verify IAP signatures, issuer, expiration, exact
resource audience and company identity. Plain email/role headers cannot authorize
anything. IAP assertion/workload credentials stay server-side; cookie-authenticated
mutations require the exact frontend Origin and a same-origin action header.
Account switching uses IAP's `gcp-iap-mode=CLEAR_LOGIN_COOKIE`; it clears this app's
IAP session, not the user's Google session. A single signed-in Google account can
be silently signed back in by Google.

The deployed IAM mode verifies the complete signed Google user identity, then
looks up authorization in:

`oa-apmena-techsandbox-ap-dv.agent_quality.application_access_grants`

The table contains `email`, `display_name`, `role` (`reporter` or `reviewer`),
`active`, optional `expires_at`, `created_at`, `updated_at` and `updated_by`.
There is no default role, domain-wide application grant, owner alias or browser
role selection. Missing/inactive/expired rows deny access. Duplicate/invalid rows
and storage failures fail closed. The old `FEEDBACK_GOOGLE_IAM_USERS_JSON` is not
an authorization fallback. Grant caching is bounded to 30 seconds and cannot
outlive expiration; Google signature/audience/expiry checks still run per request.

For the reviewed, existing-service auth upgrade, use **`deploy/iam_authz.py`**, not
the legacy bootstrap deployer below:

```bash
backend/.venv/bin/python deploy/iam_authz.py --artifacts /path/to/private/reviewed-snapshot
```

Its reviewed snapshot records both service configurations/IAM policies and the
already-approved Google grants. It creates/seeds only access storage (insert-only;
existing changed or revoked rows are not overwritten), builds IAM-mode images and
updates **only images and explicit auth environment fields**. Runtime/build service
accounts, secret version bindings, agent connections, RCA/model/evidence settings,
worker flags, CPU/memory, scaling, ingress and IAM policy remain unchanged.
No secret rotation, RCA/evidence probes, agent calls, job retries, workflow schema
init, ingestion or schedules are part of this deployment. Smoke checks cover IAM,
the actual BigQuery role lookup, data reads and the disabled hosted demo picker.
Existing cloud settings are preserved even when an existing worker is already off;
the deployer does not turn it off or on as an auth workaround.

Prefer **Settings → People & access** for routine changes. Operators with normal
BigQuery write permission can still manage records directly, for example:

```sql
-- Revoke access without an image deployment. Do not change email to impersonate an owner.
UPDATE `oa-apmena-techsandbox-ap-dv.agent_quality.application_access_grants`
SET active = FALSE, updated_at = CURRENT_TIMESTAMP(), updated_by = SESSION_USER()
WHERE LOWER(TRIM(email)) = 'person@loreal.com';

-- Change an existing role. Keep exactly one row per normalized email.
UPDATE `oa-apmena-techsandbox-ap-dv.agent_quality.application_access_grants`
SET role = 'reporter', updated_at = CURRENT_TIMESTAMP(), updated_by = SESSION_USER()
WHERE LOWER(TRIM(email)) = 'person@loreal.com';
```

Direct SQL administration requires the operator's normal BigQuery write permission.
In-app reviewer changes use the backend runtime identity after application-role
checks; reviewers do not need personal BigQuery or Secret Manager IAM roles.
An application user does not need direct BigQuery access: the existing backend
runtime identity reads the row for the verified user. In the browser, the company
IAP login rule and managed IAP edge identity cover the frontend boundary; ordinary
users do not need an individual Cloud Run invoker role. A BigQuery grant does not
authorize direct invocation of the private API. No public or blanket-authenticated
Cloud Run binding is added.

`backend/scripts/init_access_grants.py --seed-file /private/approved.json --apply`
is an explicit migration/bootstrap tool, not a startup step. Never use local demo
profiles as Google IAM grants or re-seed deleted users without authorization.

## Legacy authenticated loopback flow (before browser IAP)

The hosted app now uses the direct frontend URL and Google sign-in above. This
section documents the earlier IAM-only preview, not the current browser entry.
Google-managed IAP does not automatically allow programmatic gcloud OAuth clients;
do not add client allowlists or store personal tokens just to bypass browser login.

With the intended company account signed into gcloud:

```bash
gcloud auth login
python3 deploy/proxy.py --port 8080
```

Open **http://localhost:8080**. The helper needs only Python's standard library and
gcloud; it can also run on your laptop from a copy of `proxy.py`. If it runs on a
remote development machine, forward that machine's loopback port through your IDE
or an authenticated SSH tunnel. Do not bind the helper to a public interface or
publish the port through an anonymous tunnel.

The helper binds only `127.0.0.1`, validates loopback Host/Origin headers to prevent
DNS-rebinding/cross-site access, refreshes the selected gcloud account's ID token
in memory, and never puts Google credentials into browser JavaScript/storage. It does
not log tokens or payloads and never automatically retries mutations.

The stock `gcloud run services proxy` supplies `X-Serverless-Authorization`, whose
signature Cloud Run removes before delivering the request. This app needs a
**complete Google user JWT** to verify the actual user independently. The supplied
helper preserves that full credential in `X-Feedback-User-Authorization`. The UI
server forwards it and separately obtains its **own** runtime-service ID token
for invoking the backend. The backend checks Google's signature, issuer,
expiration, permitted audience, verified company email and explicit role grant.
Plain email/role headers, stripped/unsigned JWTs and mock identity selection do
not authorize access.

## Original hosted demo picker (legacy mode, not the current IAM deployment)

To deploy the original reviewer/reporter picker with the **existing dataset and
normal reviewer workflow**, use:

```bash
backend/.venv/bin/python deploy/cloudrun.py --grant-current-deployer --private-demo
```

This is not standalone cloud mock authentication. `private_demo` first verifies
the real Google caller, requires its active reviewer grant **and** explicit entry
in `FEEDBACK_PRIVATE_DEMO_PRESENTERS`, then permits that presenter to select a
registered demo profile. Everyone else is denied. The ordinary development-only
`mock` mode still refuses Cloud Run and role previews refuse production mode.

The original private profile mapping is a separate Secret Manager reference;
the sample requester's owner scope is never returned in profiles or session
claims. The browser stores a short-lived demo-persona session, not a Google token.
`X-Feedback-Demo-Authorization` carries that session separately from the verified
Google credential. A session is signed and bound to its Google presenter, so it
cannot be used alone or replayed by another Google user. Switch demo user returns
to the same picker; it does not change the real caller's grants.

There is no blanket read-only redesign or replacement/synthetic dataset. A demo
reviewer has the existing reviewer workflow and writes use the real presenter's
audit identity. Demo reporters can create/edit their own reserved test-account
submissions. Selecting a mapped reporter view cannot edit a real employee's
submission or confirm a fix on their behalf; actual owner/revision/environment
checks remain enforced. Notification read-state changes during a role preview
are client-side only and do not alter another person's persisted unread state.

Cloud AI calls still use the runtime service account. Selecting a mock profile
does not fix the known gateway/NEO authorization restrictions. The deployed site,
picker and data APIs now verify successfully; the earlier apparent routing
failure was a bad readiness probe (`/healthz`), not an unavailable application.
The deployer/verifier does not start jobs or fabricate answers.

That legacy IAM-only mode returned 403 when either URL was opened directly.
In the current deployment the frontend redirects to Google sign-in; the private
API still blocks unauthenticated requests. Do not enable anonymous Cloud Run
invocation as a workaround for either authentication boundary.

## What is stored, and what is automatic?

### Two separate AI connections

```text
Question → NEO Companion generation API → fresh agent answer
Answer + retrieved Neo4j sources → L'Oréal AI Gateway → RCA / correction assessment
```

The NEO endpoint generates the business answer; the gateway is used directly by
this app's separate RCA judge. They have independent authorization policies.
Being allowed to invoke NEO does not automatically authorize direct gateway
calls, or vice versa. A configuration GET returning 404 is not a test of the
actual NEO generation POST.

The normal IAM deployment stores five credential/configuration values in Secret Manager:
Neo4j URI, Neo4j username, Neo4j password, the direct OpenAI query-embedding API
key, and the application's stable scope-signing secret. Agent target URLs,
permitted Google audiences and explicit user grants are runtime configuration.
Feedback/workflow/history remains in BigQuery and source chunks remain in Neo4j.

No Google access token, downloaded service-account JSON key or personal gcloud
credential is stored in either cloud image/configuration. The attached default
compute identity obtains short-lived Google credentials through ADC/metadata.
There is no separate static gateway/NEO API key in this configuration.

Actual approved hello tests for candidate
`neo-nasapmena-dv@oa-apmena-techsandbox-ap-dv.iam.gserviceaccount.com` (19 October):
gateway chat completion succeeds with **200 / Hello / claude-sonnet-4-6** when the
email OAuth scope is included; actual NEO non-production generation returns
**403 / Access to requested content is forbidden**. These are one-shot inference
tests, not configuration GETs. The running deployment identity and IAM grants
were not changed, and the candidate still lacks the audited BigQuery/secret
permissions needed as a full backend replacement.
The `--private-demo` variant additionally stores the existing private demo profile
mapping as a sixth, server-only Secret Manager reference.

**Credential availability is not permission.** The ability to mint a Google
token, or existing project Editor/Cloud Run roles, does not establish access to
L'Oréal's model gateway or a particular NEO context. Those systems must authorize
the service-account principal separately. Authenticated model/configuration GET
checks can verify read access, but do not by themselves prove generation-POST
permission; avoid declaring the deployment ready or launching jobs on that basis.

Latest live checks (19 October 2026): the gateway `/models` request using the
default compute identity returns **401: “GCP service account is not authorized in
the organization.”** The local developer credential gets 200 and lists the
requested Sonnet model. Adding the email OAuth scope does not change the compute
rejection. The gateway organization owner must authorize the service-account
principal; saving a personal/temporary Google token is not a deployment fix.
The initial NEO configuration GET returned 404 with both credentials and was
inconclusive. After explicit user approval, exactly one synthetic non-production
request was sent to the actual NEO generation endpoint as the default compute
identity: **HTTP 403**, with no completed AI answer. There was no retry, RCA call,
feedback job or feedback-record write. The NEO API/context owner must resolve
that invocation restriction separately from the gateway organization grant.
The cloud worker is still disabled pending these AI permissions. The apparent
Cloud Run access blocker was subsequently traced to probing `/healthz`: the real
site and application APIs return 200. The verifier now probes `/` (frontend) and
`/docs` (backend anonymous-IAM check), not that misleading path.

## Legacy initial bootstrap deployer

The commands in this section describe the older initial bootstrap/private-demo
path. It has worker/RCA verification behavior and is **not used for auth-only
upgrades**. Use `iam_authz.py` above to preserve existing runtime configuration.

From the feedback-app root, with backend dependencies installed:

```bash
backend/.venv/bin/python deploy/cloudrun.py \
  --grant-current-deployer \
  --enable-worker
```

`--grant-current-deployer` is an **explicit** preview reviewer grant to the active
company gcloud account; it is not a domain-wide or implicit bootstrap-admin
policy. Alternatively, pass one or more `--reviewer reviewer@loreal.com` arguments.
No other identity gets application access by default. Without `--private-demo`,
the private demo-reporter ownership mapping and local test users are not deployed. Reporter access can be
configured later through explicit backend grants; there is no cloud identity
picker.

The deployer:

- Uses separate, allowlisted build contexts with only required code/configuration.
  Private `.env` files, local credentials, workbooks, browser fixtures and caches
  never enter build sources or images.
- Copies the existing ingestion manifest as **provenance metadata only**, pins
  its fingerprint, and searches source text in Neo4j. No document re-ingestion,
  index mutation or stored-chunk re-embedding occurs.
- Sends the configured Neo4j/OpenAI credentials and a stable scope-signing secret
  to app-owned Secret Manager secrets over stdin. Images/configuration contain
  version-pinned secret references, never credential values. Existing unrelated
  services/secrets are not overwritten. Existing app-owned secrets are reused;
  credential rotation requires `--rotate-owned-secrets` explicitly.
- Builds both images through regional Cloud Build using the default compute
  account, and deploys immutable image digests to `neo-feedback-api` and
  `neo-feedback-ui` in `europe-west1`.
- Deploys the API with its worker initially disabled, then checks anonymous IAM
  rejection, real user authorization, BigQuery reads, Neo4j corpus/index coverage
  and disabled mock sign-in through the private frontend.
- Enables the worker only after those checks when `--enable-worker` is supplied.
  Cloud Run uses runtime ADC/metadata credentials; no gcloud CLI, developer token
  or service-account key is required inside either image.
- Never initializes/replaces feedback or golden/evaluation tables, queues a job,
  invokes the agent, starts a schedule, commits code or pushes git changes.

The existing `agent_quality` dataset and immutable answer/RCA history are reused.
The non-production agent target is backend-owned; production invocation and the
separate golden-evaluation adapter remain disabled. External Companion/gateway
permissions for the runtime service account must be granted in those systems;
configured target metadata alone does not prove permission to generate answers.

If image deployment succeeds but endpoint verification fails, do not enable
anonymous access or rebuild repeatedly. Recheck the existing deployment:

```bash
python3 deploy/verify.py --enable-worker
```

An authenticated Google-edge 404 with no container request logs is an unresolved
routing/network-access condition, not proof that the application is working or
that IAM is private. Check ingress/default URL settings and, where applicable,
the approved network/VPC Service Controls access path. Organization-policy
**dry-run** denials with `liveResult=ALLOWED` are not an enforced denial and must
not be treated as the root cause. Do not disable IAM/perimeter controls as a fix.
The verifier leaves the worker unchanged on failures and enables it only after
successful authenticated app/BigQuery/Neo4j checks.

## Worker billing and lifecycle

### Runtime service-account access checklist

For a replacement runtime identity, check effective permissions rather than
assuming that a Cloud Run Admin role covers the complete application:

- BigQuery query-job creation on the sandbox project, plus read/write access to
  the existing `agent_quality` feedback/workflow/golden/evaluation tables.
  Typical scoped grants are project `roles/bigquery.jobUser` and dataset
  `roles/bigquery.dataEditor`; do not grant project Editor as a shortcut.
- `secretmanager.versions.access` on the five core app secrets and, for the
  hosted picker, the private demo-profile mapping secret. No secret values need
  to be printed or copied into diagnostic logs.
- Invocation of the private backend, normally `roles/run.invoker` on that service
  for the frontend runtime. Broader existing Cloud Run Admin access is not
  required merely to run the application.
- L'Oréal gateway organization/model authorization and NEO context-generation
  access, checked separately from Google Cloud project roles. Model/configuration
  GETs alone are not full generation smoke tests.
- Neo4j connectivity and the embedding provider use the configured credentials;
  a Google service-account name alone does not authenticate to either provider.

Runtime identities are not demo presenters and should not be added to the human
presenter/role-picker allowlists. Checks can run in a separate, read-only,
temporary workload as the candidate account when the operator has `actAs`, without
switching the running UI/API identity or granting token-creator permissions.

For an explicitly approved AI generation smoke test, send one non-sensitive hello
to the gateway chat-completions endpoint and one to the non-production NEO
generation endpoint as the same verified candidate identity. Request the email
OAuth scope where required, disable retries and redirects, and parse a completed
assistant response rather than counting HTTP/model-list access alone. Do not
enqueue feedback work or save the test into answer/RCA history. Keep credentials
and raw tool traces out of logs and remove the temporary diagnostic job afterward.

The enabled persisted worker needs CPU **after** queue requests return. It uses
one minimum backend instance, 1 vCPU / 1 GiB, instance-based CPU allocation and a
maximum of one instance. This incurs idle billing. The frontend uses 512 MiB,
request-based CPU, zero minimum instances, and a maximum of one instance.

To pause the worker and remove the minimum instance without deleting data:

```bash
gcloud run services update neo-feedback-api \
  --project=oa-apmena-techsandbox-ap-dv --region=europe-west1 \
  --min-instances=0 --cpu-throttling \
  --update-env-vars=FEEDBACK_WORKER_ENABLED=false
```

To resume:

```bash
gcloud run services update neo-feedback-api \
  --project=oa-apmena-techsandbox-ap-dv --region=europe-west1 \
  --min-instances=1 --no-cpu-throttling \
  --update-env-vars=FEEDBACK_WORKER_ENABLED=true
```

The worker uses the existing renewable BigQuery leases. Do not launch another
bulk runner, ingestion/recovery process or scheduler as part of deployment.
Existing local services are not stopped by this deployer. If left running, their
worker competes for the same guarded leases; stop/disable it separately when the
cloud worker should be the sole executor. Do not discard an in-flight generation.

Deployment/status logs are stored in a private `/tmp/opencode/feedback-cloudrun-deploy-*`
directory. Token outputs are explicitly redacted before logging. The final
`deployment-result.json` records service URLs, pinned image digests, verified
private-access checks and corpus counts without credential values.
