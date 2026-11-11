"""Real Google reviewers manage application access; never cloud IAM or owner aliases."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from .access_repository import access_repository, normalize_principal
from .config import settings


class AccessGrantInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    display_name: str = Field(default='', max_length=200)
    role: Literal['reporter', 'reviewer', 'demo_admin'] = 'reporter'
    active: StrictBool = True
    expires_at: datetime | None = None

    @field_validator('expires_at')
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('An expiry must include its timezone')
        return value


class AccessGrantCreate(AccessGrantInput):
    email: str = Field(min_length=3, max_length=320)

    @field_validator('email')
    @classmethod
    def company_email(cls, value):
        return normalize_principal(value)


class AccessGrantUpdate(AccessGrantInput):
    expected_updated_at: datetime

    @field_validator('expected_updated_at')
    @classmethod
    def version_timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError('The saved update timestamp must include its timezone')
        return value


def _manager(request: Request):
    user = request.state.user
    if settings.auth_mode != 'google_iam' or user.role != 'reviewer' or user.presenter_email:
        raise HTTPException(403, 'Access management requires your real Google reviewer identity, not a demo profile')
    return user


access_router = APIRouter()


@access_router.get('/api/access-grants')
def list_access_grants(request: Request, search: str = Query(default='', max_length=200),
        page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100),
        repo=Depends(access_repository)):
    user = _manager(request)
    return repo.list_grants(user.email, search=search, page=page, page_size=page_size)


@access_router.post('/api/access-grants', status_code=201)
def create_access_grant(payload: AccessGrantCreate, request: Request, repo=Depends(access_repository)):
    user = _manager(request)
    return repo.save_grant(payload.email, payload, user.email, create=True)


@access_router.patch('/api/access-grants/{email}')
def update_access_grant(email: str, payload: AccessGrantUpdate, request: Request, repo=Depends(access_repository)):
    user = _manager(request)
    try:
        email = normalize_principal(email)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return repo.save_grant(email, payload, user.email, create=False)


@access_router.get('/api/access-grants/{email}/history')
def access_grant_history(email: str, request: Request, repo=Depends(access_repository)):
    user = _manager(request)
    try:
        email = normalize_principal(email)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return repo.grant_history(email, user.email)
