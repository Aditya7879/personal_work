"""Read-only hybrid/graph evidence retrieval over the completed NEO corpus.

Only stored source passages are evidence. Shared entities and NEXT_CHUNK edges
are retrieval hints, never independent facts or reconstructed agent traces.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values
from neo4j import GraphDatabase, Query, READ_ACCESS


class EvidenceRetrievalError(RuntimeError):
    """A safe error without connection strings, credentials or upstream bodies."""


_DIMENSIONS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}
_STOP = set("a an and are as at be been by can do does for from how i if in into is it its me of on or our please response answer should tell than that the their these they this to us was we were what when where which why with would you your expected incorrect correctly".split())
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_CODE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{1,10}[A-Za-z0-9_-]*\d+[A-Za-z0-9_-]*(?![A-Za-z0-9])")


@dataclass(frozen=True)
class Neo4jEvidenceConfig:
    uri: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)
    api_key: str = field(repr=False)
    database: str = "neo4j"
    document_prefix: str = "NEO_RCA-VisualAnalysis__"
    vector_index: str = "vector"
    fulltext_index: str = "keyword"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    source_manifest: str = field(default="", repr=False)
    corpus_version: str = ""
    query_timeout: int = 20
    min_vector_score: float = 0.60

    @property
    def dimensions(self) -> int:
        return _DIMENSIONS[self.embedding_model]

    @classmethod
    def from_settings(cls, settings) -> "Neo4jEvidenceConfig":
        source = {}
        if settings.neo4j_env_file:
            path = Path(settings.neo4j_env_file).expanduser()
            if not path.is_absolute() or not path.is_file():
                raise EvidenceRetrievalError("The server-side Neo4j credential file is unavailable.")
            source = dotenv_values(path)
        if str(source.get("EMBEDDING_PROVIDER") or "openai").lower() != "openai":
            raise EvidenceRetrievalError("The configured graph embedding provider is not supported by this adapter.")
        config = cls(
            uri=settings.neo4j_uri or source.get("NEO4J_URI") or "",
            username=settings.neo4j_username or source.get("NEO4J_USERNAME") or "",
            password=settings.neo4j_password or source.get("NEO4J_PASSWORD") or "",
            database=settings.neo4j_database or source.get("NEO4J_DATABASE") or "neo4j",
            api_key=settings.evidence_embedding_api_key or source.get("OPENAI_API_KEY") or "",
            embedding_model=settings.evidence_embedding_model or source.get("EMBEDDING_MODEL") or "text-embedding-3-small",
            embedding_base_url=(settings.evidence_embedding_base_url or source.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/"),
            document_prefix=settings.neo4j_document_prefix, vector_index=settings.neo4j_vector_index,
            fulltext_index=settings.neo4j_fulltext_index, source_manifest=settings.neo4j_source_manifest,
            corpus_version=settings.neo4j_corpus_version,
            query_timeout=settings.evidence_query_timeout,
        )
        config.validate(settings.app_env)
        return config

    def validate(self, app_env: str = "development") -> None:
        if not all((self.uri, self.username, self.password, self.api_key, self.database, self.document_prefix)):
            raise EvidenceRetrievalError("Neo4j evidence and query-embedding credentials must be configured on the backend.")
        try:
            uri, endpoint = urlsplit(self.uri), urlsplit(self.embedding_base_url)
        except ValueError:
            raise EvidenceRetrievalError("Invalid server-side Neo4j or embedding endpoint configuration.") from None
        local = app_env in {"development", "dev", "local", "test"} and uri.hostname in {"localhost", "127.0.0.1", "::1"}
        if uri.username or uri.password or uri.fragment or uri.query or not uri.hostname or uri.scheme not in ({"neo4j+s", "bolt+s"} | ({"neo4j", "bolt"} if local else set())):
            raise EvidenceRetrievalError("Use an encrypted, server-owned Neo4j connection without credentials in its URL.")
        if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise EvidenceRetrievalError("Query embeddings require a server-owned HTTPS endpoint without URL credentials.")
        if self.embedding_model not in _DIMENSIONS or not 1 <= self.query_timeout <= 120:
            raise EvidenceRetrievalError("The query embedding model or retrieval timeout is not supported.")
        if self.corpus_version and not self.source_manifest:
            raise EvidenceRetrievalError("Pin a source manifest to verify the configured Neo4j evidence corpus version.")
        if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,100}", value) for value in (self.vector_index, self.fulltext_index)):
            raise EvidenceRetrievalError("Invalid configured Neo4j search index name.")


def query_terms(question: str, expected: str = "") -> list[str]:
    values = _TOKEN.findall(question.casefold()) + _TOKEN.findall(expected.casefold())[:20]
    return list(dict.fromkeys(value for value in values if 2 <= len(value) <= 64 and value not in _STOP))[:32]


def business_codes(text: str) -> set[str]:
    compact = re.sub(r"\b(MM|SD|VL|VA|VF)\s+(\d+[A-Za-z0-9]*)\b", r"\1\2", text, flags=re.I)
    return {match.upper() for match in _CODE.findall(compact) if len(match) <= 64}


def lexical_query(question: str, expected: str = "") -> str:
    # Tokens contain only Unicode alphanumerics. No user Lucene operators survive.
    terms = query_terms(question, expected)
    codes = sorted(business_codes(question))[:8]
    parts = [f'"{term}"' for term in terms]
    parts.extend(f'"{code}"^4' for code in codes)
    return " OR ".join(parts) or '"__no_evidence_query_terms__"'


def source_window(text: str, question: str, expected: str = "", size: int = 4000) -> tuple[str, int, int]:
    """Keep actual text around a matched code/rule, not just a long table's head."""
    if len(text) <= size:
        return text, 0, len(text)
    codes = business_codes(question) or business_codes(expected)
    matches = []
    for code in codes:
        pattern = r"(?<![A-Za-z0-9])" + "[ _-]*".join(re.escape(part) for part in re.findall(r"[A-Z]+|\d+", code)) + r"(?![A-Za-z0-9])"
        matches.extend(match.start() for match in re.finditer(pattern, text, re.I))
    if not matches:
        terms = query_terms(question)[:10]
        lines, offset, best = text.splitlines(keepends=True), 0, (0, 0)
        for line in lines:
            hits = sum(term in line.casefold() for term in terms)
            if hits > best[0]:
                best = hits, offset
            offset += len(line)
        matches = [best[1]]
    start = max(0, min(min(matches) - 800, len(text) - size))
    if start:
        boundary = text.rfind("\n", max(0, start - 180), start + 1)
        if boundary >= 0:
            start = boundary + 1
    end = min(len(text), start + size)
    return text[start:end], start, end


