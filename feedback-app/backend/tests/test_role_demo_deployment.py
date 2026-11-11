from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy'))
try:
    import role_demo as deploy
finally:
    sys.path.pop(0)
from scripts.bootstrap_demo_admin import EVENT_ID, JOB_ID, PROVENANCE, TARGET, apply_bootstrap, reviewed_grants
from scripts.prepare_role_demo import retire_prototype
from test_auth_only_deploy import service


ORIGIN = 'https://neo-feedback-ui-fixture.run.app'


def test_feature_update_changes_only_reviewed_images_and_exact_feature_origin_flags():
    for name in (deploy.API, deploy.UI):
        values = ' '.join(deploy.update_arguments(name, 'reviewed-image', ORIGIN))
        assert '--image=reviewed-image' in values and 'FEEDBACK_ROLE_DEMO_ENABLED=true' in values
        assert ('FEEDBACK_DEMO_FRONTEND_ORIGIN=' in values) is (name == deploy.API)
        for forbidden in ('FEEDBACK_WORKER_ENABLED', '--service-account', '--set-secrets', '--env-vars-file', '--iap', '--no-iap', '--allow-unauthenticated', '--no-invoker-iam-check', '--max-instances', '--traffic'):
            assert forbidden not in values
    with pytest.raises(ValueError): deploy.update_arguments('neo-feedback-demo-api', 'image', ORIGIN)
    with pytest.raises(ValueError): deploy.feature_flags(deploy.API, 'https://user:password@attacker.example')


def test_feature_preservation_never_ignores_auth_secrets_worker_scaling_or_existing_flag_conflicts():
    before = service(); before['spec']['traffic'] = [{'latestRevision': True, 'percent': 100}]
    expected = deploy.expected_service(before, deploy.API, ORIGIN)
    assert before != expected
    changed = deepcopy(expected); changed['spec']['template']['spec']['containers'][0]['image'] = 'new-image'
    assert deploy.runtime_signature(changed) == deploy.runtime_signature(expected)
    for field in ('auth', 'worker', 'secret', 'iap', 'scaling'):
        current = deepcopy(changed)
        if field == 'auth': current['spec']['template']['spec']['containers'][0]['env'][1]['value'] = 'mock'
        if field == 'worker': current['spec']['template']['spec']['containers'][0]['env'][0]['value'] = 'false'
        if field == 'secret': current['spec']['template']['spec']['containers'][0]['env'][2]['valueFrom']['secretKeyRef']['key'] = '2'
        if field == 'iap': current['metadata']['annotations']['run.googleapis.com/iap-enabled'] = 'false'
        if field == 'scaling': current['spec']['template']['metadata']['annotations']['autoscaling.knative.dev/maxScale'] = '2'
        assert deploy.runtime_signature(current) != deploy.runtime_signature(expected)
    conflict = deepcopy(before)
    conflict['spec']['template']['spec']['containers'][0]['env'].append({'name': 'FEEDBACK_ROLE_DEMO_ENABLED', 'value': 'false'})
    with pytest.raises(ValueError): deploy.expected_service(conflict, deploy.API, ORIGIN)


def grant_snapshot():
    return [{'email': TARGET if index == 0 else f'person{index}@loreal.com', 'role': 'reviewer' if index == 0 else 'reporter',
        'active': True, 'expires_at': None, 'fingerprint': index + 10} for index in range(26)]


def test_initial_bootstrap_has_one_fixed_approved_target_and_never_weakens_normal_self_role_protection(monkeypatch):
    from app.config import settings
    monkeypatch.setitem(settings.__dict__, 'project_id', 'oa-apmena-techsandbox-ap-dv')
    monkeypatch.setitem(settings.__dict__, 'dataset', 'agent_quality')
    monkeypatch.setitem(settings.__dict__, 'authz_table', '')
    client = Mock(); client.query.return_value.result.return_value = [{'grant_json': json.dumps({'email': TARGET, 'role': 'demo_admin', 'approval_provenance': PROVENANCE})}]
    result = apply_bootstrap(client, grant_snapshot(), TARGET)
    assert result['otherGrantsChanged'] == 0 and result['normalSelfRoleChangeSafeguardUnchanged']
    call = client.query.call_args; sql = call.args[0]
    assert 'BEGIN TRANSACTION' in sql and 'COMMIT TRANSACTION' in sql and 'BOOTSTRAP_PREVIEW_STALE' in sql
    assert "SET role='demo_admin',updated_at=CURRENT_TIMESTAMP(),updated_by=@actor" in sql
    assert 'display_name=' not in sql and 'expires_at=' not in sql and 'active=' not in sql
    assert 'feedback_items' not in sql and 'feedback_answer_versions' not in sql
    assert 'application_access_events' in sql and 'application_access_control' in sql
    assert call.kwargs['job_id'] == JOB_ID and call.kwargs['job_retry'] is None
    client.query.return_value.result.assert_called_once_with(job_retry=None)
    assert EVENT_ID == next(param.value for param in call.kwargs['job_config'].query_parameters if param.name == 'event')
    client.reset_mock()
    with pytest.raises(ValueError): apply_bootstrap(client, grant_snapshot(), 'other@loreal.com')
    client.query.assert_not_called()


def test_bootstrap_refuses_expiry_revocation_role_directory_and_duplicate_changes():
    for change in ('expiry', 'inactive', 'already-admin', 'missing', 'duplicate'):
        rows = grant_snapshot()
        if change == 'expiry': rows[0]['expires_at'] = datetime.now(timezone.utc).isoformat()
        if change == 'inactive': rows[0]['active'] = False
        if change == 'already-admin': rows[0]['role'] = 'demo_admin'
        if change == 'missing': rows.pop()
        if change == 'duplicate': rows[-1]['email'] = rows[0]['email']
        with pytest.raises(ValueError): reviewed_grants(rows)


def test_password_prototype_retirement_is_only_reviewed_demo_accounts_and_sessions():
    client = Mock(); client.query.return_value.result.side_effect = [[], [{'active': 0, 'sessions': 0}]]
    result = retire_prototype(client, ['BROWSER-FIXTURE-0123456789abcdef'])
    assert result['unknownAccountsChanged'] == 0
    sql = client.query.call_args_list[0].args[0]
    assert '.agent_quality_demo.demo_admin_accounts' in sql and '.agent_quality_demo.demo_admin_sessions' in sql
    assert '.agent_quality.application_access_grants' not in sql and 'WHERE id IN UNNEST(@ids)' in sql
    assert 'PROTOTYPE_ACCOUNT_SCOPE_CHANGED' in sql and client.query.call_args_list[0].kwargs['job_retry'] is None
    with pytest.raises(ValueError): retire_prototype(Mock(), [])
