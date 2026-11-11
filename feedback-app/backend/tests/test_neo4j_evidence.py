import hashlib
import json
import re
from dataclasses import replace
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from neo4j import READ_ACCESS

from app.config import settings
from app.document_evidence import close_document_evidence_index, get_document_evidence_index
from app.main import app
from app.neo4j_evidence import (
    ADJACENT_QUERY, CORPUS_QUERY, ENTITY_QUERY, HYBRID_QUERY,
    EvidenceRetrievalError, Neo4jEvidenceConfig, Neo4jEvidenceRetriever,
    business_codes, lexical_query, load_source_manifest, source_window,
)


PREFIX = "NEO_RCA-VisualAnalysis__"
DOC = PREFIX + "training_000.md"


def config(**changes):
    return replace(Neo4jEvidenceConfig(uri="neo4j+s://graph.example", username="test-user", password="private-password",
        api_key="private-embedding-key"), **changes)


def index_records():
    return [{"name": "vector", "type": "VECTOR", "state": "ONLINE", "labelsOrTypes": ["Chunk"],
        "properties": ["embedding"], "options": {"indexConfig": {"vector.dimensions": 1536, "vector.similarity_function": "COSINE"}}},
        {"name": "keyword", "type": "FULLTEXT", "state": "ONLINE", "labelsOrTypes": ["Chunk"], "properties": ["text"], "options": {}}]


def hit(chunk="c1", document=DOC, text="Order management uses VA01 to create a sales order.", **updates):
    return {"chunk_id": chunk, "document_id": document, "text": text, "page": 3, "position": 1,
        "method": "vector", "retrieval_score": 0.9, **updates}


class FakeDriver:
    def __init__(self, hits=(), adjacent=(), entities=()):
        self.indexes = index_records()
        self.corpus = {"documents": 1, "document_ids": [DOC], "completed_documents": 1,
            "compatible_documents": 1,
            "chunks": 2, "embedded_chunks": 2, "compatible_chunks": 2, "embedding_models": ["text-embedding-3-small"]}
        self.hits, self.adjacent, self.entities = hits, adjacent, entities
        self.calls = []
        self.closed = False

    def session(self, **kwargs):
        assert kwargs == {"database": "neo4j", "default_access_mode": READ_ACCESS}
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, parameters):
        self.calls.append((query.text, parameters, query.timeout))
        if query.text.startswith("SHOW INDEXES"):
            return self.indexes
        if query.text == CORPUS_QUERY:
            return [self.corpus]
        if query.text == HYBRID_QUERY:
            return [{"hit": row} for row in self.hits]
        if query.text == ADJACENT_QUERY:
            return [{"hit": row} for row in self.adjacent]
        if query.text == ENTITY_QUERY:
            return [{"hit": row} for row in self.entities]
        raise AssertionError("Unexpected Cypher")

    def close(self):
        self.closed = True


