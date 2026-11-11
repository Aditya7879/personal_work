# Agent Quality Console API

FastAPI backend for feedback capture and triage persistence in BigQuery.

## Setup

```bash
cd /home/dhruv/trustworthy-ai/feedback-app/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
gcloud auth application-default login
python -m scripts.init_bigquery
uvicorn app.main:app --reload --port 8001
```

The service uses Application Default Credentials and the sandbox project from
`GCP_PROJECT_ID`. It never accepts BigQuery credentials from the browser.

### IAM-private sandbox deployment

See [`../deploy/README.md`](../deploy/README.md) for Google-managed browser IAP
on the frontend and the IAM-private backend. The cloud API uses
`FEEDBACK_AUTH_MODE=google_iam`, verifies the signed company IAP identity (or a
complete permitted Google user ID token for separately IAM-authorized API access),
and requires explicit active grants in BigQuery `application_access_grants`. A valid
company identity or Cloud Run invoker permission alone does not assign a role.
No local mock users, private demo ownership aliases or service-account keys are
deployed. Cloud workers still require explicit operational enablement after their
runtime access has been verified; preview authentication is not a separate
Production-only execution gate.

Real Google reviewers can manage individual grants at **Settings → People & access**.
The access API supports bounded/searchable listing, create, exact-version update,
revocation/activation, expiration and append-only change history. Only the existing
`reporter`, `reviewer` and `demo_admin` application roles are valid. Demo Admin
retains effective Reviewer permissions and adds switching between isolated sample
Reporter/Reviewer views after the same IAP sign-in. It grants no real employee
impersonation, extra production execution permission or cloud IAM role. See
[`../docs/demo-admin-role.md`](../docs/demo-admin-role.md). Mock/private-demo users cannot administer
real grants, and reviewers cannot modify their own access. Writes recheck the
real reviewer inside one serialized BigQuery transaction with the audit insert;
duplicate/stale/conflicting writes fail safely without automatic replay.

Demo-view requests require both an actor-bound `neo_role_demo` cookie and
`X-Feedback-Demo-View: 1`; expiry never falls back to live data. The repository and
simulated providers use request-local context, while role lookup stays on live
grants. Existing IAP, runtime identity, secret bindings and disabled live worker
are preserved. No standalone demo password login or new service is used.

For an explicitly approved **one-time import of a Google group's current users**,
`scripts/import_group_access.py` reads complete Cloud Identity membership with a
verified company Google operator, previews exact new Reporter grants, then applies
only an approved count/snapshot. Existing roles, inactive/expired grants and all
other users are preserved. The audit includes the source group and one-time mode;
group owner/manager roles never imply app Reviewer. No Google-group membership,
IAM policy, app image or sync schedule is changed. Future membership changes do
not automatically add or revoke application grants.

```bash
python -m scripts.import_group_access --group team@loreal.com --preview-out /private/preview.json
python -m scripts.import_group_access --group team@loreal.com --apply \
  --approved-preview /private/preview.json --expected-new N --result-out /private/result.json
```

The operator needs directory visibility and its existing real application-reviewer
grant, not a downloaded key or stored personal token. Credentials remain in memory;
the Cloud Identity quota project is supplied per request rather than rewriting ADC
configuration. Nested/external/non-user members require separate review instead of
being silently treated as individual company users. Automatic group synchronization
is a different feature and requires explicit cadence/removal policy and authorized
workload directory access; this importer never enables it.

`scripts/init_access_grants.py --management --apply` adds only access audit/control
storage (without seed input, no user grants change). It is an explicit installer,
not an application-startup migration. Existing workflow/history tables are untouched.

The optional `FEEDBACK_GOOGLE_IAP_AUDIENCE` enables independent verification of
the frontend's signed Google IAP assertion in `X-Feedback-IAP-Assertion`. It must
be the exact `/projects/NUMBER/locations/REGION/services/FRONTEND` resource, with
issuer `https://cloud.google.com/iap` and a Google company-user subject. BigQuery
still supplies the role. Plain proxy email headers, invalid signatures and
wrong-resource assertions fail closed. See `deploy/browser_iap.py` for the
permission-gated, Google-managed browser-login migration; never publish the API.

The default compute runtime identity supplies BigQuery, private-service and RCA
gateway credentials through ADC/metadata. Neo4j/query-embedding credentials are
version-pinned Secret Manager references, not environment files in the image.
The background worker requires always-allocated CPU and a minimum instance to
continue after HTTP requests end; the deployment guide includes pause/resume
commands and the idle-billing implications. No workflow schema initialization, data
replacement, bulk retest or ingestion is part of deployment.

## Quality workflow endpoints

- `GET /api/my/business-taxonomy` — standard domain/subdomain suggestions plus
  saved custom labels in the authenticated caller's feedback scope. Reporters
  cannot enumerate another owner's custom classifications; reviewers can use
  their normal all-feedback scope. This is read-only and does not run inference.

- `GET /api/overview?environment_id={id}` — environment-scoped feedback and latest
  saved-answer/RCA aggregates; omit the ID for distinct-report All environments.
  Golden datasets and untagged legacy evaluations are explicitly agent-wide.
- After a linked promotion, its exact target is the feedback's **main environment**.
  This pointer and an append-only `feedback_events` audit are separate from the
  immutable source report/environment and original answer/RCA history. Reviewer
  inbox and Reporter My feedback show the main target with the original source
  label. Owner history/confirmation use the main exact environment, latest completed
  saved answer and current input revision; a cross-environment result or another
  employee's identity can never satisfy those checks.
