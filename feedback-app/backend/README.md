# Agent Quality Console API

FastAPI backend for feedback capture and triage persistence in BigQuery.

## Setup

```bash
cd /home/dhruv/feedback-app/backend
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

## Quality workflow endpoints

- `GET /api/overview` — current feedback, golden-case, and latest-evaluation aggregates.
- `GET|POST /api/golden-datasets` — list/create datasets.
- `GET|POST /api/golden-datasets/{id}/cases` — list cases or add a candidate.
- `PATCH /api/golden-cases/{id}/state` — approve/reject a candidate.
- `POST /api/feedback/{id}/golden-candidate` — create a reviewer-curated candidate from feedback.
- `POST /api/evaluations` — queue an evaluation over approved cases.
- `GET /api/evaluations` and `GET /api/evaluations/{id}/cases` — inspect persisted results.

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
