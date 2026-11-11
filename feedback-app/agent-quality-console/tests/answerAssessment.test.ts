import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { AnswerVersion, DiagnosisVersion, FeedbackHistory } from '../src/api/feedbackApi';
import type { FeedbackItem, RcaEvidence } from '../src/types';
import { answerVersionLabel, diagnosesForAnswer, selectedDiagnosis } from '../src/utils/answerAssessment';
import { SavedRcaAssessment } from '../src/components/SavedRcaAssessment';
import { RcaRationale } from '../src/components/RcaRationale';
import { FeedbackEvidencePanel } from '../src/components/FeedbackEvidencePanel';

const answer: AnswerVersion = { id: 'answer:retest-2', kind: 'retest', environment: 'nonprod', revision: 2, createdAt: '2026-10-16T10:00:00Z' };
const source: RcaEvidence = { evidence_id: 'NEO-source-2', source: 'Order scheduling.pdf', page: 12, origin: 'neo4j',
  excerpt: 'Short preview', context: 'Full source passage with the actual scheduling rule beyond the short preview.',
  chunk_id: 'chunk-2', document_id: 'NEO_RCA-VisualAnalysis__orders.md', corpus_version: 'manifest-2' };
const diagnosis: DiagnosisVersion = { id: 'rca:retest-2', answerId: answer.id, category: 'reasoning_error',
  defect: 'Wrong scheduling mechanism', rationale: 'The answer conflicts with NEO-source-2.', evidence: [source],
  evidenceBackend: 'neo4j', retrievalStatus: 'available', confidence: 0.9, verified: false, environment: 'nonprod', createdAt: '2026-10-16T10:01:00Z' };
const originalDiagnosis: DiagnosisVersion = { ...diagnosis, id: 'rca:original', answerId: 'original:FDB-1', category: 'incomplete_answer', evidence: [{ evidence_id: 'ORIGINAL', source: 'Original private source.pdf', context: 'Original-only passage' }] };
const history: FeedbackHistory = { answers: [answer], diagnoses: [originalDiagnosis, diagnosis], attempts: [] };
const item = { id: 'FDB-1', suggestedRcaEvidence: originalDiagnosis.evidence, evidence: [{ id: 'CAPTURED', source: 'Captured source.pdf', excerpt: 'Captured original-only passage' }] } as FeedbackItem;

test('the selected answer gets its own diagnosis, never the original classification', () => {
  assert.equal(selectedDiagnosis(history, answer.id)?.category, 'reasoning_error');
  assert.equal(selectedDiagnosis(history, 'original:FDB-1')?.category, 'incomplete_answer');
  assert.equal(selectedDiagnosis(history, 'answer:missing'), undefined);
  assert.deepEqual(diagnosesForAnswer(history), []);
});

test('diagnoses sort by assessment time without mutating server history', () => {
  const newer = { ...diagnosis, id: 'rca:newer', createdAt: '2026-10-17T00:00:00Z', category: 'factual_error' };
  const values = [diagnosis, newer, originalDiagnosis];
  const before = values.map((value) => value.id);
  const data = { ...history, diagnoses: values };
  assert.deepEqual(diagnosesForAnswer(data, answer.id).map((value) => value.id), [newer.id, diagnosis.id]);
  assert.deepEqual(data.diagnoses.map((value) => value.id), before);
});

test('explicit older RCA selection keeps that immutable assessment', () => {
  const newer = { ...diagnosis, id: 'rca:newer', createdAt: '2026-10-17T00:00:00Z', category: 'factual_error' };
  const data = { ...history, diagnoses: [...history.diagnoses, newer] };
  assert.equal(selectedDiagnosis(data, answer.id)?.id, newer.id);
  assert.equal(selectedDiagnosis(data, answer.id, diagnosis.id)?.id, diagnosis.id);
  assert.equal(selectedDiagnosis(data, answer.id, originalDiagnosis.id)?.id, newer.id);
});

test('version labels retain the actual environment/revision and do not invent missing context', () => {
  assert.equal(answerVersionLabel(answer), 'Retest · nonprod · revision 2');
  assert.match(answerVersionLabel({ ...answer, kind: 'submission_edit', environment: 'unknown' }), /^Submission correction · environment not recorded/);
  assert.equal(answerVersionLabel({ ...answer, kind: 'original', environment: 'prod' }), 'Original submission · prod · revision 2');
  assert.equal(answerVersionLabel({ ...answer, createdAt: 'invalid' }, true), answerVersionLabel(answer));
});

test('saved RCA shows the actual category/defect and is explicitly read-only and unverified', () => {
  const html = renderToStaticMarkup(React.createElement(SavedRcaAssessment, { answer, diagnosis, pending: false, onReviewEvidence() {} }));
  assert.match(html, /value="Reasoning Error"/);
  assert.match(html, /value="Wrong scheduling mechanism"/);
  assert.match(html, /readOnly=""/);
  assert.match(html, /AI, not verified/);
  assert.match(html, /Neo4j evidence/);
  assert.match(html, /Review 1 cited source passages/);
  assert.doesNotMatch(html, /Not classified|name="confirmed_rca"|Original-only passage/);
});

