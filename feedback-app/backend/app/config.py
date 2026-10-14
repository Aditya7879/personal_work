from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    project_id: str = os.getenv("GCP_PROJECT_ID", "oa-apmena-techsandbox-ap-dv")
    dataset: str = os.getenv("BIGQUERY_DATASET", "agent_quality")
    location: str = os.getenv("BIGQUERY_LOCATION", "europe-west1")
    default_agent_id: str = os.getenv("DEFAULT_AGENT_ID", "neo-rules-agent")
    neo_agent_api_url: str = os.getenv("NEO_AGENT_API_URL", "http://localhost:8000").rstrip("/")
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