def load_source_manifest(path: str, prefix: str) -> tuple[str | None, dict[str, dict]]:
    """Read filename provenance only; never load or locally rank document text."""
    if not path:
        return None, {}
    try:
        file = Path(path).expanduser()
        if not file.is_absolute():
            raise ValueError("A server-owned absolute manifest path is required")
        raw = file.read_bytes()
        manifest = json.loads(raw)
        version = "neo-rca-visual-" + hashlib.sha256(raw).hexdigest()[:20]
        mapping = {}
        for document in manifest["documents"]:
            source = str(document.get("source") or "").strip()
            parser = document.get("parser_origin")
            if not source or parser not in {"vlm", "fast"}:
                raise ValueError("Missing source/parser provenance")
            gcs_prefix = manifest["vlm_prefix" if parser == "vlm" else "fast_prefix"]
            uris = [f"gs://{manifest['bucket']}/{gcs_prefix}/{name}" for name in document.get("gcs_objects", [])]
            for markdown in document["markdown_files"]:
                name = prefix + Path(markdown).name
                if not name.endswith(".md"):
                    raise ValueError("Expected an ingested Markdown filename")
                row = {"source": source, "parser_origin": parser, "source_uris": uris}
                if name in mapping:
                    raise ValueError("Duplicate source mapping")
                mapping[name] = row
        if not mapping:
            raise ValueError("No source mappings")
        return version, mapping
    except Exception:
        raise EvidenceRetrievalError("The configured Neo4j source manifest is unavailable or invalid; no local evidence fallback was used.") from None


_DOCUMENT_SCOPE = """d.fileName STARTS WITH $prefix
    AND (NOT $scope_to_manifest OR d.fileName IN $document_ids)"""
_SCOPE = f"""{_DOCUMENT_SCOPE} AND d.status = 'Completed' AND d.embedding_model = $model
    AND c.text IS NOT NULL AND c.id IS NOT NULL"""
_FIELDS = """chunk_id: c.id, document_id: d.fileName,
    position: c.position, page: c.page_number, text: c.text"""

CORPUS_QUERY = f"""
MATCH (d:Document) WHERE {_DOCUMENT_SCOPE}
OPTIONAL MATCH (d)<-[:PART_OF]-(c:Chunk)
RETURN count(DISTINCT d) AS documents, collect(DISTINCT d.fileName) AS document_ids,
    count(DISTINCT CASE WHEN d.status = 'Completed' THEN d END) AS completed_documents,
    count(DISTINCT CASE WHEN d.embedding_model = $model THEN d END) AS compatible_documents,
    count(c) AS chunks, count(c.embedding) AS embedded_chunks,
    sum(CASE WHEN size(c.embedding) = $dimensions THEN 1 ELSE 0 END) AS compatible_chunks,
    collect(DISTINCT d.embedding_model) AS embedding_models
"""

