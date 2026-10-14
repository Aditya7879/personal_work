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

Vite proxies `/api` and `/healthz` to `http://localhost:8001`. Set
`VITE_API_URL` when the API is hosted at another origin.

## Current scope

Connected:

- feedback submission;
- BigQuery-backed feedback inbox;
- feedback detail records;
- triage state/RCA updates;
- append-only feedback audit events.

Golden datasets, evaluation runs, release comparisons, and overview metrics are
shown as not connected until their API repositories are implemented. No fake
metrics or mock feedback are rendered in the live application.
