from pathlib import Path
from unittest.mock import Mock

import pytest
from openpyxl import Workbook

from app.bigquery import BigQueryRepository
from scripts.replace_feedback_xlsx import read_feedback_workbook, prepare_rows


HEADERS = ['No.', 'Question', 'Sub-domain', 'User', 'Data source', 'Status', 'Answer status',
           'Expected answer', 'Generated answer', 'Latency (s)', 'Follow-up', 'Remarks (Dev team)',
           'Resolution', 'Status note', 'Language']


def make_workbook(path: Path, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'All Questions'
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    language = workbook.create_sheet('English Questions')
    language.append(HEADERS)
    for row in rows:
        language.append(row)
    workbook.create_sheet('Analysis').append(['Summary only'])
    workbook.save(path)
    workbook.close()


def test_workbook_only_imports_all_questions_and_preserves_updated_fields(tmp_path):
    path = tmp_path / 'updated.xlsx'
    make_workbook(path, [[1, 'Exact question', 'O2C - Orders', 'reporter@example.test', 'training', 'Closed',
                          'Partially correct', 'Expected rule', 'Updated generated answer', 2.75, 'Missing a step',
                          'Private developer note', 'Old resolution', 'Private status note', 'English']])
    payloads = read_feedback_workbook(path)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.answer == 'Updated generated answer'
    assert payload.expected_behavior == 'Expected rule'
    assert payload.user_verdict == 'Partially correct'
    assert payload.run_context['latency_seconds'] == 2.75
    assert payload.run_context['legacy_row'] == '1'
    repo = BigQueryRepository(client=Mock())
    rows, events, originals = prepare_rows(repo, payloads, {'1': 'FDB-EXISTING'})
    assert rows[0]['feedback_id'] == 'FDB-EXISTING'
    assert rows[0]['state'] == 'Triaged'
    assert rows[0]['public_status'] == 'In review'
    assert rows[0]['expected_behavior_verified'] is False
    assert rows[0]['environment'] == 'unknown'
    assert rows[0]['business_domain'] == 'O2C'
    assert rows[0]['business_subdomain'] == 'Orders'
    assert rows[0]['domain_source'] == 'workbook_import'
    assert payload.run_context['sub_domain'] == 'O2C - Orders'
    assert 'Private developer note' in rows[0]['reviewer_notes']
    public = repo._my_feedback_record(repo._record(rows[0]), [])
    assert public['feedbackText'] == 'Missing a step'
    assert 'Private developer note' not in public['feedbackText']
    assert public['legacyContext']['answerStatus'] == 'Partially correct'
    assert originals[0]['id'] == 'original:FDB-EXISTING'
    assert len(events) == 1


def test_empty_or_duplicate_workbook_is_rejected_before_replacement(tmp_path):
    path = tmp_path / 'empty.xlsx'
    make_workbook(path, [])
    with pytest.raises(ValueError, match='No valid feedback'):
        read_feedback_workbook(path)
    row = [1, 'Question', None, None, None, None, 'Wrong', None, 'Answer', None, None, None, None, None, 'English']
    make_workbook(path, [row, row])
    with pytest.raises(ValueError, match='duplicate feedback number'):
        read_feedback_workbook(path)


def test_missing_answer_is_not_silently_dropped(tmp_path):
    path = tmp_path / 'missing.xlsx'
    make_workbook(path, [[1, 'Question']])
    with pytest.raises(ValueError, match='generated answer is missing'):
        read_feedback_workbook(path)
