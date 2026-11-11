"""Evidence-only domain backfill. Preview by default; --apply uses a guarded MERGE."""
from __future__ import annotations

import argparse
import json
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from google.cloud import bigquery

from app.bigquery import BigQueryRepository
from app.business_domain import infer_business_domain
from app.config import settings
from app.document_evidence import get_document_evidence_index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repo = BigQueryRepository()
    candidates = repo.workflow_query(f"""SELECT feedback_id, question, ground_truth_hint, run_context_json,
        business_subdomain, COALESCE(revision, 1) AS revision FROM `{repo.feedback_ref}`
        WHERE NOT COALESCE(domain_verified, FALSE) AND COALESCE(domain_source, '') != 'workbook_import'
            AND (business_domain IS NULL OR business_domain = 'Unspecified')""")
    index = get_document_evidence_index()
    rows = []
    for record in candidates:
        evidence = index.search(str(record.get("question") or ""), str(record.get("ground_truth_hint") or ""))
        suggestion = infer_business_domain(str(record.get("question") or ""), evidence)
        legacy = repo._json_object(record.get("run_context_json"))
        rows.append({"feedback_id": record["feedback_id"], "revision": record["revision"],
                     "domain": suggestion["domain"], "subdomain": record.get("business_subdomain") or legacy.get("sub_domain") or suggestion["subdomain"],
                     "source": suggestion["source"],
                     "confidence": suggestion["confidence"], "reason": suggestion["reason"],
                     "evidence_json": json.dumps(suggestion["evidence"])})
    print("Candidate feedback records:", len(rows))
    print("Evidence elements available:", len(index.records))
    print("Suggested business domains:", dict(Counter(row["domain"] for row in rows)))
    if not args.apply or not rows:
        print("Preview only; no feedback metadata changed.")
        return
    table_ref = f"{repo.dataset_ref}._domain_backfill_{uuid.uuid4().hex[:12]}"
    schema = [bigquery.SchemaField("feedback_id", "STRING"), bigquery.SchemaField("revision", "INT64"),
              bigquery.SchemaField("domain", "STRING"), bigquery.SchemaField("subdomain", "STRING"),
              bigquery.SchemaField("confidence", "FLOAT64"), bigquery.SchemaField("reason", "STRING"),
              bigquery.SchemaField("source", "STRING"),
              bigquery.SchemaField("evidence_json", "STRING")]
    table = bigquery.Table(table_ref, schema=schema)
    table.expires = datetime.now(timezone.utc) + timedelta(hours=1)
    repo.client.create_table(table)
    repo.client.load_table_from_json(rows, table_ref, job_config=bigquery.LoadJobConfig(schema=schema), location=settings.location).result()
    job = repo.client.query(f"""MERGE `{repo.feedback_ref}` f USING `{table_ref}` s ON f.feedback_id = s.feedback_id
        WHEN MATCHED AND NOT COALESCE(f.domain_verified, FALSE) AND COALESCE(f.domain_source, '') != 'workbook_import' AND COALESCE(f.revision, 1) = s.revision
        THEN UPDATE SET business_domain = s.domain, business_subdomain = s.subdomain,
            domain_source = s.source, domain_confidence = s.confidence, domain_reason = s.reason,
            domain_evidence_json = s.evidence_json, updated_at = CURRENT_TIMESTAMP()""", location=settings.location)
    job.result()
    print("Updated metadata only:", job.num_dml_affected_rows)
    print("Original question/answer snapshots, ownership, environment and verification were not changed.")


if __name__ == "__main__":
    main()
