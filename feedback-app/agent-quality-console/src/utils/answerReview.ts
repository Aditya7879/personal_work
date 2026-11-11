import type { AnswerReview, AnswerVersion, BusinessContext, FeedbackHistory } from '../api/feedbackApi';

export function confirmationVerdict(value?: string | null): string | undefined {
  return ({ fixed: 'Correct', partially_fixed: 'Partially correct', still_incorrect: 'Incorrect' } as Record<string, string>)[value || ''];
}

/** A human opinion on this exact variant, never the AI comparison or original report label. */
export function answerUserVerdict(answer?: AnswerVersion, history?: FeedbackHistory | null): string {
  if (!answer) return 'Not yet reviewed';
  if (answer.kind === 'retest') {
    const attempt = history?.attempts.find(row => row.id === answer.attemptId);
    return attempt ? confirmationVerdict(attempt.confirmation) || 'Not yet reviewed' : answer.userVerdict || 'Not yet reviewed';
  }
  return answer.userVerdict || 'Not recorded';
}

export function answerEligibilityNote(answer: AnswerVersion, review: AnswerReview): string | undefined {
  const label = answer.environmentLabel || (answer.environment === 'prod' ? 'Production' : answer.environment === 'nonprod' ? 'Non-production' : 'Unknown environment');
  if (answer.revision !== review.revision) return `Historical ${label} answer · input revision ${answer.revision}. The current submission is revision ${review.revision}, so this answer cannot resolve the current report. Its saved user verdict, AI assessment and RCA remain specific to this version.`;
  if (answer.environmentId !== review.environmentId || answer.environment !== review.environmentKind) return `This answer is from ${label}, not the report's current main environment (${review.environmentLabel || review.environmentId || 'not recorded'}). It cannot resolve the current report.`;
  return undefined;
}

/** Use fresh server eligibility, not the submitted verdict or current table filter. */
export function answerReview(history: FeedbackHistory | null, context: BusinessContext): AnswerReview {
  if (history?.answerReview) return history.answerReview;
  const review: AnswerReview = { state: 'no_fresh_answer', environmentId: context.mainEnvironmentId || context.environmentId,
    environmentKind: context.mainEnvironmentKind || context.environment || 'unknown',
    environmentLabel: context.mainEnvironmentLabel || context.environmentLabel, revision: context.revision || 1 };
  // Compatibility with a cached/older response; the write API always rechecks eligibility.
  const latestId = history?.sharingPolicy === 'automatic' ? history.latestConfirmableAttemptId : context.latestPublishedAttemptId;
  const eligible = history?.attempts.find(row => row.id === latestId && row.kind === 'retest' && row.status === 'completed');
  if (eligible) return { ...review, state: eligible.confirmation ? 'already_responded' : 'available',
    attemptId: eligible.id, answerId: `answer:${eligible.id}`, confirmation: eligible.confirmation };
  const latest = history?.attempts.find(row => row.kind === 'retest');
  if (!review.environmentId || review.environmentKind === 'unknown') return { ...review, state: 'environment_unknown' };
  if (latest?.revision !== undefined && latest.revision !== review.revision) return { ...review, state: 'outdated_revision' };
  if (latest && (latest.environmentId !== review.environmentId || latest.environment !== review.environmentKind)) return { ...review, state: 'different_environment' };
  if (latest && ['queued', 'running'].includes(latest.status)) return { ...review, state: 'processing' };
  if (latest && ['failed', 'cancelled'].includes(latest.status)) return { ...review, state: 'unavailable' };
  return review;
}

export function reviewMessage(review: AnswerReview): string {
  const environment = review.environmentLabel || (review.environmentKind === 'prod' ? 'Production' : review.environmentKind === 'nonprod' ? 'Non-production' : 'the current environment');
  switch (review.state) {
    case 'available': return `Updated ${environment} answer ready for your review.`;
    case 'already_responded': return 'Your response to the latest updated answer has already been recorded.';
    case 'processing': return 'A fresh answer and its checks are still processing. The review choices will appear when it completes.';
    case 'outdated_revision': return 'The saved result belongs to an older submission revision. A fresh answer for the current revision is needed.';
    case 'different_environment': return `The saved retest is from a different environment. A completed result in ${environment} is needed to confirm this report.`;
    case 'environment_unknown': return 'The current main environment is not recorded. The review team must confirm its exact environment first.';
    case 'unavailable': return 'The latest retest did not complete successfully. Its available history is preserved, but it cannot be confirmed yet.';
    default: return 'No completed fresh answer is available to review yet. Running RCA only does not create a new agent answer.';
  }
}

export function reviewAnswer(history: FeedbackHistory | null, review: AnswerReview) {
  if (!review.attemptId) return undefined;
  return history?.answers.find(row => row.kind === 'retest' && row.attemptId === review.attemptId && !!row.answer?.trim());
}
