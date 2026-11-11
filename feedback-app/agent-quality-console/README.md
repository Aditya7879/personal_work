# Agent Quality Console

Frontend for the feedback and triage workflow. Feedback data is loaded from
the FastAPI service and persisted in BigQuery; this frontend does not contain a
runtime mock dataset.

## Run locally

Start the backend first:

```bash
cd ../backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
gcloud auth application-default login
python -m scripts.init_bigquery
uvicorn app.main:app --reload --port 8001
```

Then start the frontend:

```bash
cd ../agent-quality-console
npm install
npm run dev
```

### Reviewer/reporter demo

The deployed IAP app now supports the **Demo Admin** application role. Its
**Switch demo view** chooser uses fictional Reporter/Reviewer personas, isolated
sample feedback and explicitly simulated AI, and **Exit demo** restores the real
Google account. It uses the normal `google_iam` build and login; no password or
separate app is needed. See [`../docs/demo-admin-role.md`](../docs/demo-admin-role.md).
The local/legacy picker below is separate and does not enable hosted switching.

Open **http://localhost:3000/?demo=login** to start at the original mock-account
picker, even if a previous session is remembered. Choose **Quality Reviewer** for
the reviewer workspace or **Sample requester (existing feedback)** for the
owner-scoped reporter view. Alex/Sam requester accounts remain available too.
No company sign-in is required for this **local** demo. The header's **Switch demo
user** control returns to the picker and clears the previous account's client
state/cache before another role is selected.

`npm run dev:demo` explicitly starts the loopback Vite server in mock mode. The
local backend must use development/mock auth; keep its full existing private demo
mapping rather than replacing it with defaults. The mapping's original owner
identity is server-only and must never be put into browser configuration or docs.
The local `.env.local` pins `VITE_AUTH_MODE=mock` and is excluded from git/build
contexts. Private Cloud Run builds still explicitly use `google_iam`; neither the
demo URL nor the switch control bypasses deployed identity/grant checks.

For the same picker in the private hosted sandbox, deploy with
`--grant-current-deployer --private-demo` as described in `../deploy/README.md`.
The existing data and normal reviewer workflow are retained. A verified,
explicitly authorized presenter can choose demo profiles; ordinary users cannot
use the picker to obtain reviewer rights. Google and demo-persona credentials
travel separately, and real employees' owner-only actions remain protected.

Vite proxies `/api` and `/healthz` to `http://localhost:8001`. Set
`VITE_API_URL` when the API is hosted at another origin.

### Interaction motion

Secondary actions share `ActionButton`: recognizable actions are icon-first;
less-obvious actions retain a short caption. The full label reveals with a subtle
180 ms width/fade transition on hover or keyboard focus. Menu triggers stay
expanded while open, and loading actions keep their label/status. Dense table
actions use a fixed footprint and expand leftward without resizing columns.
Touch controls remain compact, have 40 px targets and perform their normal action
on the first tap; no hover step is required. Narrow headers stay icon-first.
Full accessible names and disabled reasons are retained. Save, submit, confirmation,
AI-run actions, sticky workflow bars, destructive actions, pagination/navigation,
tabs and citation IDs remain explicitly
labelled rather than blindly applying the effect to every button. Hover styling
never calls an action/API or changes permissions, data or drafts.

Dialogs, the reporter detail drawer, filters, notifications and disclosures use
short 100–220 ms transitions with no bounce or decorative delays. Exit animations
finish before an overlay unmounts; closing surfaces become inert immediately.
Disclosures keep visited content mounted so drafts and answer scroll positions
survive collapsing. Citation navigation waits for the evidence panel to open.

OS/browser **Reduce motion** disables movement and timed transitions, including
smooth citation scrolling. Workspace navigation stays fade-only: transforming
the page would misplace its fixed dialogs. Switching accounts clears the previous
workspace immediately rather than animating private data between identities.

## Google-authenticated Cloud Run app

