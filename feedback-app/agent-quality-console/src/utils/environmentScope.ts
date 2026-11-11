import type { AnswerVersion, BusinessContext, FeedbackHistory } from '../api/feedbackApi';

/** Never equate two named environments just because both are non-production. */
export function answerEnvironmentId(answer: AnswerVersion, history: FeedbackHistory | null, context: BusinessContext): string | undefined {
  if (answer.environmentId) return answer.environmentId;
  const attempt = history?.attempts.find((attempt) => attempt.id === answer.attemptId);
  if (attempt?.environmentId) return attempt.environmentId;
  if (answer.kind !== 'retest' && answer.environment === context.environment && answer.revision === (context.revision || 1)) return context.environmentId || undefined;
  return undefined;
}

export function answersInEnvironment(history: FeedbackHistory | null, context: BusinessContext, environmentId?: string): AnswerVersion[] {
  return history?.answers.filter((answer) => !environmentId || answerEnvironmentId(answer, history, context) === environmentId) || [];
}
