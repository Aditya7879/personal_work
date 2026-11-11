"""BigQuery is the sole source of application roles for verified Google users."""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from functools import lru_cache
import json
import re
from threading import Lock
import time
import uuid

from fastapi import HTTPException
from google.api_core.exceptions import Aborted, BadRequest, Conflict
from google.cloud import bigquery

from .config import settings

APPLICATION_ROLES = {'reporter','reviewer','demo_admin'}


def access_table_ref() -> str:
    value = settings.authz_table or f"{settings.project_id}.{settings.dataset}.application_access_grants"
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]*\.[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*", value):
        raise HTTPException(503, "Application authorization storage is not configured correctly")
    return value


def access_management_tables() -> tuple[str, str]:
    dataset = access_table_ref().rsplit('.', 1)[0]
    return f'{dataset}.application_access_events', f'{dataset}.application_access_control'


def normalize_principal(value: str) -> str:
    email = value.strip().lower()
    if (len(email) > 320 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+", email)
            or email.count('@') != 1 or email.rsplit('@', 1)[1] not in settings.google_iam_domains):
        raise ValueError('Use an individual email address in an approved company domain')
    return email


def _timestamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime):
        raise ValueError('Invalid access timestamp')
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def public_grant(row: dict, actor: str, now: datetime) -> dict:
    email = normalize_principal(row['email'])
    if row.get('role') not in APPLICATION_ROLES or not isinstance(row.get('active'), bool):
        raise ValueError('Invalid access grant')
    expires, updated, created = (_timestamp(row.get(key)) for key in ('expires_at', 'updated_at', 'created_at'))
    if updated is None:
        raise ValueError('Access grants require an update timestamp')
    return {'email': email, 'displayName': str(row.get('display_name') or '').strip()[:200],
        'role': row['role'], 'active': row['active'], 'expiresAt': expires.isoformat() if expires else None,
        'createdAt': created.isoformat() if created else None, 'updatedAt': updated.isoformat(),
        'updatedBy': str(row.get('updated_by') or ''), 'canEdit': email != actor,
        'status': 'revoked' if not row['active'] else 'expired' if expires and expires <= now else 'active'}