- `GET|POST /api/golden-datasets` — list/create datasets.
- `GET|POST /api/golden-datasets/{id}/cases` — list cases or add a candidate.
- `PATCH /api/golden-cases/{id}/state` — approve/reject a candidate.
- `POST /api/feedback/{id}/golden-candidate` — add completed, reviewer-verified feedback to a selected dataset as a candidate.
- `POST /api/evaluations` — queue an evaluation over approved cases.
- `GET /api/evaluations` and `GET /api/evaluations/{id}/cases` — inspect persisted results.
- `POST /api/feedback/{id}/root-cause/suggest` — retrieve Neo4j document evidence and request a Sonnet RCA suggestion.
- `GET /api/evidence/status` — reviewer-only, read-only evidence connectivity/corpus/index diagnostics.

Feedback progresses through `Submitted` → `Triaged` → `Evidence review` →
`Review complete` → `Golden candidate` → `Approved for dataset`. Completing
review requires a non-empty expected behavior and an explicit reviewer
verification flag. The feedback-to-dataset endpoint checks that state and flag,
requires the caller to select a dataset, and prevents adding the same feedback
twice to the same dataset version. Dataset approval remains a separate action;
only approved cases are included in evaluation runs.

### Automatic source-RCA triage progress

A completed, cited, non-inconclusive RCA for the **current source capture** can
advance `Submitted` → `Triaged` even when its confidence still requires human
review. This is processing progress, not acceptance of the diagnosis. AI stays
unverified; no confirmed RCA, verified expectation, completed review, resolution,
golden case or owner-confirmation pointer is assigned automatically.

The suggestion/progress/audit commit is conditional on the exact current input
revision, source answer ID, question and captured answer. It advances only open
Submitted reports in Received/In review, without overriding human decisions or
closed/confirmation/retesting statuses. Selected target-environment RCA and old
captures remain in immutable history without advancing the source workflow.
Failed, unavailable, uncited or insufficient-evidence analyses do not auto-triage.

`scripts/reconcile_rca_triage.py` is an explicit saved-result-only metadata repair:
preview first, then `--apply --approved-preview /private/preview.json
--expected-count N` only for an approved exact selection. It rechecks current
source inputs, latest successful analysis, row fingerprints and the real Google
reviewer grant in one transaction, appends an audit and never calls models or
retries jobs. Native JSON parsing preserves exact Unicode/emoji comparisons; it
does not normalize or rewrite saved answers. This is not a startup migration.

### Submission domain and subdomain

`FeedbackCreate` accepts optional first-class `business_domain` (100 characters)
and `business_subdomain` (300 characters), including custom labels. Exact standard
code aliases are normalized (for example OTC → O2C); other custom names are kept.
Captured question/answer text is not changed by classification normalization.

Provided context is recorded as `user_submitted`, not document-verified, and is
protected from automatic document suggestions. If neither field is supplied, the
existing unverified document-suggestion flow remains available. Authoritative
workbook imports keep their original import path and provenance; neither this
feature nor its dropdown suggestions reclassifies existing reports. Explicitly
cleared/changed current labels do not resurface from immutable legacy metadata.

## On-demand RCA workflow

The default retriever is **Neo4j**, not the former local/GCS BM25 index.
BigQuery remains the workflow system of record. Neo4j is read only from this
application: no ingestion, chunk re-embedding, index creation or graph updates
occur during startup, health checks or RCA.

The adapter uses the existing `vector` (`Chunk.embedding`, cosine, 1,536
dimensions) and `keyword` (`Chunk.text`) indexes. Query embeddings use the same
`text-embedding-3-small` model as ingestion. Bounded, over-fetched vector and
full-text candidates are filtered to completed documents in
`NEO_RCA-VisualAnalysis__`, fused by reciprocal rank and boosted for exact business
codes. Expansion uses only immediate, same-document `NEXT_CHUNK` neighbors and
chunks sharing a bounded number of low-degree entities. It returns stored source
passages, **not entity relationships presented as verified facts**. Retrieved
evidence is independent of what the external agent actually retrieved.

Configure the backend using the `FEEDBACK_NEO4J_*` and
`FEEDBACK_EVIDENCE_EMBEDDING_*` settings in `.env.example`. Supply credentials
directly from backend secrets, or explicitly set `FEEDBACK_NEO4J_ENV_FILE` to an
absolute private credential-file path. The local ignored `.env` reuses the existing
Graph Builder credential file; it does not copy its secrets or expose them to the
browser. Production deployment should use a dedicated read-only Neo4j identity
with permission to inspect indexes and run the vector/full-text procedures. No
production agent access or identity grants are enabled by this integration.

Set `FEEDBACK_NEO4J_SOURCE_MANIFEST` to the ingestion `manifest.json` for exact
original PDF/PPTX/DOCX names, parser origin and parsed-GCS artifact references.
This small file provides **provenance only**; document text is searched in Neo4j,
not loaded into a local text index. When supplied, its document mapping also
restricts retrieval to that release and is checked against the completed graph
corpus. The local deployment uses the manifest at
`/home/dhruv/loreal-neo/llm-graph-builder/output/rca_markdown_gcs_visual_analysis/manifest.json`.
An optional `FEEDBACK_NEO4J_CORPUS_VERSION` pins its computed fingerprint. Without
a manifest, the stored Markdown document identifier is retained as the source;
original filenames and a corpus release are not invented.

Evidence retains original source, ingestion page (unknown stays unknown), graph
document/chunk ID, chunk position, parser/artifact provenance, manifest
fingerprint, exact content offsets and a SHA-256 hash of the consumed chunk.
Parsed-GCS URIs refer to JSON artifacts, not original PDFs. RCA snapshots record
the actual independent evidence backend/version; they do not label the agent's
unknown corpus with an old `parsed-docs-current` default. Query embeddings alone
are cached briefly in a bounded in-memory cache; answers are not cached here.

