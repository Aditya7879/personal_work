"""Evidence-retriever factory and explicitly opt-in legacy parsed-JSON reader.

The index follows the evidence_eval.py approach from neo-list-triage: one
record per parsed element, preferring VLM output, retaining source/page/element
provenance, with BM25 ranking and an exact business-code boost. VLM JSON can be
loaded from GCS; fast-parser JSON can be loaded from a separate GCS prefix or
from an optional local fallback. This reader is retained for offline migration
tools/tests. The running app defaults to Neo4j and never falls back here on an
unavailable graph or embedding service.
"""

from __future__ import annotations

import html
import io
import json
import math
import re
import tarfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

from google.cloud import storage

from .config import settings
from .demo_context import is_demo


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _codes(text: str) -> set[str]:
    return {
        code.upper()
        for code in re.findall(r"\b[A-Za-z]+[A-Za-z0-9_-]*\d+[A-Za-z0-9_-]*\b", text)
    }


class DocumentEvidenceIndex:
    backend_name = "bm25"

    def __init__(
        self,
        fast_dir: str,
        vlm_dir: str,
        vlm_gcs_uri: str = "",
        fast_gcs_uri: str = "",
    ) -> None:
        self.records: list[dict[str, str]] = []
        if vlm_gcs_uri:
            self._load_gcs_uri(vlm_gcs_uri, origin="vlm", collection="VLM")
        elif vlm_dir:
            self._load_dir(Path(vlm_dir), origin="vlm")
        vlm_sources = {record["source"] for record in self.records}
        if fast_gcs_uri:
            self._load_gcs_uri(
                fast_gcs_uri,
                origin="fast",
                collection="fast-parser",
                excluded_sources=vlm_sources,
            )
        elif fast_dir:
            self._load_dir(Path(fast_dir), origin="fast", excluded_sources=vlm_sources)
        unique: dict[tuple[str, str, str, str], dict[str, str]] = {}
        for record in self.records:
            key = (record["source"], record["page"], record["element_id"], record["text"])
            unique[key] = record
        self.records = list(unique.values())
        self.documents = [_tokens(record["text"]) for record in self.records]
        self.document_codes = [_codes(record["text"]) for record in self.records]
        self.term_frequencies = [Counter(document) for document in self.documents]
        self.doc_freq: Counter[str] = Counter()
        self.doc_lengths = [len(doc) for doc in self.documents]
        for document in self.documents:
            self.doc_freq.update(set(document))
        self.average_length = sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 0.0

    def _load_dir(self, directory: Path, *, origin: str, excluded_sources: set[str] | None = None) -> None:
        if not directory.is_dir():
            return
        for path in directory.glob("*_raw.json"):
            try:
                elements = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            self._append_elements(
                elements,
                fallback_source=path.name.removesuffix("_raw.json"),
                origin=origin,
                excluded_sources=excluded_sources,
            )

    def _load_gcs_uri(
        self,
        uri: str,
        *,
        origin: str,
        collection: str,
        excluded_sources: set[str] | None = None,
    ) -> None:
        if not uri.startswith("gs://"):
            raise ValueError("Parsed-document GCS URIs must start with gs://")
        bucket_and_prefix = uri[5:]
        bucket_name, separator, prefix = bucket_and_prefix.partition("/")
        if not bucket_name:
            raise ValueError("Parsed-document GCS URI is missing a bucket name")
        prefix = f"{prefix.rstrip('/')}/" if separator and prefix else ""

        client = storage.Client(project=settings.project_id)
        bucket = client.bucket(bucket_name)
        bundle_name = f"{prefix}_raw_bundle.tar.gz"
        bundle = bucket.blob(bundle_name)
        if bundle.exists(client=client):
            self._load_gcs_bundle(
                bundle.download_as_bytes(),
                bundle_name=bundle_name,
                origin=origin,
                collection=collection,
                excluded_sources=excluded_sources,
            )
            return

        blobs = [
            blob for blob in client.list_blobs(bucket_name, prefix=prefix)
            if blob.name.endswith("_raw.json")
        ]
        if not blobs:
            raise RuntimeError(f"No parsed {collection} *_raw.json objects found under {uri}")

        def read_blob(blob: Any) -> tuple[Any, Any]:
            try:
                return blob, json.loads(blob.download_as_bytes())
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Could not read parsed document object {blob.name}") from exc

        # Object downloads are latency-bound. Bounded parallel reads keep the
        # first index build from paying one network round trip per document.
        with ThreadPoolExecutor(max_workers=min(16, len(blobs))) as executor:
            loaded_blobs = list(executor.map(read_blob, blobs))

        for blob, elements in loaded_blobs:
            fallback_source = Path(blob.name).name.removesuffix("_raw.json")
            self._append_elements(
                elements,
                fallback_source=fallback_source,
                origin=origin,
                excluded_sources=excluded_sources,
            )

    def _load_gcs_bundle(
        self,
        archive_bytes: bytes,
        *,
        bundle_name: str,
        origin: str,
        collection: str,
        excluded_sources: set[str] | None = None,
    ) -> None:
        try:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
                members = [member for member in archive.getmembers() if member.isfile() and member.name.endswith("_raw.json")]
                if not members:
                    raise RuntimeError(f"No parsed {collection} *_raw.json entries in {bundle_name}")
                for member in members:
                    stream = archive.extractfile(member)
                    if stream is None:
                        continue
                    try:
                        elements = json.load(stream)
                    except (OSError, json.JSONDecodeError) as exc:
                        raise RuntimeError(f"Could not read {member.name} from {bundle_name}") from exc
                    self._append_elements(
                        elements,
                        fallback_source=Path(member.name).name.removesuffix("_raw.json"),
                        origin=origin,
                        excluded_sources=excluded_sources,
                    )
        except tarfile.TarError as exc:
            raise RuntimeError(f"Could not open parsed document bundle {bundle_name}") from exc

    def _append_elements(
        self,
        elements: Any,
        *,
        fallback_source: str,
        origin: str,
        excluded_sources: set[str] | None = None,
    ) -> None:
        if not isinstance(elements, list):
            return
        source = next((
            str((element.get("metadata") or {}).get("filename"))
            for element in elements
            if isinstance(element, dict) and (element.get("metadata") or {}).get("filename")
        ), fallback_source)
        if excluded_sources and source in excluded_sources:
            return
        for element in elements:
            if not isinstance(element, dict):
                continue
            metadata = element.get("metadata") or {}
            text = _clean_text(element.get("text", ""))
            table_html = _clean_text(metadata.get("text_as_html", ""))
            if table_html and table_html not in text:
                text = f"{text}\n{table_html}".strip()
            if not text:
                continue
            self.records.append({
                "source": source,
                "page": str(metadata.get("page_number", "")),
                "element_id": str(element.get("element_id", "")),
                "element_type": str(element.get("type", "")),
                "text": text,
                "origin": origin,
            })

    def search(self, query: str, expected: str = "", limit: int = 8) -> list[dict[str, Any]]:
        if not self.records:
            return []
        query_text = f"{query}\n{expected}"
        query_tokens = _tokens(query_text)
        if not query_tokens:
            return []
        query_codes = _codes(query_text)
        count = len(self.records)
        k1 = 1.5
        b = 0.75
        ranked: list[tuple[float, int]] = []
        for index, document in enumerate(self.documents):
            frequencies = self.term_frequencies[index]
            score = 0.0
            for token in query_tokens:
                frequency = frequencies.get(token, 0)
                if not frequency:
                    continue
                document_frequency = self.doc_freq[token]
                inverse = math.log(1 + (count - document_frequency + 0.5) / (document_frequency + 0.5))
                denominator = frequency + k1 * (1 - b + b * self.doc_lengths[index] / max(self.average_length, 1))
                score += inverse * frequency * (k1 + 1) / denominator
            record_codes = self.document_codes[index]
            score += 5.0 * len(query_codes & record_codes)
            if score > 0:
                ranked.append((score, index))
        ranked.sort(reverse=True)
        results: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for score, index in ranked:
            record = self.records[index]
            unique_key = (record["source"], record["page"], record["text"])
            if unique_key in seen:
                continue
            seen.add(unique_key)
            results.append({
                "evidence_id": f"D{len(results) + 1}",
                "source": record["source"],
                "page": record["page"] or None,
                "element_id": record["element_id"] or None,
                "element_type": record["element_type"] or None,
                "origin": record["origin"],
                "score": round(score, 4),
                "excerpt": record["text"][:1200],
                "context": record["text"][:4000],
            })
            if len(results) >= limit:
                break
        return results