HYBRID_QUERY = f"""
CALL () {{
    CALL db.index.vector.queryNodes($vector_index, $fetch_count, $embedding) YIELD node AS c, score
    MATCH (c:Chunk)-[:PART_OF]->(d:Document) WHERE {_SCOPE} AND score >= $min_vector_score
    WITH c, d, score ORDER BY score DESC, c.id LIMIT $candidate_limit
    RETURN collect({{{_FIELDS}, method: 'vector', retrieval_score: score}}) AS vector_hits
}}
CALL () {{
    CALL db.index.fulltext.queryNodes($fulltext_index, $lexical, {{limit: $fetch_count}}) YIELD node AS c, score
    MATCH (c:Chunk)-[:PART_OF]->(d:Document) WHERE {_SCOPE}
    WITH c, d, score ORDER BY score DESC, c.id LIMIT $candidate_limit
    RETURN collect({{{_FIELDS}, method: 'fulltext', retrieval_score: score}}) AS keyword_hits
}}
UNWIND vector_hits + keyword_hits AS hit RETURN hit
"""

ADJACENT_QUERY = f"""
UNWIND $seeds AS seed
MATCH (s:Chunk {{id: seed.chunk_id}})-[:PART_OF]->(d:Document {{fileName: seed.document_id}})
MATCH (s)-[:NEXT_CHUNK]-(c:Chunk)-[:PART_OF]->(d)
WHERE {_SCOPE} AND abs(c.position - s.position) = 1
RETURN {{{_FIELDS}, method: 'adjacent_graph', seed_id: seed.chunk_id, seed_score: seed.score}} AS hit
ORDER BY seed.score DESC, seed.chunk_id, c.position, c.id
LIMIT 24
"""

ENTITY_QUERY = f"""
UNWIND $seeds AS seed
MATCH (s:Chunk {{id: seed.chunk_id}})-[:PART_OF]->(sd:Document {{fileName: seed.document_id}})
CALL (s) {{
    MATCH (s)-[:HAS_ENTITY]->(e:__Entity__)
    WITH e, COUNT {{ (e)<-[:HAS_ENTITY]-(:Chunk) }} AS degree
    WHERE degree >= 2 AND degree <= 30
    RETURN e, degree ORDER BY degree, e.id LIMIT 3
}}
MATCH (e)<-[:HAS_ENTITY]-(c:Chunk)-[:PART_OF]->(d:Document)
WHERE {_SCOPE} AND c.id <> s.id
RETURN {{{_FIELDS}, method: 'entity_graph', seed_id: seed.chunk_id, seed_score: seed.score,
    via_entity: e.id, entity_degree: degree}} AS hit
ORDER BY seed.score DESC, degree, e.id, d.fileName, c.id
LIMIT 36
"""