Connectivity, index shape, model, dimensions and manifest coverage are validated
before retrieval. **No automatic BM25 fallback is used.** Graph/embedding failures
produce `evidence_unavailable`, `insufficient_evidence` and review-required,
unverified output without calling the judge on empty evidence. A normal search
with no passages is separately marked `no_matching_evidence`; neither condition
establishes a corpus-wide source gap. A saved retest answer stays automatically
owner-visible and its assessment becomes inconclusive if evidence is unavailable.
Temporary retrieval failures do not erase existing business-domain suggestions.
Raw passages, graph hints, artifact URIs and worker diagnostics remain private to
reviewers; owner/environment/revision confirmation guards are unchanged.

Read-only validation (no agent generation, judge, ingestion or feedback writes):

```bash
python -m scripts.check_neo4j_evidence
python -m scripts.check_neo4j_evidence --question "How are MM30 and MM40 used?"
```

The authenticated `GET /api/evidence/status` endpoint exposes the same safe
corpus/index diagnostics to reviewers only. `/healthz` remains the lightweight
application/BigQuery check. The legacy parsed-JSON reader remains for explicit
compatibility use (`FEEDBACK_EVIDENCE_BACKEND=bm25`) and tests, never as a failure
fallback. Existing saved answers/RCA are not rewritten when retrieval changes;
new analysis uses the configured evidence backend. No bulk backfill/retest is
started by this configuration.

Sonnet 4.6 suggests a taxonomy label and plain-language subcategory, citing only
returned evidence IDs. Its prompt treats source passages as untrusted data and
does not equate independently retrieved Neo4j evidence with the original agent's
tool trace. If gateway judgment fails, the result remains unverified,
`insufficient_evidence` and review-required.

The service auto-classifies only when confidence is at least 0.85, the result
has a subcategory and cited evidence, Sonnet explicitly marks it as not needing
review, and the category is not one of the always-review categories. This
updates the RCA category/subcategory and marks the result `auto_classified`.
Otherwise, the editable suggested values are shown with `Review recommended`.
Users can run RCA when needed, change either value, and save their own
classification; that is recorded as `reviewer_classified`. Neither path
approves a golden case.

The initial evaluator invokes `NEO_AGENT_API_URL` and checks required-claim text
and expected status. Missing claim matches are marked `review_required`; this is
a transparent lexical baseline, not semantic/model-judge approval. Candidates
are excluded until a reviewer approves them.

An evaluation run requires at least one approved case. The run’s case-level
answers and results are stored in `evaluation_case_results`. Create a new
dataset patch version to snapshot its approved cases before making additional
curation changes.

## Import legacy triage workbooks

```bash
python -m scripts.import_legacy_triage \
  /home/dhruv/neo-list-triage/data/sample_test_cases_triaged.xlsx
```

Legacy spreadsheet records are marked with source metadata and remain in
`Submitted` state until a reviewer confirms them.

## Import CSV feedback exports

The SAP MENA export can be imported idempotently:

```bash
python -m scripts.import_feedback_csv \
  /home/dhruv/Downloads/NEO_NA_SAPMENA_Feedback.csv
```

The importer preserves the original row number, user, domain, status,
expected answer, follow-up, developer remarks, resolution, and language in the
feedback record context. Re-running the command skips rows already imported.

## Replace feedback from an updated XLSX export

`scripts.replace_feedback_xlsx` reads **All Questions** only; language subset and
analysis sheets are not imported again. Preview validates all records before any
removal:

```bash
python -m scripts.replace_feedback_xlsx /path/to/updated.xlsx
```

For an explicitly authorized replacement, quiesce feedback API/workers and run
the same command with `--replace`. It privately backs up the six feedback tables
under `/tmp/opencode`, loads and checks staging tables, then replaces active
feedback/events/original snapshots and clears old RCA/jobs/notifications in a
single transaction. Staging tables expire automatically. An optional
`--backup-dir` selects a private recovery directory. Golden datasets, golden
cases, evaluation runs and evaluation results are untouched. Matching workbook
`No.` values retain their feedback IDs so links remain valid; prior history is
still reset. Updated question text can differ from an existing golden-case
snapshot, which needs separate review rather than automatic modification.

Developer remarks/status notes are reviewer-only. The workbook's question,
generated answer, expected answer, reporter, latency, language and original
status are preserved. Imported Closed/Done statuses do not independently verify
a fix; expected answers and RCA remain unverified. Blank reporters stay
reviewer-only rather than being assigned to a fabricated user. Restore the API
with its full identity configuration afterward and refresh/sign in again to
discard old browser/session caches. A transient systemd unit may disappear when
stopped, so do not assume a bare `systemctl start` can recreate its environment.

## Feedback list filters

- **My feedback (reporter):** search, domain, and public status. Domain choices
  come only from the signed-in user's own submissions, including the private
  existing-feedback scope of a configured development demo account.
- **Feedback inbox (reviewer):** user/reporter, domain, and public status, alongside
  the existing review-state, severity, verdict, and RCA filters.

Filters are combined in BigQuery before counting and pagination. Changing or
clearing a filter returns to page one. Choices cover all authorized submissions,
not just the current page. Public status uses the same values displayed in the
reporter portal; the internal review state remains a separate reviewer filter.

