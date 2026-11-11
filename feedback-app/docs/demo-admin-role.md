# Demo Admin in the existing feedback app

**Demo Admin is a BigQuery application role (`demo_admin`), not a GCP IAM role.**
It uses the existing deployed URL, Google/IAP login, private API and runtime
identities. There is no separate password login, public demo service or demo
authentication build mode.

## Using demo views

1. Sign in to the normal feedback app with an active Demo Admin grant.
2. The real workspace retains the current Reviewer permissions. Select
   **Switch demo view**, then **Alex Reporter**, **Sam Reporter** or **Demo Reviewer**.
3. Use the normal submission, review, saved-answer/RCA, linked promotion and
   owner-confirmation screens. The persistent banner labels **sample data** and
   **simulated AI**. No real employee is impersonated.
4. **Switch demo view** changes only the fictional persona. **Exit demo** restores
   the actual Google account and its current application permissions without
   signing out of IAP. Unsaved drafts require confirmation before leaving.
5. **Reset demo data** explicitly resets the shared sample workflow to three
   fictional reports. It never resets live feedback, grants or audit history.

Ordinary Reviewers retain their existing rights but do not get demo switching.
People & access can explicitly assign Demo Admin to another company account;
the normal prohibition on changing your own grant remains in place. The initial
explicitly requested grant is for `dhruv.chawla@loreal.com` only.

## Isolation and authentication

- The stored application role is separate from the effective workflow role.
  `demo_admin` maps to effective `reviewer`, plus `accessRole` and
  `canSwitchDemoViews` capability metadata. Existing Reporter/Reviewer checks
  continue to enforce workflow permissions.
- The API verifies the real Google/IAP principal first. Demo selection and reset
  require a fresh `demo_admin` grant in the **live** `application_access_grants`
  table, never a demo grant, browser role claim or owner alias.
- A purpose-separated HMAC cookie (`neo_role_demo`) is bound to the verified
  primary actor and an allowlisted fictional persona. It has a nonce and a
  30-minute expiry, with HttpOnly, SameSite=Strict and Secure on HTTPS.
- Every demo data request also carries `X-Feedback-Demo-View: 1`. Missing,
  expired, forged or wrong-actor cookies fail closed. Requests marked as demo
  never fall back to the real Reviewer's live storage. An unmarked data request
  carrying a demo cookie is also rejected until the user explicitly exits.
- Only after verifying IAP does the frontend proxy forward the one role cookie,
  marker and action headers. IAP/provider/legacy cookies and caller role, identity
  or workload headers are not forwarded. Only the role cookie may be returned.
- All mutations keep exact-Origin and CSRF/action-header checks. Switching views
  does not add a new authentication mode or return credentials to JavaScript.
  Browser storage contains only UI identity/cache state. Each tab pins its
  workspace identity so another tab exiting demo cannot redirect a stale form
  into live writes.
- The repository/provider scope is a request-local `ContextVar`, not a mutation
  of global settings. Sample data uses only `agent_quality_demo`; concurrent live
  requests keep `agent_quality`. Authorization remains live in both contexts.
- NEO is still the only agent. Demo responses, evidence, comparisons and RCA are
  clearly labelled fixtures. No NEO, LiteLLM, graph, embedding or evaluation call
  is made. Real connection/schema/evaluation execution and real People & access
  are unavailable inside demo views.
- Publishing a simulated result never resolves a report or changes its public
  review status automatically. The original reporter's explicit confirmation,
  current revision, latest result and exact named-environment guards still apply.

## Promoted records: main environment and owner confirmation

- An explicit linked promotion records its exact target ID as the feedback's
  **main environment** in a separate `feedback_main_environments` pointer. The
  original `feedback_items.environment`, source `run_context_json`, original
  answer, RCA and all prior environments remain unchanged.
- All-environment reviewer inbox and Reporter **My feedback** display the current
  main target prominently and retain a source label (for example **Production ·
  promoted; originally reported in Non-production**). Selecting an explicit
  environment still scopes its own exact named answer/RCA history.
- The reporter detail opens on the promoted main environment by default. This is
  also the environment used for the owner's current-result/revision/confirmation
  checks. The Reporter sees **Correct / Partially correct / Incorrect** only for
  a saved, completed latest result for that current exact environment and revision.
  A promoted answer cannot overwrite the original capture or bypass owner access.
- Historical promoted records are populated from the latest explicit promotion
  batch, with one append-only `feedback_events` audit per pointer. No agent/job is
  rerun and no feedback, original answer or RCA row is rewritten. The backfill is
  reviewable, serialized, hash-fenced and not automatically replayed.

The original development-only mock picker and private local owner mapping remain
separate and must never be copied into the hosted demo dataset or build context.

## Deployment and initial assignment

The existing API/UI retain IAP, invoker checks, private API IAM, runtime/build
identity, scaling, pinned secret bindings and `FEEDBACK_WORKER_ENABLED=false`.
Demo actions process only their simulated sample jobs synchronously. No new
project Job User or service-account grant is needed. If the existing API runtime
lacks sample storage access, grant only dataset-scoped WRITER on the newly
created `agent_quality_demo` dataset, not project IAM or live dataset access.

The reviewed new runtime flags are limited to:

- API and UI: `FEEDBACK_ROLE_DEMO_ENABLED=true`.
- API: `FEEDBACK_DEMO_FRONTEND_ORIGIN=<the existing hosted UI origin>`.

Use the feature-aware `deploy/role_demo.py`, not the strict image-only updater or
the retired standalone-demo recipe. It checks all other runtime/IAM/IAP/secret
settings and live table fingerprints before/after deployment. Build contexts use
the existing metadata-only corpus manifest, never credentials, workbooks or owner
maps. Backend/frontend/context-isolation tests and integrated browser checks must
pass first.

`scripts/prepare_role_demo.py` prepares only the sample tenant and disables the
exact reviewed password-prototype accounts/sessions. The obsolete password
modules, frontend login and separate-service deployment recipe are retired; the
two unused prototype identities need no new role and are not deployed.

Only after compatible code is deployed, the narrowly scoped
`scripts/bootstrap_demo_admin.py` may apply the explicitly approved first
Reviewer → Demo Admin transition. It must preserve every other grant and all
display/active/expiry fields, serialize against access changes, and append one
normal access audit with explicit bootstrap provenance. This does not weaken the
People & access self-role safeguard. Never rerun the completed ownership migration,
ingestion, pilot jobs, evaluations or group onboarding as part of this feature.