class Neo4jEvidenceRetriever:
    backend_name = "neo4j"

    def __init__(self, config: Neo4jEvidenceConfig, *, driver=None, client=None):
        self.config = config
        self.corpus_version, self._provenance = load_source_manifest(config.source_manifest, config.document_prefix)
        if config.corpus_version and self.corpus_version != config.corpus_version:
            raise EvidenceRetrievalError("The source manifest does not match the pinned Neo4j evidence corpus version.")
        self._driver = driver or GraphDatabase.driver(config.uri, auth=(config.username, config.password),
            connection_timeout=10, connection_acquisition_timeout=15, max_connection_pool_size=4,
            max_connection_lifetime=120, max_transaction_retry_time=5)
        self._client = client or httpx.Client(timeout=httpx.Timeout(config.query_timeout, connect=10), follow_redirects=False)
        self._lock = Lock()
        self._schema_until = 0.0
        self._embeddings: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()

    @classmethod
    def from_settings(cls, settings) -> "Neo4jEvidenceRetriever":
        return cls(Neo4jEvidenceConfig.from_settings(settings))

    def close(self) -> None:
        self._client.close()
        self._driver.close()

    def _run(self, cypher: str, parameters: dict | None = None) -> list[dict]:
        try:
            with self._driver.session(database=self.config.database, default_access_mode=READ_ACCESS) as session:
                return [dict(row) for row in session.run(Query(cypher, timeout=self.config.query_timeout), parameters or {})]
        except Exception:
            raise EvidenceRetrievalError("Neo4j source retrieval is unavailable; no local evidence fallback was used.") from None

    def _scope_parameters(self) -> dict:
        return {"prefix": self.config.document_prefix, "scope_to_manifest": bool(self._provenance),
                "document_ids": list(self._provenance), "dimensions": self.config.dimensions,
                "model": self.config.embedding_model}

    def _corpus_summary(self) -> dict:
        rows = self._run(CORPUS_QUERY, self._scope_parameters())
        summary = rows[0] if rows else {}
        if (not summary.get("documents") or not summary.get("chunks")
                or summary.get("completed_documents") != summary["documents"]
                or summary.get("compatible_documents") != summary["documents"]
                or summary.get("compatible_chunks") != summary["chunks"]
                or summary.get("embedding_models") != [self.config.embedding_model]
                or (self._provenance and set(summary.get("document_ids", [])) != set(self._provenance))):
            raise EvidenceRetrievalError("The scoped Neo4j corpus is missing, incomplete or incompatible with the configured embedding model/manifest.")
        return {key: value for key, value in summary.items() if key != "document_ids"}

    def _check_indexes(self) -> None:
        with self._lock:
            if self._schema_until > time.monotonic():
                return
            rows = self._run("""SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties, options
                WHERE name IN $names RETURN name, type, state, labelsOrTypes, properties, options""",
                {"names": [self.config.vector_index, self.config.fulltext_index]})
            indexes = {row["name"]: row for row in rows}
            vector = indexes.get(self.config.vector_index, {})
            fulltext = indexes.get(self.config.fulltext_index, {})
            vector_config = (vector.get("options") or {}).get("indexConfig", {})
            if vector.get("type") != "VECTOR" or vector.get("state") != "ONLINE" or "Chunk" not in vector.get("labelsOrTypes", []) or vector.get("properties") != ["embedding"] or vector_config.get("vector.dimensions") != self.config.dimensions or str(vector_config.get("vector.similarity_function") or "").lower() != "cosine":
                raise EvidenceRetrievalError("Neo4j vector index is unavailable or does not match the ingestion embedding model/dimensions.")
            if fulltext.get("type") != "FULLTEXT" or fulltext.get("state") != "ONLINE" or "Chunk" not in fulltext.get("labelsOrTypes", []) or "text" not in fulltext.get("properties", []):
                raise EvidenceRetrievalError("Neo4j keyword index is unavailable. Configure the existing index; no local fallback was used.")
            self._corpus_summary()
            self._schema_until = time.monotonic() + 60

    def _embed(self, question: str) -> list[float]:
        text = question.strip()[:8000]
        key = hashlib.sha256(text.encode()).hexdigest()
        with self._lock:
            cached = self._embeddings.get(key)
            if cached and cached[0] > time.monotonic():
                self._embeddings.move_to_end(key)
                return cached[1]
        try:
            response = self._client.post(self.config.embedding_base_url + "/embeddings",
                headers={"Authorization": "Bearer " + self.config.api_key, "Content-Type": "application/json"},
                json={"model": self.config.embedding_model, "input": text, "encoding_format": "float"})
            response.raise_for_status()
            payload = response.json()
            vector = payload["data"][0]["embedding"]
            if payload.get("model", self.config.embedding_model) != self.config.embedding_model:
                raise ValueError("Incompatible embedding response model")
            if not isinstance(vector, list) or len(vector) != self.config.dimensions or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector) or not any(vector):
                raise ValueError("Invalid query-vector dimensions or values")
        except Exception:
            raise EvidenceRetrievalError("Query embedding is unavailable or incompatible with the ingested graph. No local fallback was used.") from None
        with self._lock:
            self._embeddings[key] = time.monotonic() + 300, vector
            self._embeddings.move_to_end(key)
            while len(self._embeddings) > 128:
                self._embeddings.popitem(last=False)
        return vector

    def stats(self) -> dict:
        self._check_indexes()
        summary = self._corpus_summary()
        return {"backend": self.backend_name, "connected": True, "vectorIndex": self.config.vector_index,
                "keywordIndex": self.config.fulltext_index, "embeddingModel": self.config.embedding_model,
                "dimensions": self.config.dimensions, "corpusPrefix": self.config.document_prefix,
                "corpusVersion": self.corpus_version, "manifestDocuments": len(self._provenance),
                "localFallbackEnabled": False, **summary}

    def search(self, query: str, expected: str = "", limit: int = 8) -> list[dict]:
        if not query.strip() or limit <= 0:
            return []
        limit = min(limit, 12)
        self._check_indexes()
        parameters = {**self._scope_parameters(), "model": self.config.embedding_model,
            "vector_index": self.config.vector_index,
            "fulltext_index": self.config.fulltext_index, "fetch_count": 160, "candidate_limit": 32,
            "min_vector_score": self.config.min_vector_score, "embedding": self._embed(query),
            "lexical": lexical_query(query, expected)}
        rows = [row["hit"] for row in self._run(HYBRID_QUERY, parameters)]
        rows.sort(key=lambda hit: (str(hit.get("method")), -float(hit.get("retrieval_score") or 0),
                                  str(hit.get("document_id")), str(hit.get("chunk_id"))))
        candidates: dict[tuple[str, str], dict] = {}
        ranks = {"vector": 0, "fulltext": 0}
        seen_hits = set()
        codes = business_codes(query)
        for hit in rows:
            method = hit.get("method")
            if method not in ranks or not self._eligible_hit(hit):
                continue
            key = hit["document_id"], hit["chunk_id"]
            if (*key, method) in seen_hits:
                continue
            seen_hits.add((*key, method))
            ranks[method] += 1
            entry = candidates.setdefault(key, {**hit, "score": 0.0, "methods": set(), "via_entities": set()})
            entry["methods"].add(method)
            entry["score"] += 1.0 / (60 + ranks[method])
            entry[f"{method}_score"] = hit.get("retrieval_score")
        for entry in candidates.values():
            matches = codes & business_codes(entry["text"])
            if matches:
                entry["score"] *= 1.0 + 0.20 * min(len(matches), 3)
        ranked = sorted(candidates.values(), key=lambda hit: (-hit["score"], hit["document_id"], hit["chunk_id"]))
        seeds = [{"chunk_id": hit["chunk_id"], "document_id": hit["document_id"], "score": hit["score"]} for hit in ranked[:min(6, limit)]]
        if seeds:
            graph_params = {**self._scope_parameters(), "model": self.config.embedding_model}
            graph_params["seeds"] = seeds
            terms = query_terms(query)
            graph_rows = self._run(ADJACENT_QUERY, graph_params) + self._run(ENTITY_QUERY, graph_params)
            for row in graph_rows:
                hit = row["hit"]
                if not self._eligible_hit(hit):
                    continue
                method = hit["method"]
                overlap = sum(term in hit["text"].casefold() for term in terms)
                if method == "entity_graph" and not overlap:
                    continue
                key = hit["document_id"], hit["chunk_id"]
                entry = candidates.setdefault(key, {**hit, "score": float(hit["seed_score"]) * (0.78 if method == "adjacent_graph" else 0.60), "methods": set(), "via_entities": set()})
                entry["methods"].add(method)
                if hit.get("via_entity"):
                    entry["via_entities"].add(str(hit["via_entity"]))
        ranked = sorted(candidates.values(), key=lambda hit: (-hit["score"], hit["document_id"], hit["chunk_id"]))
        results, seen = [], set()
        for hit in ranked:
            content, start, end = source_window(hit["text"], query, expected)
            unique = hit["document_id"], content
            if unique in seen:
                continue
            seen.add(unique)
            content_hash = hashlib.sha256(hit["text"].encode()).hexdigest()
            evidence_id = "NEO-" + hashlib.sha256(f"{hit['document_id']}:{hit['chunk_id']}:{content_hash}".encode()).hexdigest()[:20]
            page = hit.get("page")
            page = str(page) if page is not None and str(page).isdigit() and int(page) > 0 else None
            provenance = self._provenance.get(hit["document_id"], {})
            results.append({"evidence_id": evidence_id, "source": provenance.get("source") or hit["document_id"], "page": page,
                "element_id": hit["chunk_id"], "element_type": "graph_chunk", "origin": "neo4j",
                "score": round(hit["score"], 6), "excerpt": content[:1200], "context": content,
                "document_id": hit["document_id"], "chunk_id": hit["chunk_id"], "chunk_position": hit.get("position"),
                "parser_origin": provenance.get("parser_origin"), "source_uris": provenance.get("source_uris", []),
                "provenance_origin": "source_manifest" if provenance else "neo4j_document",
                "corpus_version": self.corpus_version, "chunk_content_sha256": content_hash,
                "retrieval_methods": sorted(hit["methods"]), "matched_entities": sorted(hit["via_entities"])[:6],
                "context_start": start, "context_end": end})
            if len(results) >= limit:
                break
        return results

    def _eligible_hit(self, hit: dict) -> bool:
        document_id = str(hit.get("document_id") or "")
        return bool(hit.get("text") and hit.get("chunk_id")
                    and document_id.startswith(self.config.document_prefix)
                    and (not self._provenance or document_id in self._provenance))
