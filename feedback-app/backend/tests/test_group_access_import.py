from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import settings
from scripts.import_group_access import DirectoryReadError, GroupDirectory, apply_import, build_preview


NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)
GROUP = 'testing@company.example'
RESOURCE = 'groups/group123'


@pytest.fixture(autouse=True)
def company_domain(monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'google_iam_domains', ('company.example',))


def member(email='person@company.example', **changes):
    return {'type':'USER','preferredMemberKey':{'id':email},'roles':[{'name':'MEMBER'}],**changes}


def directory(pages):
    calls = []
    def open_request(request, **_kwargs):
        calls.append(request)
        parsed = urlsplit(request.full_url)
        if parsed.path.endswith('groups:lookup'):
            data = {'name':RESOURCE}
        elif parsed.path == '/v1/' + RESOURCE:
            data = {'name':RESOURCE,'groupKey':{'id':GROUP},'parent':'customers/C123'}
        else:
            token = parse_qs(parsed.query).get('pageToken', [''])[0]
            data = pages[token]
        return BytesIO(json.dumps(data).encode())
    return GroupDirectory('test-token',opener=open_request,now=lambda:NOW), calls


def test_complete_pagination_uses_the_quota_project_and_returns_only_normalized_individuals():
    reader,calls = directory({'':{'memberships':[member('FIRST@company.example')],'nextPageToken':'next'},
        'next':{'memberships':[member('second@company.example')]}})
    snapshot = reader.snapshot(GROUP.upper())
    assert snapshot['complete'] and len(snapshot['members']) == 2
    assert snapshot['members'][0]['email'] == 'first@company.example'
    assert len(calls) == 4
    assert all(call.get_header('X-goog-user-project') == 'oa-apmena-techsandbox-ap-dv' for call in calls)
    assert all(call.get_method() == 'GET' and call.get_header('Authorization') == 'Bearer test-token' for call in calls)
    assert parse_qs(urlsplit(calls[-1].full_url).query)['pageSize'] == ['500']


@pytest.mark.parametrize('bad_member', [member(type='GROUP'),member(type='SERVICE_ACCOUNT'),
    member(preferredMemberKey={'id':'outside@outside.example'}),
    member(preferredMemberKey={'id':'person@company.example','namespace':'identitysources/external'})])
def test_nested_external_or_non_user_members_are_not_silently_granted_access(bad_member):
    reader,_ = directory({'':{'memberships':[bad_member]}})
    with pytest.raises((DirectoryReadError,ValueError)): reader.snapshot(GROUP)


def test_partial_or_looping_directory_results_cannot_be_used_as_a_complete_snapshot():
    reader,_ = directory({'':{'memberships':[member()],'nextPageToken':'same'},
        'same':{'memberships':[],'nextPageToken':'same'}})
    with pytest.raises(DirectoryReadError,match='pagination'): reader.snapshot(GROUP)


def test_group_owner_or_manager_does_not_imply_app_reviewer_and_expiry_is_respected():
    reader,_ = directory({'':{'memberships':[member('owner@company.example',roles=[{'name':'OWNER'}]),
        member('expired@company.example',roles=[{'name':'MEMBER','expiryDetail':{'expireTime':(NOW-timedelta(seconds=1)).isoformat()}}]),
        member('temporary@company.example',roles=[{'name':'MEMBER','expiryDetail':{'expireTime':(NOW+timedelta(days=1)).isoformat()}}])]}})
    snapshot = reader.snapshot(GROUP)
    assert len(snapshot['members']) == 2 and snapshot['expiredMembershipsExcluded'] == 1
    assert snapshot['members'][1]['expiresAt'] == (NOW+timedelta(days=1)).isoformat()
    client=Mock();client.query.return_value.result.return_value=[]
    preview=build_preview(client,snapshot)
    assert preview['roleForNewUsers']=='reporter' and preview['automaticSync'] is False


def snapshot_and_preview(existing_rows=()):
    reader,_ = directory({'':{'memberships':[member('reviewer@company.example'),member('new@company.example')]}})
    snapshot=reader.snapshot(GROUP)
    client=Mock();client.query.return_value.result.return_value=list(existing_rows)
    return snapshot,build_preview(client,snapshot)


def test_existing_roles_inactive_rows_and_expirations_are_preserved_not_reactivated():
    existing=[{'email':'reviewer@company.example','role':'reviewer','active':False,'expires_at':None,'fingerprint':123}]
    snapshot,preview=snapshot_and_preview(existing)
    assert preview['counts']['newReporterGrants']==1
    assert preview['counts']['existingGrantsPreserved']==1 and preview['counts']['existingInactiveOrExpiredPreserved']==1
    client=Mock();client.query.return_value.result.return_value=[{'added':1}]
    result=apply_import(client,preview,snapshot,'operator@company.example',1)
    assert result['added']==1 and result['existingInactiveOrExpiredPreserved']==1
    sql=client.query.call_args.args[0]
    assert 'BEGIN TRANSACTION' in sql and 'COMMIT TRANSACTION' in sql
    assert 'ACCESS_PREVIEW_STALE' in sql and 'DUPLICATE_ACCESS_GRANTS' in sql and 'REVIEWER_REQUIRED' in sql
    assert 'INSERT INTO' in sql and "'reporter'" in sql and 'group_import' in sql and "'one_time'" in sql
    assert 'UPDATE `' + settings.project_id + '.' + settings.dataset + '.application_access_grants`' not in sql
    assert 'feedback_items' not in sql and 'feedback_workflow_jobs' not in sql
    assert 'new@company.example' not in sql
    assert client.query.call_args.kwargs['job_retry'] is None
    client.query.return_value.result.assert_called_once_with(job_retry=None)


def test_existing_demo_admin_is_preserved_but_group_import_still_creates_only_reporters():
    existing = [{'email': 'reviewer@company.example', 'role': 'demo_admin', 'active': True, 'expires_at': None, 'fingerprint': 123}]
    _, preview = snapshot_and_preview(existing)
    assert preview['counts']['existingGrantsPreserved'] == 1 and preview['counts']['newReporterGrants'] == 1
    assert preview['roleForNewUsers'] == 'reporter' and preview['automaticSync'] is False


def test_empty_existing_array_has_an_explicit_struct_type_and_does_not_enable_sync():
    snapshot,preview=snapshot_and_preview()
    client=Mock();client.query.return_value.result.return_value=[{'added':2}]
    result=apply_import(client,preview,snapshot,'operator@company.example',2)
    assert result['automaticSync'] is False
    config=client.query.call_args.kwargs['job_config'].to_api_repr()
    existing=next(param for param in config['query']['queryParameters'] if param['name']=='existing')
    assert existing['parameterType']['arrayType']['type']=='STRUCT'
    assert [field['name'] for field in existing['parameterType']['arrayType']['structTypes']]==['email','fingerprint']


def test_membership_or_approved_count_changes_fail_before_any_write():
    snapshot,preview=snapshot_and_preview()
    for changed,count in [({**snapshot,'membershipHash':'changed'},2),(snapshot,99),({**snapshot,'complete':False},2)]:
        client=Mock()
        with pytest.raises(ValueError): apply_import(client,preview,changed,'operator@company.example',count)
        client.query.assert_not_called()


def test_existing_duplicate_grants_fail_closed_before_import_planning():
    reader,_=directory({'':{'memberships':[member()]}});snapshot=reader.snapshot(GROUP)
    row={'email':'person@company.example','role':'reporter','active':True,'expires_at':None,'fingerprint':1}
    client=Mock();client.query.return_value.result.return_value=[row,row]
    with pytest.raises(ValueError):build_preview(client,snapshot)