Deployment uses Google-managed IAP on the frontend and an IAM-private API, as
described in [`../deploy/README.md`](../deploy/README.md). Open
**https://neo-feedback-ui-n2st4354oa-ew.a.run.app** directly and sign in with your
company Google account. No local proxy or individual Cloud Run invoker grant is
needed for normal browser use. Both services keep the sandbox default compute
runtime identity; the separate Google-managed IAP edge identity invokes only the
frontend. Neither service is anonymously invokable.
The image builds with `VITE_AUTH_MODE=google_iam` and an empty `VITE_API_URL`, so
browser API calls stay same-origin through the authenticated server-side proxy.
No workload credential or private backend endpoint is embedded in browser code.

Deployed Google users receive their existing `reporter`/`reviewer` role only from
`oa-apmena-techsandbox-ap-dv.agent_quality.application_access_grants`. There is no
environment-JSON role fallback or hosted demo-role picker in IAM mode. Real
reviewers manage `role`, `active` and optional `expires_at` at **Settings → People
& access**, backed by BigQuery with immutable access-change audit history; changes
take effect within at most 30 seconds. Company sign-in is not an application
grant. Direct backend invocation still requires its separate IAM permission.
Local mock/demo configuration remains unchanged.

The backend verifies the signed company IAP identity and requires an explicit
application role grant; development mock users and private demo ownership aliases
are not available in the cloud app. `deploy/proxy.py` documents the older IAM-only
preview and is not required for the current browser login.

`server.mjs` serves only the built UI and proxies API calls to the fixed private
backend using runtime Google credentials. It replaces caller workload/identity
headers, rejects cross-site browser calls, does not follow redirects or retry
mutations, and keeps API responses private/no-store.

The People & access tab supports individual company users, least-privilege
Reporter defaults, explicit save/revocation confirmation, role/expiry editing,
search/pagination and change history. A reviewer cannot edit their own grant;
mock/private-demo profiles cannot administer real users. The settings tabs have
arrow/Home/End keyboard navigation and retain visited editors and unsaved drafts.
No invitation email is sent and no cloud/upstream permission is changed.

The same IAM-mode build now uses Google-managed IAP browser sign-in. `/auth/config` selects that
server-owned mode; no browser OAuth client secret, Google token or workload
credential is exposed. The UI server verifies the signed IAP assertion before
forwarding it to the private API with a separate runtime credential. All
cookie-authenticated mutations require exact Origin plus the same-origin action
header. The API independently verifies the assertion and resolves BigQuery roles.
This does not make the backend public or grant every company user an application
role. See `../deploy/README.md` for IAP configuration and migration details.

## Current scope

### Domain/subdomain submission and source review progress

The submission form has native domain and dependent subdomain dropdowns, with
**Other — enter a custom domain/subdomain** options. Choices combine standard
business suggestions with saved labels visible to the authenticated user. Both
fields are optional; custom entries are required/nonblank only when Other is
selected. Loading or failing to load saved choices does not discard drafts or
prevent custom input. A failed submission retains all fields and is not replayed.
The same controls support later owner edits and reviewer classification.

The selected values are first-class API fields, not just UI hints. Submitter
classification is labelled as user-provided and not independently verified; it is
not overwritten by automatic domain inference. These are business categories,
not RCA defect categories or new agents/environments.

Successful current-source RCA can mark the report **Triaged · AI ready · human
review pending**. The diagnosis remains unverified and human evidence review is
still required. The review-state column is explicitly the **source report**;
linked target-environment RCA does not advance it. Failed/inconclusive analysis
and stale captures do not automatically move review forward or resolve feedback.

### Agent environments and linked promotion

NEO is the existing agent; new-agent creation is intentionally not exposed.
Reviewer **Settings** can create/edit named environments, configure an approved
response endpoint, choose runtime authentication/response format and disable an
environment without deleting history. Configuration is persisted in BigQuery.
Saving configuration never invokes an agent and is not proof of upstream access.