`GET /api/my/feedback/filters` returns owner-scoped domain choices only.
`GET /api/feedback/filters` returns all domain and reporter choices and requires
reviewer access. Both feedback list endpoints accept `domain` and `public_status`;
only the reviewer list accepts a `reporter` filter. Reporter identity is always
taken from the authenticated session, never a query parameter.

Business domain is stored independently from business subdomain and RCA defect
subcategory. Legacy domain prefixes can be recognized from submitted metadata,
but do not count as reviewer-verified evidence. Missing values stay **Unspecified**.
Domain, status, environment and reviewer-only field filters are available from
their table column headers; the search bar is debounced.

## Feedback → retest → user confirmation

The submission form captures a title, exact question, original answer, environment,
optional release/run reference, and feedback. A title is no longer used as the
original question. Domain/subdomain are optional: a persisted enrichment job
retrieves evidence and suggests classification with document/page provenance.
Filename-based classification is explicitly unverified. Conflicting domain
evidence produces **Unspecified**, not a guessed fact. Users/reviewers can confirm
or correct the classification.

Run `python -m scripts.init_bigquery` once to apply additive columns and create:

- `feedback_answer_versions`: original and refreshed answers, append-only IDs.
- `feedback_rca_versions`: diagnosis snapshots tied to an answer version.
- `feedback_workflow_jobs`: persisted enrichment/retest jobs with leases.
- `feedback_notifications`: owner-scoped in-app updates.

Existing answers are copied into original snapshots using idempotent `MERGE`;
their environment remains **unknown** unless it was actually recorded. No feedback
table is dropped. The API's bounded background worker claims jobs with a conditional
DML update, renews leases, and resumes after expired leases on process restart.
An already saved answer is reused when recovering the *same* job; requesting a
new retest makes a fresh agent invocation. Neither original answers nor older RCA
results are overwritten by a retest.

Reviewer endpoints:

- `GET /api/agent-targets` — safe configuration metadata, never endpoint secrets.
- `POST /api/feedback/{id}/analysis` — queue original RCA/domain enrichment.
- `POST /api/feedback/{id}/retests` — `{target_id, idempotency_key}`.
- `GET /api/feedback/{id}/history` — private answer/RCA/job history.

Reporter endpoints:

- `GET /api/my/feedback/{id}/history` — all original/corrected submissions and
  saved retest answers/verdicts for the authenticated owner, automatically.
  Raw retrieval data, worker payloads and reviewer notes are removed.
  `sharingPolicy` is `automatic`; `pendingRetestCount` tracks unfinished checks,
  and `latestConfirmableAttemptId` identifies the latest completed result for
  the current input revision and known original environment.
- `POST /api/my/feedback/{id}/retests/{attempt}/confirmation` — `fixed`,
  `partially_fixed`, or `still_incorrect` and an explanation for non-fixed answers.
  Correcting a recorded response requires its saved value as
  `expected_confirmation`; stale corrections fail atomically and every change is audited.
- `GET /api/my/notifications` and `POST /api/my/notifications/{id}/read`.

A correction assessment is distinct from an RCA diagnosis. **There is no manual
Share/Publish step.** Saved answers become visible to their owner immediately;
the automated verdict and RCA follow as the check finishes. All outcomes are
visible, including **appears fixed**, **still incorrect** and **inconclusive**.
They remain explicitly **AI/unverified**, even when no expected answer has been
reviewed. The original reporter verdict is preserved separately.

Completing a retest atomically saves the comparison, records automatic
availability, creates one in-app notification and adds an audit event. Lease
checks and deterministic notification/event IDs make retries idempotent; only
conditional storage transactions are retried, never generation POSTs. The worker
also reconciles existing completed/failed runs with saved answers after a crash,
without rerunning the agent. Failed assessments do not hide an already saved
answer or invent a verdict. The legacy `published_at`, `published_by` and
`latest_published_attempt_id` column names are retained as availability/current
result metadata; they are no longer a visibility gate. Historical reviewer
explanations are preserved, not overwritten by AI text.

Automatic availability never changes public review/resolution status, expected
answer verification, submitted answers or the user's verdict. Only an explicit
owner response can resolve feedback; the result must be completed and latest for
the same current input and known original environment. These conditions are
rechecked in the confirmation transaction. A non-prod or stale-input result stays
visible as history but cannot resolve a prod/different-input report. A response or
explicit correction records only the reporter's opinion and the corresponding
public status. It never rewrites the saved AI comparison, reasoning, answer or
RCA, and does not enqueue analysis. A reviewer must explicitly request a separate
RCA check when needed. Reporter verdicts are projected per answer from the job's
`confirmation`, independently of the submitted-answer verdict.
The former `/publish` endpoint and request model have been removed. Notifications
stay inside the app; email delivery is not enabled.

This removes per-run manual release work for a future scheduled caller. It does
not create a cron/scheduler or launch a bulk run. A scheduled caller must choose a
server-owned target matching the selected environment and use a stable per-period
idempotency key. Authenticated reviewer access, real backend API credentials and
exact owner/environment/revision confirmation protections remain unchanged.

### Connect the real agent

Configure `FEEDBACK_AGENT_TARGETS_JSON` on the backend. Each target has an ID,
agent ID, environment (`nonprod`/`prod`), full HTTP invocation URL, auth mode and
optional version. `protocol` selects the request/response contract:

- `quality_json` (default) retains the generic JSON adapter below.
- `neo_companion` connects directly to the same Companion generations API used
  by `/home/dhruv/neo-list-triage/src/companion_client.py` and
  `retest_companion.py`. It sends `{"message":"exact submitted question"}`.
  The provider creates a **new conversation** for each independent retest; old
  report conversations and invented session IDs are not sent. The final AI
  message is parsed from `messages[].data.content`, preserving all text blocks.
  A preliminary tool-call message or tool result is never used as the answer.

