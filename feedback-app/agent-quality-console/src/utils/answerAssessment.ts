import type { AnswerVersion, DiagnosisVersion, FeedbackHistory } from '../api/feedbackApi';

export function diagnosesForAnswer(history: FeedbackHistory | null | undefined, answerId?: string): DiagnosisVersion[] {
  if (!answerId) return [];
  return (history?.diagnoses || []).filter((diagnosis) => diagnosis.answerId === answerId).sort((left, right) => {
    const leftTime = Date.parse(left.createdAt) || 0;
    const rightTime = Date.parse(right.createdAt) || 0;
    return rightTime - leftTime || right.id.localeCompare(left.id);
  });
}

export function selectedDiagnosis(history: FeedbackHistory | null | undefined, answerId?: string, diagnosisId?: string): DiagnosisVersion | undefined {
  const diagnoses = diagnosesForAnswer(history, answerId);
  return diagnoses.find((diagnosis) => diagnosis.id === diagnosisId) || diagnoses[0];
}

export function answerVersionLabel(answer: AnswerVersion, withDate = false): string {
  const kind = answer.kind === 'original' ? 'Original submission' : answer.kind === 'submission_edit' ? 'Submission correction' : 'Retest';
  const environment = answer.environment === 'unknown' ? 'environment not recorded' : answer.environment;
  const date = new Date(answer.createdAt);
  const stamp = withDate && !Number.isNaN(date.getTime()) ? ` · ${date.toLocaleString()}` : '';
  return `${kind} · ${environment} · revision ${answer.revision}${stamp}`;
}