The header's **Workspace environment** selector scopes the overview, inbox,
reporter list and answer/RCA selection. A target view includes original reports from that
environment and reports with linked retests there. The original reported
environment and reporter never change. An untested target does not borrow
another environment's answer, diagnosis or private evidence.

Select rows across pages (or **Select all N matching**) and use **Promote &
retest**. Review the exact count, choose a target and confirm once. A batch queues
one fresh answer/evidence/RCA workflow per selected input revision. Progress,
partial failures and cancelling queued items are visible; running calls are not
replayed or silently cancelled. **Recheck selected RCA only** reuses a saved
answer without invoking the agent again. Reporter-safe results remain automatic.
The same confirmation key survives selection-preview refreshes and lost-response
retries. A second batch cannot queue an already active target/input check.

Reviewers manage and test Production and Non-production connections using the
same controls. There is no extra Production SSO/grant requirement or confirmation
checkbox for endpoint testing. Feedback retests and bulk promotion also use the
same reviewer permissions for every environment; the environment/worker must be
enabled and the backend must have real upstream API access. Named environment IDs
are still checked for owner confirmation: DEV and UAT are not
interchangeable just because both are non-production. Imported unknown origins are
not guessed. The user explicitly confirmed the 156 current reports as Non-production;
that metadata correction did not rewrite their historical answers or RCA.
Private reviewer notes/evidence/traces remain private.

**Test endpoint** opens a dialog for one explicit, non-sensitive sample question
against the saved configuration. It uses backend runtime authentication, not the
browser identity, and shows HTTP status, timing, safe errors or a bounded response
preview. HTTP 200 without a completed answer is not a successful test. Test results
are persisted per configuration revision and runtime; saving a connection resets
its displayed test status. Lost-response recovery checks the same attempt without
automatically sending another request. No feedback, RCA or promotion is created.
Endpoint testing does not require an enabled environment or worker, regardless of
environment type. Only the explicit Send action makes the one response request.

The dashboard follows the selected environment and ignores stale overlapping
responses. **All environments** counts distinct feedback IDs rather than adding
source and promotion memberships. Latest target answer/RCA and automated
comparisons are separate from source-submitted verdicts and source-review state.
Golden datasets and untagged legacy evaluations are clearly marked agent-wide.

Reporter **Your verdict** opens the latest eligible answer review. Each saved
answer displays its own **Correct / Partially correct / Incorrect** reporter
verdict separately from its saved AI comparison/reasoning and RCA. An explicit
**Change your verdict for this answer** action supports audited, stale-value-guarded
corrections to the latest eligible answer. Neither a response nor a correction
starts AI work or changes an automated assessment. Passive history polling
preserves typed comments and does not disable verdict buttons; explicit refreshes
and writes retain their loading/duplicate-submit protections.

The submission editor distinguishes input revisions from opinion/metadata edits.
Actual question, answer, expectation, substantive feedback/follow-up and execution
context changes create a revision. Submitted verdict, title, impact, categories
and business labels are audited without a new revision, answer capture or job and
without invalidating RCA. Saves send both the loaded revision and edit timestamp;
stale same-revision edits are rejected. Historical answers show their exact input
revision and the current submission revision, rather than a generic mismatch.

For an existing installation, run the additive schema migration before restarting
the backend:

```bash
cd ../backend
.venv/bin/python -m scripts.init_agent_environments
```

It creates environment/configuration-version/batch and endpoint-diagnostic storage,
adds nullable job metadata columns and seeds the existing server-configured targets. It does not
replace feedback, change golden/evaluation data, queue jobs or enable workers.
Live execution still requires an enabled worker and actual endpoint permissions.

Connected:

- feedback submission;
- BigQuery-backed feedback inbox;
- feedback detail records;
- triage state/RCA updates;
- append-only feedback audit events.

Golden datasets, saved evaluation results and overview metrics read their API
repositories. Running the separate golden evaluator still requires its explicitly
configured backend adapter; configuring a feedback response environment does not
configure that evaluator. No fake metrics or mock feedback are rendered in the
live application.
