"""Verified per-feedback identity links; original reporter labels stay immutable."""
from __future__ import annotations

import re

from google.cloud import bigquery


LINK_TABLE = 'feedback_owner_links'
EVENT_TABLE = 'feedback_owner_events'

LINK_SCHEMA = [bigquery.SchemaField(name, kind) for name, kind in [
    ('id', 'STRING'), ('feedback_id', 'STRING'), ('agent_id', 'STRING'),
    ('source_reporter', 'STRING'), ('owner_email', 'STRING'), ('active', 'BOOL'),
    ('verified', 'BOOL'), ('verification_method', 'STRING'), ('approved_by', 'STRING'),
    ('approval_hash', 'STRING'), ('created_at', 'TIMESTAMP'), ('updated_at', 'TIMESTAMP'),
]]
EVENT_SCHEMA = [bigquery.SchemaField(name, kind) for name, kind in [
    ('id', 'STRING'), ('feedback_id', 'STRING'), ('actor', 'STRING'), ('action', 'STRING'),
    ('before_json', 'STRING'), ('after_json', 'STRING'), ('created_at', 'TIMESTAMP'),
]]


def ensure_ownership_tables(client, dataset_ref: str) -> None:
    """Add only dedicated identity-link/audit storage; never rewrite source rows."""
    for name, schema in [(LINK_TABLE, LINK_SCHEMA), (EVENT_TABLE, EVENT_SCHEMA)]:
        client.create_table(bigquery.Table(f'{dataset_ref}.{name}', schema=schema), exists_ok=True)


def owner_scope(repo, alias: str, *, parameter: str = 'reporters', scalar: bool = False) -> str:
    """One guard for lists, details, edits, history, notifications and confirmation.

    Only a single verified link for the exact feedback/source/agent is eligible.
    Never map another email owner, a missing source owner, or a duplicate link.
    Caller principals still come only from the authenticated request, not the UI.
    """
    if not re.fullmatch(r'[a-z][a-z0-9_]*', alias) or not re.fullmatch(r'[a-z][a-z0-9_]*', parameter):
        raise ValueError('Ownership SQL identifiers must be internal constants')
    source = f'LOWER(TRIM({alias}.reporter))'
    direct = f'{source} = LOWER(TRIM(@{parameter}))' if scalar else f'{source} IN UNNEST(@{parameter})'
    linked = f'o.owner_email = LOWER(TRIM(@{parameter}))' if scalar else f'o.owner_email IN UNNEST(@{parameter})'
    return f"""({direct} OR (
        NULLIF(TRIM({alias}.reporter), '') IS NOT NULL AND STRPOS({alias}.reporter, '@')=0
        AND EXISTS(SELECT 1 FROM (
            SELECT l.*,COUNT(*) OVER(PARTITION BY feedback_id) AS owner_link_count
            FROM `{repo.workflow_table(LINK_TABLE)}` l) o
            WHERE o.feedback_id={alias}.feedback_id AND o.agent_id={alias}.agent_id
                AND o.source_reporter={source} AND o.owner_link_count=1
                AND o.active IS TRUE AND o.verified IS TRUE AND {linked})))"""
