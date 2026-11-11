from unittest.mock import Mock

import pytest

from scripts.init_access_grants import SCHEMA, approved_grants, initialize
from app.config import settings


def test_seed_accepts_only_explicit_company_roles_and_preserves_inactive_grants(monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'google_iam_domains', ('company.example',))
    result = approved_grants([{'email': 'REVIEWER@company.example', 'role': 'reviewer'},
        {'email': 'reporter@company.example', 'role': 'reporter', 'active': False}])
    assert result[0]['email'] == 'reviewer@company.example' and not result[1]['active']


@pytest.mark.parametrize('row', [
    {'email': 'person@outside.example', 'role': 'reviewer'},
    {'email': 'person@company.example', 'role': 'admin'},
    {'email': 'person@company.example', 'role': 'reviewer', 'feedbackOwnerEmail': 'someone@company.example'},
])
def test_seed_rejects_implicit_admin_noncompany_and_owner_aliases(row, monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'google_iam_domains', ('company.example',))
    with pytest.raises(ValueError): approved_grants([row])


def test_migration_creates_only_access_storage_and_cannot_reactivate_or_overwrite_existing_rows(monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'google_iam_domains', ('company.example',))
    client = Mock(); client.get_table.return_value.schema = SCHEMA
    initialize(client, approved_grants([{'email': 'person@company.example', 'role': 'reviewer'}]))
    sql = client.query.call_args.args[0]
    assert 'WHEN NOT MATCHED THEN INSERT' in sql
    assert 'WHEN MATCHED' not in sql and 'DELETE' not in sql and 'feedback_items' not in sql
    assert client.create_table.call_args.kwargs['exists_ok']