For the known **non-production** Companion context, use a server-only target:

```json
[
  {
    "id": "neo-nonprod",
    "agent_id": "neo-rules-agent",
    "environment": "nonprod",
    "label": "NEO · Non-production",
    "protocol": "neo_companion",
    "url": "https://api.loreal.net/global/it4it/btdp-genaiengine/v1/contexts/neo_nasapmena-8ec4bd70-np/configs/default/generations",
    "auth": "google_access_token",
    "timeout_seconds": 300
  },
  {"id": "neo-prod", "environment": "prod", "label": "NEO · Production"}
]
```

The local ignored `backend/.env` holds this non-production target. It does not
contain an access token. `google_access_token` refreshes backend Google
application-default credentials with cloud-platform and userinfo.email scopes. The identity
must also have Companion permission; BigQuery access alone does not establish
that permission. No browser authentication token is forwarded upstream. The
older CLI client used the active `gcloud` identity, which can differ from ADC;
check the configured backend identity rather than silently falling back to a
different user. Deployments should use an explicitly authorized service identity.

For a separate Production-only Companion identity, set
`FEEDBACK_NEO_COMPANION_PROD_SERVICE_ACCOUNT` to a server-owned service-account
email. Only the exact `neo-prod` NEO Companion target uses a short-lived
impersonated access token; the API keeps its own runtime identity for BigQuery,
Secret Manager, RCA and every other target. The runtime identity must have
`iam.serviceAccounts.getAccessToken` on the configured target identity. Leave this
setting blank to use normal runtime ADC everywhere. Never put secret values in
source, images or target configuration.

RCA suggestions and saved-answer comparisons use a separate LiteLLM/BTAP
gateway. `BTAP_SERVICE_ACCOUNT` optionally selects an explicit impersonated
identity for **both** assessment calls, without changing Cloud Run, BigQuery,
Secret Manager or NEO target identities. Runtime ADC must be allowed to mint
tokens for it. Tokens are short-lived and cached in process memory for at most
five minutes; a failed mint never switches to another identity or a developer
token. Do not configure this setting together with `BTAP_ACCESS_TOKEN`.

Gateway failures retain the retrieved evidence and require review. Their saved
diagnosis includes a safe failure code and HTTP status when available, and the
rationale distinguishes authentication, permission, quota, timeout and invalid
responses. Logs contain only the operation, fixed failure code and numeric
status, not prompts, evidence, upstream bodies or tokens. Completion requests
are never automatically retried and redirects are not followed. An RCA gateway
failure is not evidence that the underlying source documents are absent.

Companion requests default to a 300-second read timeout (generic targets: 120
seconds); `timeout_seconds` must be an integer from 1 to 600. Authentication,
permission, network, rate-limit, timeout and contract failures are saved as safe,
actionable job errors without exposing upstream bodies or credential details.
Generation POSTs are **not automatically replayed** after failures: a timed-out
request may have run upstream. The advisory idempotency header does not establish
an upstream exactly-once guarantee. Recovery reuses an already persisted answer
for the same job, while an explicitly requested new retest creates a new attempt.

Every response records the actual returned conversation/run references, response
latency, protocol and any supplied release/model/corpus versions; absent versions
stay unknown. Answers are not silently shortened. Bounded, credential-redacted
message/tool diagnostics are saved privately with the answer and rendered lazily
under **Agent diagnostics · reviewer only**. Raw tool text is not fabricated into
document citations; absent structured sources, RCA uses the independent Neo4j
evidence store. Supplied structured source passages retain their separate
`agent_retrieval` origin rather than being relabelled as graph evidence. This
connection does not change Companion's own retrieval backend. Public history exposes the owner's saved responses and
automated verdicts by default while stripping all private traces and raw sources.
An unknown original environment never hides a result, but cannot establish which
environment's report that result would resolve.

The generic `quality_json` invocation contract remains:

```json
{"question":"exact question","conversation_id":"fresh retest session","context":{},"environment":"nonprod"}
```

That adapter expects `{answer, run_id?, agent_version?, model_version?, corpus_version?,
sources?}`. A source may include `source`, `page`, `element_id`/`chunk_id`, and
`context`/`text`/`excerpt`; supplied content is treated as untrusted source evidence.
The browser supplies only a registered target ID, never a URL/token. Non-HTTPS
targets are rejected except explicitly configured loopback development targets;
redirects are not followed. Every environment uses the same authenticated reviewer
permissions; there is no additional Production-only SSO/grant gate. Deployment
authentication and the backend identity's actual upstream API permissions still apply.
Do not reuse the Graph Builder API as the NEO invocation endpoint.

Connecting feedback retests does not run the workbook in bulk, deploy an agent
fix, resolve a report, or change golden datasets/evaluations. The older golden
evaluation adapter still uses `NEO_AGENT_API_URL` separately and stays unconfigured
unless explicitly enabled. Configure and enable the intended saved environment
connection before requesting a run; configuration itself does not grant API access.

### Compact review workspace

The frontend uses a neutral graphite palette in light and dark modes. In the
reviewer detail view, **RCA assessment** starts alongside the submitted context
(and comes first on narrow screens), rather than below the business/history
panels and full answer. Long answers have a bounded, keyboard-scrollable preview
and **See more / Show less** controls; expansion is still bounded and never
truncates the saved content. The same preview is used for version comparisons
and reporter details.

