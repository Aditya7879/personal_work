import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import type { AnswerReview, FeedbackHistory } from '../src/api/feedbackApi';
import { answerReview, reviewAnswer, reviewMessage, answerUserVerdict, answerEligibilityNote, confirmationVerdict } from '../src/utils/answerReview';

const eligible: AnswerReview = { state: 'available', environmentId: 'neo-prod', environmentKind: 'prod',
  environmentLabel: 'Production', revision: 2, attemptId: 'JOB-CURRENT', answerId: 'answer:JOB-CURRENT' };
const history: FeedbackHistory = { sharingPolicy: 'automatic', latestConfirmableAttemptId: 'JOB-CURRENT',
  answerReview: eligible, answers: [
    { id: 'answer:JOB-CURRENT', kind: 'retest', attemptId: 'JOB-CURRENT', environment: 'prod', environmentId: 'neo-prod',
      revision: 2, answer: 'Current Production answer', createdAt: '2026-11-03T00:00:00Z' },
    { id: 'answer:OTHER', kind: 'retest', attemptId: 'OTHER', environment: 'nonprod', environmentId: 'other',
      revision: 2, answer: 'Later unrelated result', createdAt: '2026-11-03T01:00:00Z' },
  ], attempts: [{ id: 'JOB-CURRENT', kind: 'retest', status: 'completed', environment: 'prod', environmentId: 'neo-prod',
    revision: 2, createdAt: '2026-11-03T00:00:00Z' }], diagnoses: [] };

test('fresh server review context wins over a stale reporter record or list environment', () => {
  const result = answerReview(history, { revision: 1, environment: 'nonprod', environmentId: 'neo-nonprod' });
  assert.equal(result, eligible);
  assert.equal(reviewAnswer(history, result)?.id, 'answer:JOB-CURRENT');
});

test('review opens the server-selected eligible answer rather than the newest unrelated answer', () => {
  assert.equal(reviewAnswer(history, eligible)?.answer, 'Current Production answer');
  assert.equal(history.answers.at(-1)?.id, 'answer:OTHER');
});

test('missing or blank saved answers never become reviewable through a badge click', () => {
  assert.equal(reviewAnswer({ ...history, answers: [{ ...history.answers[0], answer: '  ' }] }, eligible), undefined);
  assert.equal(reviewAnswer(history, { ...eligible, attemptId: null }), undefined);
});

test('RCA-only and processing states explain why response controls are unavailable', () => {
  const empty: FeedbackHistory = { answers: [], diagnoses: [], attempts: [], sharingPolicy: 'automatic' };
  assert.equal(answerReview(empty, { environment: 'prod', environmentId: 'neo-prod' }).state, 'no_fresh_answer');
  assert.match(reviewMessage({ ...eligible, state: 'no_fresh_answer' }), /Running RCA only does not create/);
  assert.match(reviewMessage({ ...eligible, state: 'processing' }), /still processing/);
});

test('already recorded responses are displayed rather than turned into a second editable verdict', () => {
  assert.equal(answerReview({ ...history, answerReview: { ...eligible, state: 'already_responded', confirmation: 'fixed' } }, {}).state, 'already_responded');
  assert.match(reviewMessage({ ...eligible, state: 'already_responded' }), /already been recorded/);
});

test('unavailable review states each have an actionable explanation', () => {
  for (const state of ['outdated_revision', 'different_environment', 'environment_unknown', 'unavailable'] as const) {
    assert.ok(reviewMessage({ ...eligible, state }).length > 40);
  }
});

test('Your verdict is a native read/open action, not an original-verdict mutation', async () => {
  const source = await readFile(new URL('../src/components/MyFeedbackView.tsx', import.meta.url), 'utf8');
  assert.match(source, /Your verdict: \{latestReporterVerdict\(item\)\}<\/button>/);
  assert.match(source, /onClick=\{\(\) => openReview\(item\.id\)\}/);
  assert.match(source, /The submitted verdict and AI\/RCA assessments are separate/);
  assert.doesNotMatch(source, /updateMyFeedback|confirmRetest/);
});

test('manual review forces a history refresh while automatic discovery preserves typed replies', async () => {
  const source = await readFile(new URL('../src/components/AnswerHistoryView.tsx', import.meta.url), 'utf8');
  assert.match(source, /manualReview\.current = true/);
  assert.match(source, /void load\(true\)/);
  assert.match(source, /!comment\.trim\(\)/);
  assert.match(source, /Updated answer review/);
  assert.match(source, /attempt\.id === latestConfirmable/);
  assert.match(source, /attempt\.status === 'completed'/);
});

test('a human verdict belongs to its answer variant and never comes from the AI comparison', () => {
  const first = { ...history.answers[0], attemptId: 'JOB-CORRECT' };
  const second = { ...history.answers[0], id: 'answer:JOB-WRONG', attemptId: 'JOB-WRONG' };
  const value: FeedbackHistory = { ...history, answers: [first, second], attempts: [
    { ...history.attempts[0], id: 'JOB-CORRECT', confirmation: 'fixed', assessment: 'still_incorrect' },
    { ...history.attempts[0], id: 'JOB-WRONG', confirmation: 'still_incorrect', assessment: 'appears_fixed' },
  ] };
  assert.equal(answerUserVerdict(first, value), 'Correct');
  assert.equal(answerUserVerdict(second, value), 'Incorrect');
  assert.equal(value.attempts[0].assessment, 'still_incorrect');
  assert.equal(value.attempts[1].assessment, 'appears_fixed');
});

test('an unreviewed new answer does not inherit the submitted or previous answer verdict', () => {
  assert.equal(answerUserVerdict(history.answers[0], history), 'Not yet reviewed');
  assert.equal(confirmationVerdict('partially_fixed'), 'Partially correct');
});

test('the FDB-1DC4EF03 warning states the actual historical/current revision mismatch', () => {
  const value = { ...history.answers[0], revision: 1, environmentLabel: 'Production' };
  const message = answerEligibilityNote(value, { ...eligible, revision: 3 });
  assert.match(message || '', /input revision 1/);
  assert.match(message || '', /current submission is revision 3/);
  assert.doesNotMatch(message || '', /differs or is unknown/);
});

test('passive polling does not enter the explicit-refresh disabled state', async () => {
  const source = await readFile(new URL('../src/components/AnswerHistoryView.tsx', import.meta.url), 'utf8');
  assert.match(source, /if \(refresh\) setHistoryRefreshing\(true\)/);
  assert.match(source, /if \(!refresh && inFlightScope\.current === scope\) return/);
  assert.match(source, /if \(mutationInFlight\.current\) return/);
  assert.match(source, /expected|verdictEdit\?\.previous/);
  assert.match(source, /AI comparison for this answer/);
  assert.match(source, /Your verdict for this answer/);
});

test('ordinary View clears a previous explicit review request so the workspace filter stays authoritative', async () => {
  const source = await readFile(new URL('../src/components/MyFeedbackView.tsx', import.meta.url), 'utf8');
  assert.match(source, /setReviewFocused\(false\); setReviewRequest\(null\); setSelectedId\(item\.id\)/);
});