@pytest.fixture
def build_retriever():
    opened = []

    def build(*, driver=None, response=None, **changes):
        calls = []

        def handler(request):
            calls.append(request)
            return response if response is not None else httpx.Response(200, json={"model": "text-embedding-3-small", "data": [{"embedding": [0.01] * 1536}]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        driver = driver or FakeDriver([hit()])
        retriever = Neo4jEvidenceRetriever(config(**changes), driver=driver, client=client)
        opened.append(retriever)
        return retriever, driver, calls

    yield build
    for retriever in opened:
        retriever.close()


def write_manifest(tmp_path, **changes):
    manifest = {"bucket": "private-test-bucket", "vlm_prefix": "parsed_docs_vlm", "fast_prefix": "parsed_docs_fast",
        "documents": [{"source": "ANZ_O2C_Order_Management.pdf", "parser_origin": "vlm", "gcs_objects": ["training_raw.json"],
                       "markdown_files": ["vlm/training_000.md"]}], **changes}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_server_configuration_reads_only_credentials_needed_from_explicit_file(tmp_path):
    private = tmp_path / "graph.env"
    private.write_text("NEO4J_URI=neo4j+s://graph.example\nNEO4J_USERNAME=file-user\nNEO4J_PASSWORD=file-secret\nOPENAI_API_KEY=file-key\nEMBEDDING_PROVIDER=openai\nEMBEDDING_MODEL=text-embedding-3-small\nUNRELATED_SECRET=not-loaded\n")
    with patch.dict(settings.__dict__, {"neo4j_env_file": str(private), "neo4j_uri": "", "neo4j_username": "", "neo4j_password": "",
            "evidence_embedding_api_key": "", "evidence_embedding_model": "", "evidence_embedding_base_url": "", "neo4j_database": "",
            "neo4j_source_manifest": "", "neo4j_corpus_version": ""}):
        loaded = Neo4jEvidenceConfig.from_settings(settings)
    assert loaded.username == "file-user" and loaded.password == "file-secret" and loaded.api_key == "file-key"
    assert loaded.embedding_model == "text-embedding-3-small" and loaded.dimensions == 1536
    for private_value in (loaded.uri, loaded.username, loaded.password, loaded.api_key, "not-loaded"):
        assert private_value not in repr(loaded)
    assert not hasattr(loaded, "UNRELATED_SECRET")


def test_explicit_server_environment_overrides_private_source_file(tmp_path):
    private = tmp_path / "graph.env"
    private.write_text("NEO4J_PASSWORD=old-secret\nOPENAI_API_KEY=old-key\n")
    with patch.dict(settings.__dict__, {"neo4j_env_file": str(private), "neo4j_uri": "neo4j+s://graph.example", "neo4j_username": "app-user",
            "neo4j_password": "new-secret", "evidence_embedding_api_key": "new-key", "neo4j_corpus_version": ""}):
        loaded = Neo4jEvidenceConfig.from_settings(settings)
    assert loaded.password == "new-secret" and loaded.api_key == "new-key"


@pytest.mark.parametrize("changes", [
    {"uri": "http://graph.example"}, {"uri": "bolt://graph.example"}, {"uri": "neo4j+s://user:secret@graph.example"},
    {"uri": "neo4j+s://graph.example?password=secret"}, {"uri": "neo4j+s://[malformed"},
    {"embedding_base_url": "http://embedding.example"}, {"embedding_base_url": "https://user:secret@embedding.example/v1"},
    {"embedding_base_url": "https://embedding.example/v1?api_key=secret"}, {"document_prefix": ""}, {"password": ""},
    {"api_key": ""}, {"embedding_model": "unrelated-1536-model"}, {"vector_index": "vector`) CALL anything"},
    {"query_timeout": 0}, {"query_timeout": 121}, {"corpus_version": "unverifiable-version"},
])
def test_invalid_or_insecure_server_configuration_fails_closed(changes):
    with pytest.raises(EvidenceRetrievalError):
        config(**changes).validate()


def test_unencrypted_loopback_graph_is_allowed_only_in_local_development():
    config(uri="bolt://127.0.0.1:7687").validate("development")
    with pytest.raises(EvidenceRetrievalError):
        config(uri="bolt://127.0.0.1:7687").validate("production")


def test_manifest_restores_exact_original_source_names_without_reading_document_text(tmp_path, build_retriever):
    path = write_manifest(tmp_path)
    version, mapping = load_source_manifest(str(path), PREFIX)
    assert version == "neo-rca-visual-" + hashlib.sha256(path.read_bytes()).hexdigest()[:20]
    assert set(mapping) == {DOC}
    retriever, driver, _ = build_retriever(source_manifest=str(path), corpus_version=version)
    result = retriever.search("How do I create an order with VA01?")[0]
    assert result["source"] == "ANZ_O2C_Order_Management.pdf" and result["page"] == "3"
    assert result["source_uris"] == ["gs://private-test-bucket/parsed_docs_vlm/training_raw.json"]
    assert result["corpus_version"] == version and result["parser_origin"] == "vlm"
    assert result["document_id"] == DOC and result["chunk_id"] == "c1" and result["chunk_position"] == 1
    assert result["chunk_content_sha256"] == hashlib.sha256(hit()["text"].encode()).hexdigest()
    assert result["provenance_origin"] == "source_manifest"
    for cypher, parameters, timeout in driver.calls:
        assert not re.search(r"\b(CREATE|MERGE|DELETE|SET|DROP|REMOVE)\b", cypher)
        assert timeout == 20
        if cypher != driver.calls[0][0]:
            assert parameters["scope_to_manifest"] is True and parameters["document_ids"] == [DOC]


def test_absent_manifest_uses_real_graph_document_identifier_not_a_fabricated_original_name(build_retriever):
    retriever, _, _ = build_retriever()
    result = retriever.search("What is the order rule?")[0]
    assert result["source"] == DOC and result["provenance_origin"] == "neo4j_document"
    assert result["corpus_version"] is None and result["parser_origin"] is None and result["source_uris"] == []


@pytest.mark.parametrize("manifest", [{"documents": []}, {"documents": [{}]}, {"documents": [{"source": "one.pdf", "parser_origin": "other"}]}])
def test_invalid_source_manifest_fails_closed(tmp_path, manifest):
    path = write_manifest(tmp_path, **manifest)
    with pytest.raises(EvidenceRetrievalError, match="manifest"):
        load_source_manifest(str(path), PREFIX)


def test_missing_or_different_pinned_manifest_fails_without_connecting_to_graph(tmp_path):
    with pytest.raises(EvidenceRetrievalError, match="manifest"):
        load_source_manifest(str(tmp_path / "missing.json"), PREFIX)
    path = write_manifest(tmp_path)
    driver = Mock()
    with pytest.raises(EvidenceRetrievalError, match="pinned"):
        Neo4jEvidenceRetriever(config(source_manifest=str(path), corpus_version="different-version"), driver=driver)
    driver.session.assert_not_called()


def test_only_scoped_manifest_documents_are_returned_and_used_as_graph_seeds(tmp_path, build_retriever):
    path = write_manifest(tmp_path)
    driver = FakeDriver([hit("foreign", document="OTHER__private.md"), hit("other-release", document=PREFIX + "not-in-manifest.md"), hit()])
    retriever, _, _ = build_retriever(driver=driver, source_manifest=str(path))
    result = retriever.search("What is the order rule?")
    assert [item["chunk_id"] for item in result] == ["c1"]
    for cypher, parameters, _ in driver.calls:
        if cypher in {ADJACENT_QUERY, ENTITY_QUERY}:
            assert [seed["chunk_id"] for seed in parameters["seeds"]] == ["c1"]
            assert "d.status = 'Completed'" in cypher and "d.embedding_model = $model" in cypher


def test_hybrid_ranking_fuses_methods_deduplicates_hits_and_uses_graph_only_as_passage_hints(build_retriever):
    driver = FakeDriver([
        hit("vector-only", retrieval_score=0.99), hit("both", method="vector", retrieval_score=0.95),
        hit("both", method="fulltext", retrieval_score=10), hit("both", method="fulltext", retrieval_score=10),
    ], adjacent=[hit("adjacent", text="Adjacent source passage about order validation.", method="adjacent_graph", seed_id="both", seed_score=0.03)],
        entities=[hit("entity", text="Order management source passage with a required order check.", method="entity_graph", seed_id="both", seed_score=0.03, via_entity="Sales order"),
                  hit("unrelated", text="A completely unrelated passage.", method="entity_graph", seed_id="both", seed_score=0.03, via_entity="Unverified entity")])
    retriever, _, _ = build_retriever(driver=driver)
    results = retriever.search("What is the order rule?")
    assert results[0]["chunk_id"] == "both" and results[0]["retrieval_methods"] == ["fulltext", "vector"]
    assert len([item for item in results if item["chunk_id"] == "both"]) == 1
    assert results[0]["score"] < 0.04
    assert "unrelated" not in {item["chunk_id"] for item in results}
    by_id = {item["chunk_id"]: item for item in results}
    assert by_id["entity"]["matched_entities"] == ["Sales order"] and by_id["entity"]["origin"] == "neo4j"
    assert by_id["entity"]["context"] == "Order management source passage with a required order check."
    assert by_id["adjacent"]["retrieval_methods"] == ["adjacent_graph"]
    assert "COUNT {" in ENTITY_QUERY and "degree <= 30" in ENTITY_QUERY and "LIMIT 3" in ENTITY_QUERY
    assert "[:NEXT_CHUNK]" in ADJACENT_QUERY and "abs(c.position - s.position) = 1" in ADJACENT_QUERY


def test_exact_business_codes_are_retained_and_lucene_operators_are_not_interpreted():
    assert business_codes("Explain MM 30, MM40 and VA01") == {"MM30", "MM40", "VA01"}
    query = lexical_query('VA01 ") OR *:* +secret -other ~2 [x TO y]')
    assert '"VA01"^4' in query and "*:*" not in query and "~" not in query and "[" not in query
    assert lexical_query("订单管理") == '"订单管理"'


def test_long_source_windows_preserve_the_actual_code_passage_and_exact_offsets(build_retriever):
    text = ("Unrelated table row.\n" * 500) + "MM30 | This is the matching status row.\n" + ("Additional table row.\n" * 200)
    context, start, end = source_window(text, "What is MM30?")
    assert start > 0 and context == text[start:end] and len(context) <= 4000 and "MM30" in context[:1200]
    retriever, _, _ = build_retriever(driver=FakeDriver([hit(text=text)]))
    first = retriever.search("What is MM30?")[0]
    second = retriever.search("Explain MM30")[0]
    assert first["evidence_id"] == second["evidence_id"] and "MM30" in first["excerpt"]
    assert first["context"] == text[first["context_start"]:first["context_end"]]


@pytest.mark.parametrize("page", [None, 0, -1, "unknown"])
def test_missing_pages_are_not_invented(build_retriever, page):
    retriever, _, _ = build_retriever(driver=FakeDriver([hit(page=page)]))
    assert retriever.search("What is the order rule?")[0]["page"] is None


@pytest.mark.parametrize("kind", ["dimensions", "state", "labels", "properties", "similarity", "keyword-missing"])
def test_incompatible_or_offline_indexes_fail_before_query_embedding(build_retriever, kind):
    retriever, driver, requests = build_retriever()
    if kind == "dimensions":
        driver.indexes[0]["options"]["indexConfig"]["vector.dimensions"] = 3072
    elif kind == "similarity":
        driver.indexes[0]["options"]["indexConfig"]["vector.similarity_function"] = "EUCLIDEAN"
    elif kind == "keyword-missing":
        driver.indexes.pop()
    else:
        driver.indexes[0][{"state": "state", "labels": "labelsOrTypes", "properties": "properties"}[kind]] = "POPULATING" if kind == "state" else ["Other"]
    with pytest.raises(EvidenceRetrievalError, match="index"):
        retriever.search("What is the order rule?")
    assert requests == []


@pytest.mark.parametrize("changes", [{"documents": 0}, {"chunks": 0}, {"completed_documents": 0}, {"compatible_documents": 0}, {"compatible_chunks": 1}, {"embedding_models": ["text-embedding-ada-002"]}])
def test_missing_or_incompatible_corpus_is_not_mistaken_for_no_search_hits(build_retriever, changes):
    retriever, driver, requests = build_retriever()
    driver.corpus.update(changes)
    with pytest.raises(EvidenceRetrievalError, match="corpus"):
        retriever.search("What is the order rule?")
    assert requests == []


def test_missing_manifest_document_is_detected_before_search(tmp_path, build_retriever):
    retriever, driver, requests = build_retriever(source_manifest=str(write_manifest(tmp_path)))
    driver.corpus["document_ids"] = [PREFIX + "another-document.md"]
    with pytest.raises(EvidenceRetrievalError, match="manifest"):
        retriever.search("What is the order rule?")
    assert requests == []


@pytest.mark.parametrize("response", [
    httpx.Response(401, json={"error": "raw private-embedding-key diagnostic"}),
    httpx.Response(200, json={"data": [{"embedding": [0.1] * 32}]}),
    httpx.Response(200, json={"data": [{"embedding": [True] * 1536}]}),
    httpx.Response(200, json={"data": [{"embedding": [0.0] * 1536}]}),
    httpx.Response(200, json={"model": "text-embedding-ada-002", "data": [{"embedding": [0.1] * 1536}]}),
    httpx.Response(200, json={"data": [{"embedding": ["bad"] * 1536}]}),
])
def test_query_embedding_failure_is_safe_and_never_runs_keyword_only_or_local_fallback(build_retriever, response):
    retriever, driver, requests = build_retriever(response=response)
    with pytest.raises(EvidenceRetrievalError) as caught, patch("app.document_evidence.DocumentEvidenceIndex") as legacy:
        retriever.search("What is the order rule?")
    assert "No local fallback" in str(caught.value) and "private-embedding-key" not in str(caught.value)
    assert caught.value.__cause__ is None and len(requests) == 1
    assert all(cypher != HYBRID_QUERY for cypher, _, _ in driver.calls)
    legacy.assert_not_called()


def test_driver_failure_redacts_upstream_error_and_uses_read_sessions_only(build_retriever):
    retriever, driver, _ = build_retriever()
    with patch.object(driver, "run", side_effect=RuntimeError("private-password neo4j+s://secret.example")):
        with pytest.raises(EvidenceRetrievalError) as caught:
            retriever.search("What is the order rule?")
    assert "private-password" not in str(caught.value) and "secret.example" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_stats_do_not_call_embedding_service_and_do_not_expose_private_connection_details(build_retriever):
    retriever, _, requests = build_retriever()
    summary = retriever.stats()
    assert summary["backend"] == "neo4j" and summary["localFallbackEnabled"] is False
    assert summary["documents"] == 1 and summary["chunks"] == 2 and summary["dimensions"] == 1536
    assert "graph.example" not in json.dumps(summary) and "private-password" not in json.dumps(summary) and "document_ids" not in summary
    assert requests == []


def test_embedding_cache_is_bounded_and_does_not_cache_answers_or_raw_questions(build_retriever):
    retriever, _, requests = build_retriever()
    retriever.search("What is the order rule?")
    retriever.search("What is the order rule?")
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload["model"] == "text-embedding-3-small" and payload["input"] == "What is the order rule?"
    for index in range(130):
        retriever._embed(f"Question {index}")
    assert len(retriever._embeddings) == 128
    assert all(re.fullmatch(r"[a-f0-9]{64}", key) for key in retriever._embeddings)
    key, (_, vector) = next(iter(retriever._embeddings.items()))
    retriever._embeddings[key] = 0, vector
    retriever._embed("Question 2")
    assert len(requests) == 132


def test_empty_search_does_not_connect_and_result_limit_is_bounded(build_retriever):
    retriever, driver, requests = build_retriever(driver=FakeDriver([hit(f"chunk-{index}", text=f"Order rule {index}") for index in range(30)]))
    assert retriever.search(" ") == [] and retriever.search("order", limit=0) == []
    assert not driver.calls and not requests
    assert len(retriever.search("Order", limit=500)) == 12


def test_factory_never_constructs_bm25_after_graph_configuration_or_connectivity_failure():
    close_document_evidence_index()
    try:
        with patch.dict(settings.__dict__, {"evidence_backend": "neo4j"}), patch("app.neo4j_evidence.Neo4jEvidenceRetriever.from_settings", side_effect=EvidenceRetrievalError("Unavailable")), patch("app.document_evidence.DocumentEvidenceIndex") as legacy:
            with pytest.raises(EvidenceRetrievalError):
                get_document_evidence_index()
            legacy.assert_not_called()
        with patch.dict(settings.__dict__, {"evidence_backend": "unknown"}):
            with pytest.raises(ValueError):
                get_document_evidence_index()
    finally:
        close_document_evidence_index()


def test_cached_graph_driver_is_closed_without_constructing_an_unused_retriever():
    close_document_evidence_index()
    fake = Mock()
    with patch.dict(settings.__dict__, {"evidence_backend": "neo4j"}), patch("app.neo4j_evidence.Neo4jEvidenceRetriever.from_settings", return_value=fake) as create:
        close_document_evidence_index()
        create.assert_not_called()
        assert get_document_evidence_index() is fake and get_document_evidence_index() is fake
        close_document_evidence_index()
        create.assert_called_once()
        fake.close.assert_called_once()


def test_evidence_health_is_reviewer_only_and_returns_safe_failures():
    client = TestClient(app)
    reporter = {"Authorization": "Bearer " + client.post("/api/auth/mock-login", json={"email": "alex.requester@example.test"}).json()["accessToken"]}
    reviewer = {"Authorization": "Bearer " + client.post("/api/auth/mock-login", json={"email": "quality.reviewer@example.test"}).json()["accessToken"]}
    fake = Mock()
    fake.stats.return_value = {"backend": "neo4j", "connected": True, "documents": 179, "localFallbackEnabled": False}
    with patch("app.main.get_document_evidence_index", return_value=fake) as get:
        assert client.get("/api/evidence/status").status_code == 401
        assert client.get("/api/evidence/status", headers=reporter).status_code == 403
        get.assert_not_called()
        response = client.get("/api/evidence/status", headers=reviewer)
    assert response.status_code == 200 and response.json()["documents"] == 179
    with patch("app.main.get_document_evidence_index", side_effect=RuntimeError("raw private-password")):
        failed = client.get("/api/evidence/status", headers=reviewer)
    assert failed.status_code == 503 and "private-password" not in failed.text and failed.json()["connected"] is False