The reviewer **Submission** card combines the question, captured response, verdict
and expandable **Feedback & metadata**; no second submission-details card is
rendered. A shared verdict badge handles all values, including Correct, blank and
future values, rather than leaving cells empty. Imported context/notes stay inside
the reviewer-only metadata area; dates are formatted for reading.

The main **RCA assessment** and **Evidence & citations** panels now follow the
selected saved answer, including an already-completed retest loaded on page open.
An **Assessment version** selector distinguishes the editable submitted-response
review from immutable retest/corrected-capture diagnoses. Category, defect,
rationale and source passages come from that answer's saved RCA, not from the
original feedback row. Saved diagnosis fields are read-only and explicitly
AI/unverified; saving feedback review fields never copies a retest category onto
the original submission. Manual original-review drafts survive version switching.

Reviewer history retains typed private evidence/provenance from the history API.
Only citations actually supplied with a diagnosis become clickable controls;
selecting one opens/focuses its matching source passage. The evidence tabs show
the full saved context window, original document/page references and graph
chunk/retrieval/manifest provenance, without mixing evidence from other answer
versions or relabelling it as the external agent's trace. Empty/processing/
unavailable assessments have distinct messages. Reporter history still strips
private sources and renders no evidence/diagnostic controls. Existing records need
only a refresh to display saved retest sources; no agent/judge rerun is required.

Polling detects newly saved diagnoses as well as answers/job completion. Queuing
submitted-response RCA refreshes that history even while its disclosure is
closed, so a fast completed analysis does not leave the main classification stale.
The frontend regression suite runs with `npm test` (Node's test runner and the
existing `tsx` dependency); backend ownership/version guards are unchanged.

**Expand comparison** opens a read-only, same-page dialog for original versus
selected answer versions. Desktop panes scroll independently; mobile uses an
original/updated switcher. The dialog keeps environment/revision and sharing
labels visible, traps keyboard focus, closes with Escape, restores the original
view/focus, and only renders the versions authorized by that history endpoint.
It never invokes the agent, publishes, or renders raw tool traces.

Business context, answer history, source evidence, submission metadata, workflow,
reviewer notes, public updates and claim verification use accessible disclosures.
Closed sections skip their first expensive render; after being opened they stay
mounted so closing a section does not discard draft edits. History metadata/job
polling remains active for visible reporter details/active jobs while collapsed, and an answer requiring owner confirmation
opens automatically. Source provenance, private notes and publication/confirmation
guards still prevent cross-owner, cross-environment or stale resolutions. Secondary state-change actions are under Review workflow;
Save changes and the next lifecycle action remain in the fixed action bar.

Retest responses and their automated verdicts are visible in both roles without
a sharing form, review checkbox, public explanation or manual release action.
History refreshes as an answer/assessment arrives. Opening an expanded comparison
pins the selected version so a scheduled update does not replace what is being
read. A mismatched/unknown environment or older input is labelled historical,
not hidden. Private diagnostics remain reviewer-only. Owner confirmation is
optional and distinct from an AI verdict; no model recommendation resolves a
report. Manual history refresh bypasses read caches.

History keeps the original plus the most recent 99 other answer versions, recent
diagnoses, and their associated job summaries, rather than silently returning the
oldest 100 once scheduled runs accumulate. All immutable versions remain stored.

The overview uses one neutral metric rail, restrained status/chart colours,
compact data-backed summaries and small empty states instead of large empty
chart boxes. No fake trend is drawn from a single imported feedback date. Its
Refresh action bypasses both client and server read caches without invoking the
agent. The sidebar count uses the overview total rather than a filtered inbox
count, and narrow screens have a separate horizontal workspace navigation.

### Caching and latency

BigQuery clients and their credential/connection pools are reused per process.
Read caching is bounded, short-lived, and keyed by authenticated email, role,
effective ownership scope, route and filters (including environment). Authentication
runs before every hit. Writes/background completion invalidate the cache; history
and notification reads have shorter TTLs. Responses remain `private, no-store` for
HTTP intermediaries. The frontend caches/deduplicates reads by signed-in scope,
clears on sign-out/writes, and debounces search. Reporter lists omit full answers
and timelines; details/history load on demand. Actual fresh agent invocations are
not served from a read cache. For multiple API processes, cache TTL bounds external
worker staleness; a distributed invalidation/cache layer can be added on deployment.

## Shared feedback portal and development sign-in

The public-facing **My feedback** page uses the same BigQuery feedback records,
but its API is scoped to the authenticated identity. The browser cannot choose
the reporter identity: `POST /api/my/feedback` replaces any submitted reporter
value with the verified API identity. Reporter tokens can only list, open, and
edit their own records; reviewer APIs require the reviewer role. Submitters can
edit their title, feedback, expected answer, verdict, categories, and impact
while review is open. Editing an expected answer clears its verification flag;
editing during evidence review returns the case to triage. Closed/resolved
records are read-only.

Public responses include the submitter's question, agent answer, verdict,
expected answer, categories, impact, legacy submission context, public status,
and any reviewer-confirmed cause or resolution. A preliminary AI cause and its
rationale may be shown only with an explicit **not verified** label. Reviewer
notes and raw evidence payloads remain private.

Reporter list/detail responses include a small owner-scoped `answerReview`
summary. A page is checked with one batched read, not one full history request per
row. The current exact main environment, input revision, completed retest and
nonempty saved answer determine review eligibility; a successful AI verdict is
not required. RCA-only jobs do not create an answer eligible for confirmation.
History includes its own fresh review context so an older detail snapshot cannot
hide an otherwise eligible answer. The confirmation transaction still rechecks
ownership, exact environment/revision, latest completed result and prior response.

