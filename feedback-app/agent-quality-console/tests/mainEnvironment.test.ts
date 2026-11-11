import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';

test('owner list shows the promoted main environment and retains the original reported label', () => {
  return readFile(new URL('../src/components/MyFeedbackView.tsx', import.meta.url), 'utf8').then(source => {
    assert.match(source, /item\.mainEnvironmentLabel \|\|/);
    assert.match(source, /Promoted · originally/);
    assert.match(source, /Main environment: \{selectedFeedback\.mainEnvironmentLabel/);
  assert.match(source, /The original submission and answers remain unchanged/);
  });
});

test('reporter history defaults to the explicit promoted target while original details remain separately labelled', async () => {
  const source = await import('node:fs/promises').then(fs => fs.readFile(new URL('../src/components/MyFeedbackView.tsx', import.meta.url), 'utf8'));
  assert.match(source, /environmentId \|\| selectedFeedback\?\.mainEnvironmentId \|\| selectedFeedback\?\.environmentId/);
    assert.match(source, /context=\{selectedFeedback\}/);
  assert.match(source, /Originally reported in/);
  const history = await import('node:fs/promises').then(fs => fs.readFile(new URL('../src/components/FeedbackDetailView.tsx', import.meta.url), 'utf8'));
  assert.match(history, /item\.mainEnvironmentId/);
  assert.match(history, /context=\{item\}/);
  assert.match(await readFile(new URL('../src/utils/answerReview.ts', import.meta.url), 'utf8'), /context\.mainEnvironmentId \|\| context\.environmentId/);
  const historyView = await readFile(new URL('../src/components/AnswerHistoryView.tsx', import.meta.url), 'utf8');
  assert.match(historyView, /\['fixed', 'Correct'\]/);
  assert.match(historyView, /\['partially_fixed', 'Partially correct'\]/);
  assert.match(historyView, /\['still_incorrect', 'Incorrect'\]/);
});