_RETRIEVER_LOCK = Lock()


@lru_cache(maxsize=1)
def _cached_document_evidence_index():
    if settings.evidence_backend == "neo4j":
        from .neo4j_evidence import Neo4jEvidenceRetriever
        return Neo4jEvidenceRetriever.from_settings(settings)
    if settings.evidence_backend != "bm25":
        raise ValueError("FEEDBACK_EVIDENCE_BACKEND must be neo4j or explicitly opted-in bm25")
    return DocumentEvidenceIndex(
        settings.fast_docs_dir,
        settings.vlm_docs_dir,
        settings.vlm_gcs_uri,
        settings.fast_gcs_uri,
    )


def get_document_evidence_index():
    if is_demo():
        from .role_demo import require_demo_scope
        from .demo_simulation import DemoEvidence
        require_demo_scope()
        return DemoEvidence()
    # lru_cache alone can construct two pooled drivers on concurrent cold reads.
    with _RETRIEVER_LOCK:
        return _cached_document_evidence_index()


def close_document_evidence_index() -> None:
    with _RETRIEVER_LOCK:
        retriever = _cached_document_evidence_index() if _cached_document_evidence_index.cache_info().currsize else None
        _cached_document_evidence_index.cache_clear()
    if retriever is not None:
        close = getattr(retriever, "close", None)
        if callable(close):
            close()


def evidence_metadata(evidence: list[dict]) -> dict:
    """Describe the evidence actually consumed, not the agent's unknown corpus."""
    backends = set()
    versions = set()
    for item in evidence:
        origin = item.get("origin")
        backends.add("bm25" if origin in {"vlm", "fast"} else str(origin or "provided_source"))
        if item.get("corpus_version"):
            versions.add(str(item["corpus_version"]))
    return {"rca_evidence_backend": next(iter(backends)) if len(backends) == 1 else "mixed" if backends else settings.evidence_backend,
            "rca_corpus_version": next(iter(versions)) if len(versions) == 1 and all(item.get("corpus_version") for item in evidence) else None,
            "rca_retrieval_status": "available" if evidence else "no_matches"}
