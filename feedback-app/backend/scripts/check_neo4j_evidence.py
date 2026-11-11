"""Read-only evidence health/search check; never ingest, re-embed, or save RCA."""
from __future__ import annotations

import argparse
import json

from app.config import settings
from app.neo4j_evidence import EvidenceRetrievalError, Neo4jEvidenceRetriever


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", help="Optional single source search; no agent/judge invocation or feedback writes")
    args = parser.parse_args()
    retriever = None
    try:
        retriever = Neo4jEvidenceRetriever.from_settings(settings)
        print(json.dumps(retriever.stats(), indent=2))
        if args.question:
            hits = retriever.search(args.question)
            print(json.dumps({"results": [{key: hit[key] for key in (
                "evidence_id", "source", "page", "document_id", "chunk_id", "retrieval_methods",
                "corpus_version", "chunk_content_sha256")} for hit in hits]}, indent=2, ensure_ascii=False))
    except EvidenceRetrievalError as exc:
        parser.exit(1, str(exc) + "\n")
    finally:
        if retriever:
            retriever.close()


if __name__ == "__main__":
    main()