class AccessGrantRepository:
    def __init__(self, client=None, *, clock=time.monotonic, utcnow=lambda: datetime.now(timezone.utc)):
        self._client = client
        self._clock = clock
        self._utcnow = utcnow
        self._lock = Lock()
        self._cache: OrderedDict[tuple[str, str], tuple[float, dict | None]] = OrderedDict()

    def grant(self, email: str, *, refresh: bool = False) -> dict | None:
        table = access_table_ref()
        email = email.strip().lower()
        key = (table, email)
        with self._lock:
            now = self._clock()
            cached = self._cache.get(key)
            if not refresh and cached and cached[0] > now:
                self._cache.move_to_end(key)
                return dict(cached[1]) if cached[1] else None
            self._cache.pop(key, None)
            try:
                if self._client is None:
                    self._client = bigquery.Client(project=settings.project_id)
                rows = list(self._client.query(f"""SELECT email,display_name,role,active,expires_at
                    FROM `{table}` WHERE LOWER(TRIM(email))=@email LIMIT 2""",
                    job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter('email', 'STRING', email)]),
                    location=settings.location).result())
                if len(rows) > 1:
                    raise ValueError('Duplicate principal grants')
                grant, expires = None, None
                if rows:
                    row = dict(rows[0])
                    if row.get('role') not in APPLICATION_ROLES or not isinstance(row.get('active'), bool):
                        raise ValueError('Invalid grant fields')
                    expires = row.get('expires_at')
                    if expires is not None:
                        if not isinstance(expires, datetime):
                            raise ValueError('Invalid grant expiration')
                        if expires.tzinfo is None:
                            expires = expires.replace(tzinfo=timezone.utc)
                    if row['active'] is True and (expires is None or expires > self._utcnow()):
                        grant = {'role': row['role'], 'displayName': str(row.get('display_name') or '').strip()[:200]}
            except Exception:
                # Never fall back to the old environment JSON or a cached expired role.
                raise HTTPException(503, "Application authorization is temporarily unavailable") from None
            ttl = min(30, max(0, settings.authz_cache_ttl_seconds))
            if expires is not None and grant:
                ttl = min(ttl, max(0, (expires - self._utcnow()).total_seconds()))
            if ttl > 0:
                self._cache[key] = (self._clock() + ttl, grant)
                while len(self._cache) > 512:
                    self._cache.popitem(last=False)
            return dict(grant) if grant else None

    def _query(self, sql, parameters=(), **kwargs):
        if self._client is None:
            self._client = bigquery.Client(project=settings.project_id)
        return self._client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=list(parameters)),
            location=settings.location, **kwargs)

    def require_manager(self, actor: str) -> None:
        # Privileged reads never rely on a cached role that may just have been revoked.
        grant = self.grant(actor, refresh=True)
        if not grant or grant['role'] not in {'reviewer','demo_admin'}:
            raise HTTPException(403, 'An active reviewer grant is required to manage access')

    def list_grants(self, actor: str, *, search: str = '', page: int = 1, page_size: int = 25) -> dict:
        self.require_manager(actor)
        table = access_table_ref()
        try:
            rows = list(self._query(f"""WITH grants AS (SELECT *,
                COUNT(*) OVER(PARTITION BY LOWER(TRIM(email))) AS principal_count
                FROM `{table}`)
                SELECT *, COUNT(*) OVER() AS total FROM grants
                WHERE @search='' OR STRPOS(LOWER(email), @search)>0
                OR STRPOS(LOWER(COALESCE(display_name,'')), @search)>0
                ORDER BY LOWER(TRIM(email)) LIMIT @limit OFFSET @offset""", [
                    bigquery.ScalarQueryParameter('search', 'STRING', search.strip().lower()),
                    bigquery.ScalarQueryParameter('limit', 'INT64', page_size),
                    bigquery.ScalarQueryParameter('offset', 'INT64', (page - 1) * page_size)]).result())
            if any(row['principal_count'] != 1 for row in rows):
                raise ValueError('Duplicate principal grants')
            items = [public_grant(dict(row), actor, self._utcnow()) for row in rows]
            return {'items': items, 'total': int(rows[0]['total']) if rows else 0,
                'page': page, 'pageSize': page_size, 'allowedDomains': list(settings.google_iam_domains),
                'propagationSeconds': 30}
        except Exception:
            raise HTTPException(503, 'Application access management is temporarily unavailable') from None

    def save_grant(self, email: str, payload, actor: str, *, create: bool) -> dict:
        email, actor = normalize_principal(email), normalize_principal(actor)
        if email == actor:
            raise HTTPException(409, 'Ask another reviewer to change your own access; self-revocation and self-role changes are blocked')
        table = access_table_ref()
        events, control = access_management_tables()
        event_id = uuid.uuid4().hex
        parameters = [bigquery.ScalarQueryParameter(name, kind, value) for name, kind, value in [
            ('email', 'STRING', email), ('actor', 'STRING', actor), ('display_name', 'STRING', payload.display_name.strip()),
            ('role', 'STRING', payload.role), ('active', 'BOOL', payload.active), ('expires_at', 'TIMESTAMP', payload.expires_at),
            ('expected', 'TIMESTAMP', None if create else payload.expected_updated_at),
            ('creating', 'BOOL', create), ('event_id', 'STRING', event_id)]]
        sql = f"""DECLARE before_state STRING; DECLARE after_state STRING;
            BEGIN TRANSACTION;
            ASSERT (SELECT COUNT(*) FROM `{control}` WHERE scope='application-access')=1 AS 'ACCESS_CONTROL_INVALID';
            -- All administration transactions update this singleton. Concurrent creates,
            -- even for a missing principal, cannot commit duplicate grants from two snapshots.
            UPDATE `{control}` SET revision=revision+1 WHERE scope='application-access';
            ASSERT (SELECT COUNT(*) FROM `{table}` WHERE LOWER(TRIM(email))=@actor)=1 AS 'ACCESS_REVIEWER_REQUIRED';
            ASSERT EXISTS(SELECT 1 FROM `{table}` WHERE LOWER(TRIM(email))=@actor AND role IN ('reviewer','demo_admin')
                AND active IS TRUE AND (expires_at IS NULL OR expires_at>CURRENT_TIMESTAMP())) AS 'ACCESS_REVIEWER_REQUIRED';
            ASSERT NOT EXISTS(SELECT 1 FROM `{table}` GROUP BY LOWER(TRIM(email)) HAVING COUNT(*)>1) AS 'ACCESS_DUPLICATE_GRANTS';
            ASSERT NOT @active OR @expires_at IS NULL OR @expires_at>CURRENT_TIMESTAMP() AS 'ACCESS_EXPIRY_PAST';
            SET before_state=(SELECT TO_JSON_STRING(t) FROM `{table}` t WHERE LOWER(TRIM(email))=@email);
            IF @creating THEN
                ASSERT before_state IS NULL AS 'ACCESS_ALREADY_EXISTS';
                INSERT INTO `{table}`(email,display_name,role,active,expires_at,created_at,updated_at,updated_by)
                VALUES(@email,@display_name,@role,@active,@expires_at,CURRENT_TIMESTAMP(),CURRENT_TIMESTAMP(),@actor);
            ELSE
                ASSERT (SELECT COUNT(*) FROM `{table}` WHERE LOWER(TRIM(email))=@email AND updated_at=@expected)=1 AS 'ACCESS_STALE';
                UPDATE `{table}` SET display_name=@display_name,role=@role,active=@active,expires_at=@expires_at,
                    updated_at=CURRENT_TIMESTAMP(),updated_by=@actor WHERE LOWER(TRIM(email))=@email AND updated_at=@expected;
            END IF;
            SET after_state=(SELECT TO_JSON_STRING(t) FROM `{table}` t WHERE LOWER(TRIM(email))=@email);
            INSERT INTO `{events}`(id,email,actor,action,before_json,after_json,created_at)
                VALUES(@event_id,@email,@actor,IF(@creating,'granted',IF(@active,'updated','revoked')),
                    before_state,after_state,CURRENT_TIMESTAMP());
            COMMIT TRANSACTION;
            SELECT after_state AS grant_json;"""
        try:
            # A stable job ID fences transport retries. Never replay a failed transaction.
            rows = list(self._query(sql, parameters, job_id='access_grant_' + event_id, job_retry=None).result(job_retry=None))
            result = public_grant(json.loads(rows[0]['grant_json']), actor, self._utcnow())
        except (Aborted, Conflict):
            raise HTTPException(409, 'Access changed concurrently. Refresh and review before saving again; no change was automatically replayed') from None
        except BadRequest as exc:
            message = str(exc)
            if 'ACCESS_REVIEWER_REQUIRED' in message:
                raise HTTPException(403, 'Your reviewer grant changed; this access change was not applied') from None
            if any(code in message for code in ('ACCESS_ALREADY_EXISTS', 'ACCESS_STALE', 'ACCESS_DUPLICATE_GRANTS', 'ACCESS_EXPIRY_PAST', 'Transaction is aborted due to concurrent update')):
                raise HTTPException(409, 'The grant already exists, changed, or has an invalid expiry. Refresh and review before saving again; no change was automatically replayed') from None
            raise HTTPException(503, 'Application access management is temporarily unavailable; verify the saved state before trying again') from None
        except Exception:
            raise HTTPException(503, 'Application access management is temporarily unavailable; verify the saved state before trying again') from None
        finally:
            with self._lock:
                self._cache.pop((table, email), None)
                self._cache.pop((table, actor), None)
        return result

    def grant_history(self, email: str, actor: str) -> list[dict]:
        self.require_manager(actor)
        email = normalize_principal(email)
        events, _ = access_management_tables()
        try:
            rows = self._query(f"""SELECT id,actor,action,before_json,after_json,created_at FROM `{events}`
                WHERE email=@email ORDER BY created_at DESC,id DESC LIMIT 50""",
                [bigquery.ScalarQueryParameter('email', 'STRING', email)]).result()
            return [{'id': row['id'], 'actor': row['actor'], 'action': row['action'],
                'createdAt': _timestamp(row['created_at']).isoformat(),
                'before': public_grant(json.loads(row['before_json']), actor, self._utcnow()) if row['before_json'] else None,
                'after': public_grant(json.loads(row['after_json']), actor, self._utcnow())} for row in rows]
        except Exception:
            raise HTTPException(503, 'Access change history is temporarily unavailable') from None


@lru_cache(maxsize=1)
def access_repository() -> AccessGrantRepository:
    return AccessGrantRepository()


def get_access_grant(email: str) -> dict | None:
    return access_repository().grant(email)