test('an unfinished saved answer never borrows an older answer category or evidence', () => {
  const html = renderToStaticMarkup(React.createElement(SavedRcaAssessment, { answer, pending: true, onReviewEvidence() {} }));
  assert.match(html, /Analysis in progress/);
  assert.match(html, /will appear automatically/);
  assert.doesNotMatch(html, /Reasoning Error|NEO-source-2|Not classified/);
});

test('a completed saved answer without a diagnosis is shown honestly rather than as an editable blank', () => {
  const html = renderToStaticMarkup(React.createElement(SavedRcaAssessment, { answer, pending: false, onReviewEvidence() {} }));
  assert.match(html, /No saved diagnosis/);
  assert.match(html, /No RCA was saved for this answer version/);
  assert.doesNotMatch(html, /Run RCA|Not classified/);
});

test('unavailable source retrieval is distinguished from a diagnosis with actual citations', () => {
  const unavailable = { ...diagnosis, evidence: [], retrievalStatus: 'unavailable' as const };
  const html = renderToStaticMarkup(React.createElement(SavedRcaAssessment, { answer, diagnosis: unavailable, pending: false, onReviewEvidence() {} }));
  assert.match(html, /Source retrieval was unavailable/);
  assert.doesNotMatch(html, /Review 1 cited source passages/);
});

test('selected-answer evidence excludes both original-run and original-RCA passages', () => {
  const html = renderToStaticMarkup(React.createElement(FeedbackEvidencePanel, {
    item, open: true, onOpenChange() {}, assessment: { answerId: answer.id, diagnosisId: diagnosis.id, label: answerVersionLabel(answer), evidence: [source] },
  }));
  assert.match(html, /Order scheduling.pdf/);
  assert.match(html, /Page 12/);
  assert.match(html, /data-evidence-id="NEO-source-2"/);
  assert.match(html, /Full source passage with the actual scheduling rule/);
  assert.doesNotMatch(html, /Original private source.pdf|Captured source.pdf|Original-only passage|Captured original-only passage/);
});

test('a selected version with no evidence never falls back to another version evidence', () => {
  const html = renderToStaticMarkup(React.createElement(FeedbackEvidencePanel, {
    item, open: true, onOpenChange() {}, assessment: { answerId: answer.id, label: 'Saved retest', evidence: [] },
  }));
  assert.match(html, /No source passages were saved for this assessment version/);
  assert.doesNotMatch(html, /Original private source.pdf|Captured source.pdf|Order scheduling.pdf/);
});

test('the explicit submission view still retains its captured and RCA references', () => {
  const html = renderToStaticMarkup(React.createElement(FeedbackEvidencePanel, { item, open: true, onOpenChange() {} }));
  assert.match(html, /Original private source.pdf/);
  assert.match(html, /Captured source.pdf/);
  assert.doesNotMatch(html, /Order scheduling.pdf/);
});

test('rationale citation buttons link only supplied IDs, not arbitrary text or URLs', () => {
  const html = renderToStaticMarkup(React.createElement(RcaRationale, {
    text: 'Use NEO-source-2; an unprovided NEO-other is not a citation. <script>alert(1)</script>',
    evidence: [source], onCitationClick() {},
  }));
  assert.equal((html.match(/<button/g) || []).length, 1);
  assert.match(html, /aria-label="Review citation NEO-source-2"/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>|href=/);
});

test('citation IDs containing regex punctuation are treated literally and overlaps prefer the full ID', () => {
  const html = renderToStaticMarkup(React.createElement(RcaRationale, {
    text: 'D10, D1, DOC-[1]+ and an unmatched DOC-111.',
    evidence: [{ evidence_id: 'D1' }, { evidence_id: 'D10' }, { evidence_id: 'DOC-[1]+' }], onCitationClick() {},
  }));
  assert.equal((html.match(/<button/g) || []).length, 3);
  assert.match(html, /Review citation D10/);
  assert.match(html, /Review citation DOC-\[1\]\+/);
});

test('reporter-style rationale without private evidence controls remains plain escaped text', () => {
  const html = renderToStaticMarkup(React.createElement(RcaRationale, { text: diagnosis.rationale }));
  assert.match(html, /NEO-source-2/);
  assert.doesNotMatch(html, /<button|Order scheduling.pdf|Full source passage/);
});

test('known citation IDs are not linked as prefixes or substrings of unknown IDs', () => {
  const html = renderToStaticMarkup(React.createElement(RcaRationale, {
    text: 'D10 and prefixD1 and D1-suffix are not D1. Only (D1) is a supplied citation.',
    evidence: [{ evidence_id: 'D1' }], onCitationClick() {},
  }));
  assert.equal((html.match(/<button/g) || []).length, 2);
  assert.match(html, /D10 and prefixD1 and D1-suffix/);
});