**Your verdict** in My feedback is a keyboard-accessible entry point to this
updated-answer review, not a mutation of the original submitted verdict. It forces
a fresh read, selects the eligible answer, and opens **Correct / Partially correct /
Incorrect**. Available updates appear automatically; the visible list refreshes
every 30 seconds and on focus/visibility return. A selected older environment is
not silently replaced: its update banner provides an explicit path to review the
main target without changing the table filter. Unavailable reviews explain why.
Recorded responses are displayed with an explicit **Change your verdict for this
answer** action for the latest eligible answer only. Passive 10-second history
polls keep verdict controls enabled and preserve typed comments; deliberate
refreshes and mutations have their own loading state. Historical-answer warnings
state both the saved answer's input revision and the current submission revision.

Reporter answer notifications live in the global header bell, with an unread
badge and a bounded, keyboard-accessible dropdown; there is no notification card
above My feedback. Updates continue polling every 30 seconds. Selecting an update
marks only that notification read and opens its owned feedback with answer history
expanded, even if the record is outside the current table page or filters.
Opening/closing the bell does not mark anything read. The dropdown supports read
history, refresh, loading/empty/error states and mobile layouts. Late cancelled
navigation and prior-session responses cannot open a different user's record.

Reporter editing uses a focused full-screen form rather than mixing fields with
the history/RCA/status detail panel. The editable allowlist covers title, question,
submitted/captured agent response, expected answer, feedback, verdict, categories,
impact, business domain/subdomain, environment, agent/release/run/conversation
references, data source, language and follow-up. It never accepts ownership,
reviewer notes, resolution/status decisions or verified RCA from the browser.
Closed/review-locked records remain read-only. The client pins the loaded input
revision and `updatedAt` (`expected_revision` / `expected_updated_at`); stale saves
and records closed during editing are rejected server-side. Metadata-only writes
require the loaded edit timestamp and use a transactional timestamp check, so
two same-revision edits cannot silently overwrite one another.

Normalized, actual changes to the question, captured response, expectations,
substantive feedback/follow-up, exact environment, agent/release/run/conversation
references, data source or language create an input revision. They atomically
insert an immutable `submission_edit` capture, audit event and enrichment job,
and invalidate the current verification/latest-result pointer. There is still
one input/assessment revision counter; existing revisions are not renumbered.

A submitted-verdict, title, impact, category or business-label correction is
audited without creating a revision/capture/job or clearing saved RCA, comparison
or result pointers. Unchanged values are no-ops. Submitted-verdict corrections
overlay only the current capture through `run_context_json.answer_user_verdicts`;
immutable snapshots remain intact, and missing historical verdicts are not
inferred from a later opinion. The first original capture and actual retest
responses are never overwritten. RCA remains tied to its exact answer version.
The reporter table shares top scrolling/pinned actions with the reviewer inbox,
and Submit feedback remains only in the global header.

For local development, `FEEDBACK_AUTH_MODE=mock` enables a test-user picker
(two reporter accounts and one reviewer account, all under `example.test`).
The UI clearly labels this as a development preview. Mock auth refuses to start
in production or Cloud Run; do not expose the mock login to company users. The
mock token signing key is ephemeral if `FEEDBACK_AUTH_SECRET` is unset, so a
backend restart requires signing in again. Company SSO should replace this
provider before broad sharing; reporter scoping and the API contracts can stay
the same.

Reviewer updates have a separate public status (`Received`, `In review`,
`Needs information`, `Resolved`, `Not planned`, or `Duplicate`). Marking an
item `Resolved` requires a user-facing resolution summary; an optional release
or build identifier can also be recorded. These safe status changes are written
to `feedback_events` as `public_status_updated` events, while the complete
reviewer event payload remains unavailable to reporter APIs.

The additive public-status columns are applied by the existing
`POST /api/admin/bigquery/init` schema initialization endpoint. Run it once with
a reviewer identity after deploying the updated backend. The public portal
then reads existing feedback owned by that email as well as newly submitted
feedback.
## Environment settings and bulk promotion

`python -m scripts.init_agent_environments` upgrades existing storage additively.
It seeds existing `FEEDBACK_AGENT_TARGETS_JSON` targets once; subsequent settings
edits are persisted in BigQuery rather than replaced from environment variables.
No agent call, feedback backfill or worker enablement is performed by migration.

Reviewer APIs:

- `GET/POST /api/agent-environments`, `PATCH /api/agent-environments/{id}`.
- `POST /api/agent-environments/{id}/test`: one explicit sample response request
  against a saved configuration revision, with an idempotency key.
- `GET /api/agent-environments/{id}/tests/{test_id}`: read an existing diagnostic
  result without invoking the endpoint again.
- `POST /api/promotions/preview`: explicit IDs or an all-matching filter snapshot.
- `POST /api/promotions`: target ID, preview token and idempotency key; atomically
  enqueues a bounded batch after rechecking revisions and target configuration.
- `GET /api/promotions`, `GET /api/promotions/{id}`, and
  `POST /api/promotions/{id}/cancel` (requester only, queued jobs only).
- `POST /api/feedback/{id}/answer-rca`: answer-scoped RCA-only recheck.

`GET /api/my/agent-environments` returns names/types/capabilities, never URLs or
authentication settings. Both feedback list APIs accept `environment_id` to
include original and promoted membership; ownership filtering remains mandatory.
All existing legacy kind filters (`nonprod/prod/unknown`) remain supported.
Known kind filters match the original source or a linked retest's immutable target
kind, including queued/failed attempts; a link does not imply a successful answer.
`unknown` instead means the original source was not recorded. Neither filter
rewrites the report's source fields, ID, owner or history. Count and page queries
share the same membership predicate, with a stable feedback-ID ordering tie-breaker.

