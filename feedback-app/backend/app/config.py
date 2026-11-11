from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("FEEDBACK_APP_ENV", "development").strip().lower()
    auth_mode: str = os.getenv("FEEDBACK_AUTH_MODE", "mock").strip().lower()
    auth_secret: str = os.getenv("FEEDBACK_AUTH_SECRET", "")
    auth_token_ttl_seconds: int = int(os.getenv("FEEDBACK_AUTH_TOKEN_TTL_SECONDS", "28800"))
    mock_users_json: str = os.getenv("FEEDBACK_MOCK_USERS_JSON", "")
    google_iam_audiences_json: str = os.getenv("FEEDBACK_GOOGLE_IAM_AUDIENCES_JSON", "[]")
    google_iap_audience: str = os.getenv("FEEDBACK_GOOGLE_IAP_AUDIENCE", "").strip()
    # Legacy migration input only; verified Google users obtain roles from BigQuery.
    google_iam_users_json: str = os.getenv("FEEDBACK_GOOGLE_IAM_USERS_JSON", "[]")
    authz_table: str = os.getenv("FEEDBACK_AUTHZ_TABLE", "").strip()
    authz_cache_ttl_seconds: int = int(os.getenv("FEEDBACK_AUTHZ_CACHE_TTL_SECONDS", "30"))
    google_iam_domains: tuple[str, ...] = tuple(value.strip().lower() for value in os.getenv("FEEDBACK_GOOGLE_IAM_DOMAINS", "loreal.com").split(",") if value.strip())
    private_demo_presenters: tuple[str, ...] = tuple(value.strip().lower() for value in os.getenv("FEEDBACK_PRIVATE_DEMO_PRESENTERS", "").split(",") if value.strip())
    role_demo_enabled: bool = os.getenv('FEEDBACK_ROLE_DEMO_ENABLED', 'false').lower() == 'true'
    demo_frontend_origin: str = os.getenv('FEEDBACK_DEMO_FRONTEND_ORIGIN', '').strip()
    project_id: str = os.getenv("GCP_PROJECT_ID", "oa-apmena-techsandbox-ap-dv")
    dataset: str = os.getenv("BIGQUERY_DATASET", "agent_quality")
    location: str = os.getenv("BIGQUERY_LOCATION", "europe-west1")
    default_agent_id: str = os.getenv("DEFAULT_AGENT_ID", "neo-rules-agent")
    neo_agent_api_url: str = os.getenv("NEO_AGENT_API_URL", "").rstrip("/")
    agent_targets_json: str = os.getenv("FEEDBACK_AGENT_TARGETS_JSON", "")
    # Optional secondary identity used only for the exact Production NEO Companion target.
    neo_companion_prod_service_account: str = os.getenv("FEEDBACK_NEO_COMPANION_PROD_SERVICE_ACCOUNT", "").strip().lower()
    agent_allowed_hosts: tuple[str, ...] = tuple(value.strip().lower() for value in os.getenv("FEEDBACK_AGENT_ALLOWED_HOSTS", "api.loreal.net").split(",") if value.strip())
    promotion_batch_limit: int = int(os.getenv("FEEDBACK_PROMOTION_BATCH_LIMIT", "500"))
    # Deprecated compatibility setting. All environment runs use the same reviewer permissions.
    prod_retest_reviewers: tuple[str, ...] = tuple(value.strip().lower() for value in os.getenv("FEEDBACK_PROD_RETEST_REVIEWERS", "").split(",") if value.strip())
    read_cache_ttl_seconds: int = int(os.getenv("FEEDBACK_READ_CACHE_TTL_SECONDS", "30"))
    workflow_worker_enabled: bool = os.getenv("FEEDBACK_WORKER_ENABLED", "true").lower() == "true"
    workflow_poll_seconds: int = int(os.getenv("FEEDBACK_WORKER_POLL_SECONDS", "15"))
    evidence_version: str = os.getenv("FEEDBACK_EVIDENCE_VERSION", "parsed-docs-current")
    evidence_backend: str = os.getenv("FEEDBACK_EVIDENCE_BACKEND", "neo4j").strip().lower()
    neo4j_env_file: str = os.getenv("FEEDBACK_NEO4J_ENV_FILE", "")
    neo4j_uri: str = os.getenv("FEEDBACK_NEO4J_URI", os.getenv("NEO4J_URI", ""))
    neo4j_username: str = os.getenv("FEEDBACK_NEO4J_USERNAME", os.getenv("NEO4J_USERNAME", ""))
    neo4j_password: str = os.getenv("FEEDBACK_NEO4J_PASSWORD", os.getenv("NEO4J_PASSWORD", ""))
    neo4j_database: str = os.getenv("FEEDBACK_NEO4J_DATABASE", "")
    neo4j_document_prefix: str = os.getenv("FEEDBACK_NEO4J_DOCUMENT_PREFIX", "NEO_RCA-VisualAnalysis__")
    neo4j_vector_index: str = os.getenv("FEEDBACK_NEO4J_VECTOR_INDEX", "vector")
    neo4j_fulltext_index: str = os.getenv("FEEDBACK_NEO4J_FULLTEXT_INDEX", "keyword")
    neo4j_source_manifest: str = os.getenv("FEEDBACK_NEO4J_SOURCE_MANIFEST", "")
    neo4j_corpus_version: str = os.getenv("FEEDBACK_NEO4J_CORPUS_VERSION", "")
    evidence_embedding_model: str = os.getenv("FEEDBACK_EVIDENCE_EMBEDDING_MODEL", "")
    evidence_embedding_api_key: str = os.getenv("FEEDBACK_EVIDENCE_EMBEDDING_API_KEY", "")
    evidence_embedding_base_url: str = os.getenv("FEEDBACK_EVIDENCE_EMBEDDING_BASE_URL", "")
    evidence_query_timeout: int = int(os.getenv("FEEDBACK_EVIDENCE_QUERY_TIMEOUT_SECONDS", "20"))
    fast_docs_dir: str = os.getenv("NEO_FAST_DOCS_DIR", "/home/dhruv/neo-list-triage/parsed_docs")
    vlm_docs_dir: str = os.getenv("NEO_VLM_DOCS_DIR", "/home/dhruv/neo-list-triage/parsed_docs_vlm")
    vlm_gcs_uri: str = os.getenv(
        "NEO_VLM_GCS_URI",
        "gs://oa-apmena-techsandbox-ap-dv-neo-rca-vlm-docs/parsed_docs_vlm",
    ).rstrip("/")
    fast_gcs_uri: str = os.getenv(
        "NEO_FAST_GCS_URI",
        "gs://oa-apmena-techsandbox-ap-dv-neo-rca-vlm-docs/parsed_docs_fast",
    ).rstrip("/")
    btap_gateway_url: str = os.getenv(
        "BTAP_GATEWAY_URL",
        "https://x-np.api.loreal.net/global/it4it/btapgateways-aigateway/v1",
    ).rstrip("/")
    btap_access_token: str = os.getenv("BTAP_ACCESS_TOKEN", "")
    # Separate, explicit RCA gateway identity; never reuse a NEO target setting implicitly.
    btap_service_account: str = os.getenv("BTAP_SERVICE_ACCOUNT", "").strip().lower()
    btap_model: str = os.getenv("BTAP_MODEL", "claude-sonnet-4-6")
    allow_all_origins: bool = os.getenv("FEEDBACK_ALLOW_ALL_ORIGINS", "true").lower() == "true"
    cors_origins: tuple[str, ...] = tuple(
        value.strip()
        for value in os.getenv(
            "FEEDBACK_CORS_ORIGINS",
            "http://localhost:3000,http://localhost:5173",
        ).split(",")
        if value.strip()
    )


settings = Settings()