The inbox Environment selector shares the header's exact named-environment ID,
clears the legacy kind predicate when choosing a named view, and resets pagination
and selection. DEV/UAT are not merged merely because both have kind `nonprod`;
disabled environments remain available for historical browsing. A linked row shows
its selected context separately from its original reported environment. Scoped RCA
uses only the exact matching attempt, or the original RCA in its exact native source
view when no scoped attempt exists. All environments counts each feedback ID once,
so overlapping source/linked environment counts must not be added as unique reports.

New endpoints must be HTTPS, on `FEEDBACK_AGENT_ALLOWED_HOSTS` (or an already
operator-configured target host), without credentials, query strings, fragments,
IP addresses or nonstandard remote ports. Local unprivileged test ports are
allowed only outside Cloud Run in explicit development/local/test mode. Redirects
are not followed. NEO Companion uses runtime Google OAuth; no personal token is
accepted by the settings API. Production context/type mismatches are rejected.

Each job freezes the approved target configuration and source baseline. An
environment disabled before execution blocks queued calls. A durable generation
marker prevents automatic POST replay after interruption; saved answers can
resume evidence/RCA checks. Source feedback, ownership, original snapshots and
saved diagnoses are never rewritten by promotion. Confirmation compares named
environment IDs in addition to the current revision and known legacy kind.

Named origins/results retain their canonical kind and ID in versioned context or
target snapshots. For custom environments the old kind-only storage column is
deliberately `unknown`, so an older deployed API sharing this dataset cannot
mistake UAT for the legacy non-production origin during confirmation. Updated
APIs/UI return the canonical kind/name. Imported unknown origins remain unknown
unless explicitly confirmed by the user; no historical source is guessed. Use the updated UI for named
environment management and confirmation.

### Environment settings and explicit endpoint tests

Reviewers can create/edit, enable/disable and test saved environment connections
using the same settings permissions for Production and Non-production. There is no
extra Production SSO check, grant or confirmation checkbox for endpoint testing.
Environment type cannot be changed in place; optimistic revision checks still
prevent overwriting a configuration that changed concurrently. The existing
feedback-retest/bulk-execution paths now use the same reviewer authorization for
all environment kinds as well. Disabled/unconfigured targets, disabled workers,
unapproved URLs and reporter dispatch are still rejected. The legacy
`FEEDBACK_PROD_RETEST_REVIEWERS` variable is ignored; it does not grant or deny runs.

**Test endpoint** opens a confirmation dialog; opening it or saving a connection
does not call the agent. Sending the sample uses the same saved adapter and backend
runtime credentials as a retest, not browser credentials. Any saved environment
may be tested while disabled and without enabling the workflow worker. Clicking
**Send one test request** is the same explicit action for every environment.

The upstream response timeout is capped at 60 seconds. Only a completed, non-empty
answer is success: HTTP 200 containing a tool call or malformed response is not.
Results include HTTP status when available, elapsed time, a bounded/redacted answer
preview or safe error reason, test ID, configuration revision and available runtime
identity metadata. Raw upstream errors, headers, credentials and traces are not
returned. The sample question is not stored; only its hash supports key validation.

`agent_endpoint_tests` stores a durable reservation before invocation and its safe
result afterward. Retries of the same key read that attempt instead of generating
again, including after a configuration edit. Interrupted outcomes remain unknown;
no automatic generation retry occurs. Current-revision last tests are displayed
only for the same local host or Cloud Run service/revision, so local credentials
cannot be presented as proof of deployed-runtime access. Tests do not create
feedback, workflow jobs, notifications, RCA or resolution, nor activate anything.

### Environment-specific overview

Header selection scopes the overview API, frontend cache keys and latest-answer
RCA/comparison queries. Late responses from a previous environment or signed-out
session cannot replace the current dashboard. A promoted case appears in its source
and target views but counts only once in **All environments**. For example, 156
source reports plus 20 linked UAT checks are 156 distinct reports, not 176.

Quality metrics use the latest saved answer for each case/environment and current
input revision, then that answer's latest diagnosis. Missing target RCA never falls
back to an older/source answer. Retest attempts/progress and unverified automated
comparisons are separate from the submitter's verdict and original report workflow.
Incoming promotions do not count as new source submissions. Golden datasets and
untagged legacy evaluations remain explicitly labelled **agent-wide**.

### Explicit source-environment correction (not promotion)

On 23 October the user confirmed that all **156 existing reports** originated in
**Non-production (`neo-nonprod`)**. A backed-up, audited correction changed current
source metadata only; immutable answer/RCA captures, ownership, review state and
golden/evaluation data were preserved. No calls or jobs were started. This does not
authorize automatically relabelling future unknown imports.

`python -m scripts.assign_feedback_environment` previews the metadata-only operation.
`--apply` requires explicit authorization. It rejects a conflicting known origin,
guards revisions/previous context transactionally, writes a private metadata backup
under `/tmp/opencode` and appends `source_environment_confirmed` audit events. It
does not use promotion, regenerate answers, rerun RCA or resolve reports.

`FEEDBACK_PROMOTION_BATCH_LIMIT` defaults to 500 (hard maximum 500); oversized
query-parameter payloads are rejected before dispatch. All environment execution
uses the same authenticated reviewer role, enabled connection/worker and real
backend API access. Creating a configuration
or having a readable endpoint is not verification of inference permission.
Duplicate confirmations return the existing batch; a separate confirmation with
overlapping queued/running target/input checks is rejected. Configuration and
input conflicts return safe, actionable errors without retrying generation.
