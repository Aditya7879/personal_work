import React, { useEffect, useState } from 'react';
import { AnimatePresence } from 'motion/react';
import { formatRcaLabel } from '../utils/formatRcaLabel';
import { FeedbackItem, ViewPath } from '../types';
import { DiagnosisVersion, GoldenDatasetRecord } from '../api/feedbackApi';
import { BusinessDomainPanel } from './BusinessDomainPanel';
import { AnswerHistorySelection, AnswerHistoryView } from './AnswerHistoryView';
import { CollapsibleSection } from './CollapsibleSection';
import { ContentPreview } from './ContentPreview';
import { SubmissionContextCard } from './SubmissionContextCard';
import { EvidenceAssessment, EvidenceFocusRequest, FeedbackEvidencePanel } from './FeedbackEvidencePanel';
import { SavedRcaAssessment } from './SavedRcaAssessment';
import { RcaRationale } from './RcaRationale';
import { answerVersionLabel, selectedDiagnosis } from '../utils/answerAssessment';
import { AnimatedDiv, AnimatedSection } from './UiMotion';
import { answersInEnvironment } from '../utils/environmentScope';
import { ArrowLeft, BookOpen, RotateCcw } from 'lucide-react';
import { ActionButton } from './ActionButton';
import { useUnsavedDemoDraft } from '../utils/unsavedDemoDrafts';

interface FeedbackDetailViewProps {
  environmentId?: string;
  environmentName?: string;
  item: FeedbackItem;
  datasets: GoldenDatasetRecord[];
  onNavigate: (view: ViewPath, targetId?: string) => void;
  onPromoteToCandidate?: (item: FeedbackItem, datasetId: string) => Promise<void>;
  onSaveTriage?: (id: string, updates: Record<string, unknown>) => Promise<void>;
  onSuggestRootCause?: (id: string) => Promise<FeedbackItem | void>;
  onDataChanged: () => Promise<void>;
}

export const FeedbackDetailView: React.FC<FeedbackDetailViewProps> = ({
  item,
  datasets,
  onNavigate,
  onPromoteToCandidate,
  onSaveTriage,
  onSuggestRootCause,
  onDataChanged,
  environmentId,
  environmentName,
}) => {
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [historySelection, setHistorySelection] = useState<AnswerHistorySelection | null>(null);
  const [historySelectedId, setHistorySelectedId] = useState('');
  const [assessmentMode, setAssessmentMode] = useState<'latest' | 'submission'>('latest');
  const [selectedDiagnosisId, setSelectedDiagnosisId] = useState('');
  const [evidenceFocus, setEvidenceFocus] = useState<EvidenceFocusRequest>();
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [selectedRca, setSelectedRca] = useState(item.confirmedRca || item.suggestedRca || 'Not classified');
  const [selectedSubCategory, setSelectedSubCategory] = useState(item.defectSubCategory || item.suggestedRcaSubcategory || '');
  const [reviewerNotes, setReviewerNotes] = useState(item.reviewerNotes || '');
  const [recommendedFix, setRecommendedFix] = useState(item.recommendedFix || '');
  const [publicStatus, setPublicStatus] = useState(item.publicStatus || 'Received');
  const [publicMessage, setPublicMessage] = useState(item.publicMessage || '');
  const [resolutionSummary, setResolutionSummary] = useState(item.resolutionSummary || '');
  const [resolutionVersion, setResolutionVersion] = useState(item.resolutionVersion || '');
  const [expectedBehavior, setExpectedBehavior] = useState(item.groundTruthHint || '');
  const [expectedBehaviorVerified, setExpectedBehaviorVerified] = useState(item.expectedBehaviorVerified || false);
  const [isSuggestingRca, setIsSuggestingRca] = useState(false);
  const [showDatasetPicker, setShowDatasetPicker] = useState(false);
  const [datasetTargetId, setDatasetTargetId] = useState('');
  const [isPromoting, setIsPromoting] = useState(false);
  const [rcaSuggestionError, setRcaSuggestionError] = useState<string | null>(null);
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState('');
  useUnsavedDemoDraft(selectedRca !== (item.confirmedRca || item.suggestedRca || 'Not classified') ||
    selectedSubCategory !== (item.defectSubCategory || item.suggestedRcaSubcategory || '') || reviewerNotes !== (item.reviewerNotes || '') ||
    recommendedFix !== (item.recommendedFix || '') || publicStatus !== (item.publicStatus || 'Received') || publicMessage !== (item.publicMessage || '') ||
    resolutionSummary !== (item.resolutionSummary || '') || resolutionVersion !== (item.resolutionVersion || '') ||
    expectedBehavior !== (item.groundTruthHint || '') || expectedBehaviorVerified !== Boolean(item.expectedBehaviorVerified));
  const lifecycle = ['Submitted', 'Triaged', 'Evidence review', 'Review complete', 'Golden candidate', 'Approved for dataset'];
  const terminalState = ['Rejected', 'Duplicate', 'Needs more information'].includes(item.state);
  const currentLifecycleIndex = lifecycle.indexOf(item.state);
  const activeEnvironmentId = environmentId || item.mainEnvironmentId || item.environmentId || undefined;
  const activeEnvironmentName = environmentId ? environmentName : item.mainEnvironmentLabel || item.environmentLabel || undefined;
  const selection = historySelection?.feedbackId === item.id && historySelection.environmentId === activeEnvironmentId ? historySelection : null;
  const history = selection?.history;
  const savedAnswer = assessmentMode === 'latest' ? selection?.selected : undefined;
  const savedDiagnosis = selectedDiagnosis(history, savedAnswer?.id, selectedDiagnosisId);
  const savedAttempt = history?.attempts.find((attempt) => attempt.id === savedAnswer?.attemptId);
  const savedPending = !!savedAttempt && ['queued', 'running'].includes(savedAttempt.status);
  const assessmentLoading = assessmentMode === 'latest' && (!selection || (!history && !selection.error));
  const targetMissing = Boolean(activeEnvironmentId && activeEnvironmentId !== item.environmentId && assessmentMode === 'latest' && !savedAnswer);
  const scopedAnswers = answersInEnvironment(history || null, item, activeEnvironmentId);
  const correctedCaptureId = item.runContext?.submission_answer_id;
  const currentCaptureId = typeof correctedCaptureId === 'string' && correctedCaptureId.startsWith(`submission:${item.id}:r`) ? correctedCaptureId : `original:${item.id}`;
  const submissionLabel = `${currentCaptureId.startsWith('submission:') ? 'Current submitted response' : 'Original submitted response'} · ${item.environment === 'unknown' || !item.environment ? 'environment not recorded' : item.environment} · revision ${item.revision || 1}`;
  const submissionDiagnosis = selectedDiagnosis(history, currentCaptureId, selectedDiagnosisId);
  const useSubmissionSnapshot = !!submissionDiagnosis && (!!selectedDiagnosisId || !item.suggestedRcaEvidence?.length);
  const evidenceAssessment: EvidenceAssessment = targetMissing ? {
    answerId: `environment:${activeEnvironmentId}:unavailable`, label: `${activeEnvironmentName || activeEnvironmentId} · no refreshed answer`, evidence: [], capturedEvidence: [], pending: assessmentLoading,
  } : savedAnswer ? {
    answerId: savedAnswer.id, label: answerVersionLabel(savedAnswer), diagnosisId: savedDiagnosis?.id,
    evidence: savedDiagnosis?.evidence || [], pending: savedPending, retrievalStatus: savedDiagnosis?.retrievalStatus,
  } : {
    answerId: currentCaptureId, label: submissionLabel, diagnosisId: useSubmissionSnapshot ? submissionDiagnosis?.id : undefined,
    evidence: useSubmissionSnapshot ? submissionDiagnosis?.evidence || [] : item.suggestedRcaEvidence || [],
    capturedEvidence: item.evidence,
    pending: assessmentLoading,
    retrievalStatus: submissionDiagnosis?.retrievalStatus,
  };
  const attachedEvidenceCount = evidenceAssessment.evidence.length + (evidenceAssessment.capturedEvidence?.length || 0);
  const isAutoClassified = item.suggestedRcaStatus === 'auto_classified';
  const isManuallyClassified = item.suggestedRcaStatus === 'reviewer_classified';
  useEffect(() => {
    setEvidenceOpen(false); setEvidenceFocus(undefined); setHistorySelection(null); setHistorySelectedId('');
    setAssessmentMode('latest'); setSelectedDiagnosisId(''); setHistoryRefresh(0);
  }, [item.id, activeEnvironmentId]);
  const requestEvidence = (answerId: string, diagnosisId?: string, evidenceId?: string) => {
    setEvidenceOpen(true);
    setEvidenceFocus((previous) => ({ answerId, diagnosisId, evidenceId, sequence: (previous?.sequence || 0) + 1 }));
  };
  const showEvidence = (evidenceId?: string) => requestEvidence(evidenceAssessment.answerId, evidenceAssessment.diagnosisId, evidenceId);
  const selectHistoryVersion = (id: string) => { setHistorySelectedId(id); setAssessmentMode('latest'); setSelectedDiagnosisId(''); setEvidenceFocus(undefined); };
  const reviewSubmission = () => { setAssessmentMode('submission'); setSelectedDiagnosisId(''); setEvidenceFocus(undefined); };
  const reviewSavedEvidence = (diagnosis: DiagnosisVersion, evidenceId?: string) => {
    if (!history?.diagnoses.some((value) => value.id === diagnosis.id && value.answerId === diagnosis.answerId)) return;
    if (diagnosis.answerId === currentCaptureId) setAssessmentMode('submission');
    else { setAssessmentMode('latest'); setHistorySelectedId(diagnosis.answerId); }
    setSelectedDiagnosisId(diagnosis.id);
    requestEvidence(diagnosis.answerId, diagnosis.id, evidenceId);
  };

  useEffect(() => {
    setSelectedRca(item.confirmedRca || item.suggestedRca || 'Not classified');
  }, [item.id, item.confirmedRca, item.suggestedRca]);
  useEffect(() => {
    setSelectedSubCategory(item.defectSubCategory || item.suggestedRcaSubcategory || '');
  }, [item.id, item.defectSubCategory, item.suggestedRcaSubcategory]);
  useEffect(() => { setReviewerNotes(item.reviewerNotes || ''); }, [item.id, item.reviewerNotes]);
  useEffect(() => { setRecommendedFix(item.recommendedFix || ''); }, [item.id, item.recommendedFix]);
  useEffect(() => { setPublicStatus(item.publicStatus || 'Received'); }, [item.id, item.publicStatus]);
  useEffect(() => { setPublicMessage(item.publicMessage || ''); }, [item.id, item.publicMessage]);
  useEffect(() => { setResolutionSummary(item.resolutionSummary || ''); }, [item.id, item.resolutionSummary]);
  useEffect(() => { setResolutionVersion(item.resolutionVersion || ''); }, [item.id, item.resolutionVersion]);
  useEffect(() => { setExpectedBehavior(item.groundTruthHint || ''); }, [item.id, item.groundTruthHint]);
  useEffect(() => { setExpectedBehaviorVerified(item.expectedBehaviorVerified || false); }, [item.id, item.expectedBehaviorVerified]);

  const triggerToast = (msg: string) => {
    setToastMessage(msg);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 3000);
  };

  const runRcaSuggestion = async () => {
    if (!onSuggestRootCause) return;
    reviewSubmission();
    setIsSuggestingRca(true);
    setRcaSuggestionError(null);
    try {
      const updated = await onSuggestRootCause(item.id);
      setHistoryRefresh((value) => value + 1);
      if (updated) {
        setSelectedRca(updated.confirmedRca || updated.suggestedRca || 'Not classified');
        setSelectedSubCategory(updated.defectSubCategory || updated.suggestedRcaSubcategory || '');
      }
      triggerToast(!updated ? 'Analysis queued. Follow its progress in the answer-history panel.' : updated?.suggestedRcaReviewRequired === false
        ? 'RCA auto-classified. You can edit either field before saving.'
        : 'RCA result ready. Review or edit the suggested classification.');
    } catch (error) {
      setRcaSuggestionError(error instanceof Error ? error.message : 'Could not generate RCA suggestion');
    } finally {
      setIsSuggestingRca(false);
    }
  };

  const saveReviewFields = async (state?: string, verified = expectedBehaviorVerified) => {
    if (!onSaveTriage) return;
    await onSaveTriage(item.id, {
      ...(state ? { state } : {}),
      ...(!savedAnswer && !assessmentLoading && !targetMissing ? {
        confirmed_rca: selectedRca === 'Not classified' ? null : selectedRca,
        subcategory: selectedSubCategory.trim() || null,
      } : {}),
      reviewer_notes: reviewerNotes,
      recommended_fix: recommendedFix,
      expected_behavior: expectedBehavior,
      expected_behavior_verified: verified,
    });
  };

  const savePublicUpdate = async () => {
    if (!onSaveTriage) return;
    if (publicStatus === 'Resolved' && !resolutionSummary.trim()) {
      triggerToast('Add a resolution summary before marking this feedback resolved.');
      return;
    }
    if (['Needs information', 'Not planned', 'Duplicate'].includes(publicStatus) && !publicMessage.trim() && !resolutionSummary.trim()) {
      triggerToast('Add a short explanation that the submitter can see.');
      return;
    }
    try {
      await onSaveTriage(item.id, {
        public_status: publicStatus,
        public_message: publicMessage.trim() || null,
        resolution_summary: resolutionSummary.trim() || null,
        resolution_version: resolutionVersion.trim() || null,
      });
      triggerToast('Submitter-facing status updated.');
    } catch (error) {
      triggerToast(error instanceof Error ? error.message : 'Could not update the submitter-facing status.');
    }
  };

  const advanceLifecycle = async () => {
    if (!onSaveTriage) return;
    try {
      if (item.state === 'Submitted') {
        await onSaveTriage(item.id, { state: 'Triaged' });
        triggerToast('Feedback marked as triaged.');
      } else if (item.state === 'Triaged') {
        await onSaveTriage(item.id, { state: 'Evidence review' });
        triggerToast('Evidence review started.');
      } else if (item.state === 'Evidence review') {
        if (!expectedBehavior.trim()) {
          triggerToast('Add reviewer-verified expected behavior before completing review.');
          return;
        }
        if (!expectedBehaviorVerified) {
          triggerToast('Confirm that expected behavior was checked against source evidence.');
          return;
        }
        await saveReviewFields('Review complete', true);
        triggerToast('Evidence review completed. Choose a target dataset to add this candidate.');
      } else if (item.state === 'Review complete') {
        setDatasetTargetId('');
        setShowDatasetPicker(true);
      } else if (item.state === 'Golden candidate' && !item.expectedBehaviorVerified) {
        await onSaveTriage(item.id, { state: 'Evidence review', expected_behavior_verified: false });
        triggerToast('Unverified legacy candidate withdrawn. Complete evidence review before adding it again.');
      } else if (item.state === 'Golden candidate' || item.state === 'Approved for dataset') {
        onNavigate('golden-datasets');
      }
    } catch (error) {
      triggerToast(error instanceof Error ? error.message : 'Could not advance the feedback lifecycle.');
    }
  };

  const addToDataset = async () => {
    if (!onPromoteToCandidate || !datasetTargetId) return;
    setIsPromoting(true);
    try {
      await onPromoteToCandidate(item, datasetTargetId);
      setShowDatasetPicker(false);
      triggerToast('Reviewed candidate added to the selected dataset.');
    } catch (error) {
      triggerToast(error instanceof Error ? error.message : 'Could not add the candidate to this dataset.');
    } finally {
      setIsPromoting(false);
    }
  };

  return (
    <div className="feedback-review-workspace flex w-full flex-col gap-4 pb-24 animate-in fade-in duration-200">
      {/* Toast Notification */}
      {showToast && (
        <div role="status" className="fixed top-18 right-8 z-50 flex items-center gap-space-sm px-space-md py-space-sm bg-surface shadow-lg rounded-xl border border-surface-border animate-in fade-in slide-in-from-top-2">
          <div className="w-6 h-6 rounded-full bg-state-gray-soft text-ink-secondary flex items-center justify-center">
            <span aria-hidden="true" className="material-symbols-outlined text-[16px]">info</span>
          </div>
          <div className="flex flex-col">
            <span className="font-title-md text-title-md text-ink-primary font-semibold">{toastMessage}</span>
          </div>
          <button
            type="button"
            onClick={() => setShowToast(false)}
            aria-label="Dismiss review update"
            className="ml-space-sm text-ink-muted hover:text-ink-primary p-0.5 rounded transition-colors cursor-pointer"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>
      )}

      {/* Top Navigation / Context Header */}
      <header className="flex min-w-0 flex-col gap-3 py-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-metadata text-ink-muted">
          <ActionButton label="Feedback inbox" icon={<ArrowLeft />} tone="ghost" size="sm" onClick={() => onNavigate('feedback-inbox')} />
          <span aria-hidden="true">/</span><span className="font-code-xs">{item.id}</span>
          <span className="rounded-md border border-surface-border bg-surface px-2 py-1 text-ink-secondary">{item.state}</span>
          {item.assignedReviewer && <span className="ml-auto">Reviewer: {item.assignedReviewer}</span>}
        </div>
        <h1 className="max-w-5xl break-words font-headline-md text-ink-primary">{item.title}</h1>
        {item.mainEnvironmentId && <p role="note" aria-label="Current and original environments" className="max-w-5xl rounded-lg border border-surface-border bg-surface px-3 py-2 text-body-sm text-ink-secondary"><strong className="text-ink-primary">Main environment: {item.mainEnvironmentLabel || item.mainEnvironmentKind}</strong><span> · Originally reported in {item.environmentLabel || (item.environment === 'nonprod' ? 'Non-production' : item.environment === 'prod' ? 'Production' : 'an unknown environment')}. Source metadata and submission history are unchanged.</span></p>}
      </header>

      <div className="grid w-full grid-cols-1 items-start gap-4 lg:grid-cols-12">
        <div className="order-2 flex min-w-0 flex-col gap-3 lg:order-1 lg:col-span-5">
          <SubmissionContextCard item={item} />
          <BusinessDomainPanel key={`business-${item.id}`} context={item} onSave={async (fields) => { if (onSaveTriage) await onSaveTriage(item.id, fields); }} />
            <AnswerHistoryView feedbackId={item.id} context={item} reviewer environmentId={activeEnvironmentId} environmentName={activeEnvironmentName} onDataChanged={onDataChanged} selectedVersionId={historySelectedId} onSelectVersion={selectHistoryVersion} onSelectionChange={(value) => { if (value.feedbackId === item.id && value.environmentId === activeEnvironmentId) setHistorySelection(value); }} onReviewEvidence={reviewSavedEvidence} onReviewSubmission={reviewSubmission} refreshRequest={historyRefresh} />
           <FeedbackEvidencePanel key={`evidence-${item.id}`} item={item} assessment={evidenceAssessment} focusRequest={evidenceFocus} open={evidenceOpen} onOpenChange={setEvidenceOpen} />
           <CollapsibleSection key={`workflow-${item.id}`} title="Review workflow" summary={item.state}>
              <p className="mb-4 text-body-sm text-ink-secondary">Successful RCA on the current source answer can mark this report Triaged. The diagnosis remains unverified until human review. Linked-environment RCA does not advance this source workflow or resolve feedback.</p>
             <div className="relative flex flex-col gap-3 pl-6">
               <div className="absolute bottom-3 left-2.5 top-2 w-0.5 bg-surface-border"></div>
               {lifecycle.map((step, index) => {
                 const complete = !terminalState && currentLifecycleIndex > index;
                 const current = !terminalState && currentLifecycleIndex === index;
                 return <div key={step} className={`relative flex items-start gap-3 ${!complete && !current ? 'opacity-55' : ''}`}>
                   <div className={`absolute -left-6 top-0.5 flex h-5 w-5 items-center justify-center rounded-full ${complete ? 'bg-evidence-soft text-evidence-teal' : current ? 'bg-review-soft text-review-amber' : 'bg-surface-container-low text-ink-muted'}`}>
                     <span className="material-symbols-outlined text-[14px]">{complete ? 'check' : current ? 'radio_button_checked' : 'more_horiz'}</span>
                   </div>
                   <div className={`flex flex-col ${current ? 'w-full rounded-lg border border-review-amber/20 bg-review-soft/40 p-2 -m-1' : ''}`}>
                     <span className={`font-label-sm text-label-sm ${current ? 'font-bold text-ink-primary' : 'font-medium text-ink-secondary'}`}>{step}{current ? ' · Current' : ''}</span>
                     {step === 'Submitted' && <span className="font-metadata text-metadata text-ink-muted">{item.reportedTime || 'Time not recorded'}</span>}
                     {step === 'Evidence review' && current && <span className="font-metadata text-metadata text-ink-secondary">{item.assignedReviewer ? `Assigned to ${item.assignedReviewer}` : 'Not assigned'}</span>}
                   </div>
                 </div>;
               })}
               {terminalState && <div className="rounded bg-state-gray-soft px-2 py-1 font-label-sm text-ink-secondary">Terminal state: {item.state}</div>}
             </div>
              <div className="mt-4 flex flex-wrap gap-2 border-t border-surface-border pt-3">
                {!terminalState && <>
                  {!['Golden candidate', 'Approved for dataset'].includes(item.state) && <button type="button" onClick={() => { if (onSaveTriage) void onSaveTriage(item.id, { state: 'Needs more information' }).then(() => triggerToast('More information requested.')).catch((error: Error) => triggerToast(error.message)); }} className="rounded-lg border border-surface-border px-3 py-2 text-label-sm text-ink-secondary hover:bg-canvas">Request more information</button>}
                  <button type="button" onClick={() => { if (onSaveTriage) void onSaveTriage(item.id, { state: 'Duplicate' }).then(() => onNavigate('feedback-inbox')).catch((error: Error) => triggerToast(error.message)); }} className="rounded-lg border border-surface-border px-3 py-2 text-label-sm text-ink-secondary hover:bg-canvas">Mark duplicate</button>
                  {!['Golden candidate', 'Approved for dataset'].includes(item.state) && <button type="button" onClick={() => { if (onSaveTriage) void onSaveTriage(item.id, { state: 'Rejected' }).then(() => onNavigate('feedback-inbox')).catch((error: Error) => triggerToast(error.message)); }} className="rounded-lg border border-surface-border px-3 py-2 text-label-sm text-issue-red hover:bg-issue-soft">Reject feedback</button>}
                </>}
              </div>
          </CollapsibleSection>
        </div>

        <div className="order-1 flex min-w-0 flex-col gap-3 lg:order-2 lg:col-span-7">
          {/* SECTION 2: Reviewer Assessment */}
          <section aria-labelledby="rca-assessment-title" className="workspace-panel flex flex-col gap-4 rounded-xl border border-surface-border bg-surface p-4 sm:p-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                 <div><h2 id="rca-assessment-title" className="font-title-md text-ink-primary">RCA assessment</h2><p className="mt-0.5 text-metadata text-ink-muted">{targetMissing ? `${environmentName || environmentId} · no refreshed answer` : savedAnswer ? `${savedAnswer.environmentLabel || ''} ${answerVersionLabel(savedAnswer)}` : submissionLabel}</p></div>
              </div>
              <span className="rounded-md border border-surface-border px-2 py-1 text-metadata text-ink-secondary">
                 {savedAnswer ? savedDiagnosis?.verified ? 'Reviewer verified' : 'AI · not verified' : isAutoClassified ? 'Auto-classified' : isManuallyClassified ? 'Manually classified' : 'Review recommended'}
              </span>
            </div>

             {(Boolean(environmentId) || !!history?.answers.some((answer) => answer.kind !== 'original')) && <label className="flex flex-col gap-1 text-label-sm font-medium text-ink-secondary">Assessment version
               <select aria-label="Assessment version" value={savedAnswer?.id || (targetMissing ? 'environment' : 'submission')} onChange={(event) => { if (event.target.value === 'submission') reviewSubmission(); else if (event.target.value === 'environment') setAssessmentMode('latest'); else selectHistoryVersion(event.target.value); }} className="min-w-0 max-w-full rounded-lg border border-surface-border bg-canvas px-3 py-2 text-body-sm text-ink-primary">
                 {targetMissing && <option value="environment">{environmentName || 'Selected environment'} · not tested</option>}
                 <option value="submission">{submissionLabel} · editable review</option>
                 {scopedAnswers.filter((answer) => answer.kind !== 'original').map((answer) => <option key={answer.id} value={answer.id}>{answer.environmentLabel || ''} {answerVersionLabel(answer, true)} · saved diagnosis</option>)}
               </select>
             </label>}
             {assessmentLoading ? <p role="status" className="text-body-sm text-ink-muted">Loading saved RCA assessments…</p> : targetMissing ? <p role="status" className="rounded-lg border border-surface-border bg-canvas p-4 text-body-sm text-ink-secondary">Not tested in {environmentName || 'this environment'}. Promote this feedback or run a fresh answer to save its own response and RCA. Another environment's diagnosis is not used as a substitute.</p> : savedAnswer ? <SavedRcaAssessment answer={savedAnswer} diagnosis={savedDiagnosis} pending={savedPending} onReviewEvidence={showEvidence} /> : <>
             {selection?.error && <p className="text-body-sm text-issue-red">Saved answer assessments could not be loaded. The fields below apply only to the submitted response.</p>}
             {!!selection?.selected && <p className="text-metadata text-ink-muted">This is the submitted response’s review. Saved retests have separate RCA categories and evidence; choose their assessment version above to inspect them.</p>}
             <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {/* Confirmed RCA */}
              <div className="flex flex-col gap-1">
                <label className="text-label-sm font-medium text-ink-secondary" htmlFor="rca-category">RCA category</label>
                  <select
                    aria-label="RCA category"
                    id="rca-category"
                  value={selectedRca}
                  onChange={(e) => setSelectedRca(e.target.value)}
                  className="min-w-0 w-full p-2.5 rounded-lg bg-surface-container-low text-ink-primary font-label-md font-semibold border border-surface-border focus:border-primary focus:outline-none cursor-pointer"
                >
                   <option value="Not classified">Not classified</option>
                   <option value="correct_but_differently_worded">Correct, differently worded</option>
                   <option value="factual_error">Factual error</option>
                   <option value="missing_required_content">Missing required content</option>
                   <option value="incomplete_answer">Incomplete answer</option>
                   <option value="wrong_region_or_scope">Wrong region or scope</option>
                   <option value="table_interpretation_error">Table interpretation error</option>
                   <option value="image_ocr_error">Image/OCR error</option>
                   <option value="retrieval_failure">Retrieval failure</option>
                   <option value="source_gap">Knowledge/source gap</option>
                   <option value="outdated_content">Outdated content</option>
                   <option value="ambiguous_question">Ambiguous question</option>
                   <option value="unsupported_expected_answer">Unsupported expected answer</option>
                   <option value="insufficient_evidence">Insufficient evidence</option>
                   <option value="reasoning_error">Reasoning error</option>
                   <option value="citation_failure">Citation failure</option>
                   <option value="format_mismatch">Format mismatch</option>
                   <option value="tool_error">Tool error</option>
                   <option value="other">Other</option>
                    {selectedRca !== 'Not classified' && ![
                     'correct_but_differently_worded', 'factual_error', 'missing_required_content',
                     'incomplete_answer', 'wrong_region_or_scope', 'table_interpretation_error',
                     'image_ocr_error', 'retrieval_failure', 'source_gap', 'outdated_content',
                     'ambiguous_question', 'unsupported_expected_answer', 'insufficient_evidence',
                     'reasoning_error', 'citation_failure', 'format_mismatch', 'tool_error', 'other',
                    ].includes(selectedRca) && <option value={selectedRca}>{formatRcaLabel(selectedRca)}</option>}
                </select>
              </div>

              {/* Sub-category */}
              <div className="flex flex-col gap-1">
                <label htmlFor="rca-subcategory" className="text-label-sm font-medium text-ink-secondary">RCA subcategory</label>
                <input
                  id="rca-subcategory"
                  list="rca-subcategory-options"
                  value={selectedSubCategory}
                  onChange={(e) => setSelectedSubCategory(e.target.value)}
                  placeholder="Set or edit the specific defect"
                  className="min-w-0 rounded-lg border border-transparent bg-surface-container-low px-3 py-2.5 text-body-sm text-ink-primary hover:border-surface-border focus:border-primary focus:outline-none"
                />
                <datalist id="rca-subcategory-options">
                  {[
                    'Incorrect schedule time', 'Wrong status or code', 'Wrong region or scope',
                    'Missing required step', 'Unsupported claim', 'Source passage not retrieved',
                    'Table row or column misread', 'Stale source content', 'Citation missing or mismatched',
                    'Image text OCR misread', 'Incomplete response', 'Format not followed',
                    'Outdated vector chunk in top-k', 'Embedding distance threshold too low',
                    'PDF table line break collapse', 'Incorrect paragraph anchor',
                  ].map((subcategory) => <option key={subcategory} value={subcategory} />)}
                  {item.suggestedRcaSubcategory && <option value={item.suggestedRcaSubcategory} />}
                </datalist>
              </div>
            </div>

            <div className="rounded-lg border border-surface-border bg-canvas/60 p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-label-md font-semibold text-ink-primary">Document-backed analysis</h3>
                  <p className="mt-1 text-body-sm text-ink-muted">AI suggestions remain subject to source review.</p>
                </div>
                <button type="button" disabled={isSuggestingRca} onClick={() => void runRcaSuggestion()} className="shrink-0 rounded-lg bg-primary-container px-3 py-2 text-label-sm font-semibold text-on-primary transition-colors hover:bg-primary disabled:opacity-50">
                  {isSuggestingRca ? 'Analyzing evidence…' : item.suggestedRca ? 'Run again' : 'Run RCA'}
                </button>
              </div>
              {rcaSuggestionError && <p className="mt-2 text-body-sm text-issue-red">{rcaSuggestionError}</p>}
              {item.suggestedRca && (
                <div className="mt-4 border-t border-primary/10 pt-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-surface px-2.5 py-1 font-label-sm font-semibold text-primary">{formatRcaLabel(item.suggestedRca)}</span>
                    {item.suggestedRcaConfidence != null && <span className="font-metadata text-ink-secondary">Confidence {(item.suggestedRcaConfidence * 100).toFixed(0)}%</span>}
                    <span className={`rounded px-2 py-1 font-metadata font-semibold ${item.suggestedRcaReviewRequired === false ? 'bg-evidence-soft text-evidence-teal' : 'bg-review-soft text-review-amber'}`}>{isManuallyClassified ? 'Manually classified' : item.suggestedRcaReviewRequired === false ? 'Auto-classified · editable' : 'Review recommended'}</span>
                    {item.suggestedRcaStatus && <span className="font-metadata text-ink-muted">{item.suggestedRcaStatus}</span>}
                  </div>
                   {item.suggestedRcaRationale && <div className="mt-2"><ContentPreview label="RCA rationale" compact><RcaRationale text={item.suggestedRcaRationale} evidence={evidenceAssessment.evidence} onCitationClick={showEvidence} /></ContentPreview></div>}
                   {item.suggestedRcaSubcategory && <p className="mt-1 font-metadata text-ink-muted">Detected subcategory: {formatRcaLabel(item.suggestedRcaSubcategory)}</p>}
                    {evidenceAssessment.evidence.length ? <ActionButton label={`Review ${evidenceAssessment.evidence.length} cited source passages`} compactLabel={`${evidenceAssessment.evidence.length} sources`} icon={<BookOpen />} tone="ghost" size="sm" containerClassName="mt-3" onClick={() => showEvidence()} /> : <p className="mt-2 text-body-sm text-ink-muted">No supporting document passages were retrieved for this submission assessment.</p>}
                  {item.suggestedRcaMissingClaims?.length ? <div className="mt-3 text-body-sm text-review-amber"><strong>Missing:</strong> {item.suggestedRcaMissingClaims.join(' · ')}</div> : null}
                  {item.suggestedRcaContradictedClaims?.length ? <div className="mt-2 text-body-sm text-issue-red"><strong>Contradicted:</strong> {item.suggestedRcaContradictedClaims.join(' · ')}</div> : null}
                  <ActionButton label="Restore detected classification" compactLabel="Restore" icon={<RotateCcw />} tone="ghost" size="sm" containerClassName="mt-3" onClick={() => { setSelectedRca(item.suggestedRca || 'Not classified'); setSelectedSubCategory(item.suggestedRcaSubcategory || ''); }} />
                </div>
              )}
             </div>
             </>}
             {savedAnswer && (savedAnswer.environment !== item.environment || savedAnswer.revision !== (item.revision || 1) || !item.environment || item.environment === 'unknown') && <p role="note" className="text-metadata text-ink-muted">This diagnosis belongs to the selected answer’s recorded environment and revision. The original environment or current input differs or is unknown; this result cannot resolve that report.</p>}

             {/* Rationale */}
             <div className="flex flex-col gap-1">
               {savedAnswer && <p className="mb-2 text-metadata text-ink-muted">The review fields below apply to the current feedback. Saving them does not edit or copy the selected answer’s saved RCA.</p>}
              <label className="text-label-sm font-medium text-ink-secondary" htmlFor="expected-answer">Expected answer</label>
              <textarea
                id="expected-answer"
                value={expectedBehavior}
                onChange={(event) => {
                  setExpectedBehavior(event.target.value);
                  if (expectedBehaviorVerified) setExpectedBehaviorVerified(false);
                }}
                readOnly={['Review complete', 'Golden candidate', 'Approved for dataset'].includes(item.state)}
                rows={3}
                placeholder="Write reviewer-verified expected behavior; user feedback text is not ground truth."
                className="w-full rounded-lg border border-surface-border bg-canvas p-3 text-body-sm text-ink-primary read-only:opacity-80"
              />
              <label className={`mt-1 flex items-start gap-2 rounded-lg border border-surface-border p-3 font-body-sm ${item.state === 'Evidence review' ? 'cursor-pointer bg-surface' : 'bg-canvas text-ink-muted'}`}>
                <input
                  type="checkbox"
                  checked={expectedBehaviorVerified}
                  disabled={item.state !== 'Evidence review'}
                  onChange={(event) => setExpectedBehaviorVerified(event.target.checked)}
                  className="mt-0.5 accent-primary"
                />
                <span>
                  <span className="block font-label-sm font-semibold text-ink-primary">I verified this expected behavior against source evidence</span>
                  <span className="mt-0.5 block text-ink-muted">User-provided feedback or an AI suggestion alone does not qualify as verified ground truth.</span>
                </span>
              </label>
            </div>

            <CollapsibleSection key={`notes-${item.id}`} title="Reviewer notes & remediation" summary="Private to the review team">
            <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <label className="font-metadata text-metadata text-ink-muted uppercase font-semibold">
                Reviewer Root Cause Rationale
              </label>
              <textarea aria-label="Reviewer notes" value={reviewerNotes} onChange={(event) => setReviewerNotes(event.target.value)} rows={3} placeholder="Record reviewer rationale" className="w-full rounded-lg border border-surface-border bg-canvas p-3 text-body-sm text-ink-primary" />
            </div>

            {/* Recommended Fix */}
            <div className="flex flex-col gap-1">
              <label className="font-metadata text-metadata text-ink-muted uppercase font-semibold">
                Recommended Remediation
              </label>
              <textarea aria-label="Recommended remediation" value={recommendedFix} onChange={(event) => setRecommendedFix(event.target.value)} rows={2} placeholder="Optional recommended remediation" className="w-full rounded-lg border border-surface-border bg-canvas p-3 text-body-sm text-ink-primary" />
            </div>
            </div>
            </CollapsibleSection>

            <CollapsibleSection key={`public-update-${item.id}`} title="Submitter-facing update" summary={item.publicStatus || 'Received'}>
            <div className="flex flex-col gap-3">
              <div>
                <p className="mt-1 text-body-sm text-ink-secondary">Only these fields appear on the user’s My feedback page. Reviewer notes and RCA evidence stay private.</p>
              </div>
              <label className="flex flex-col gap-1 text-label-sm font-semibold text-ink-secondary">
                Public status
                <select value={publicStatus} onChange={(event) => setPublicStatus(event.target.value as typeof publicStatus)} className="rounded-lg border border-surface-border bg-surface px-3 py-2 text-body-sm text-ink-primary">
                  {Array.from(new Set(['Received', 'In review', 'Needs information', 'Not planned', 'Duplicate', publicStatus])).map((value) => <option key={value} value={value} disabled={['Resolved', 'Retesting', 'Awaiting your confirmation'].includes(value)}>{value}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-label-sm font-semibold text-ink-secondary">
                Update message
                <textarea value={publicMessage} onChange={(event) => setPublicMessage(event.target.value)} rows={2} maxLength={2000} placeholder="A brief update or request visible to the submitter" className="rounded-lg border border-surface-border bg-surface p-3 text-body-sm font-normal text-ink-primary" />
              </label>
              {publicStatus === 'Resolved' && <>
                <label className="flex flex-col gap-1 text-label-sm font-semibold text-ink-secondary">
                  Resolution summary <span className="text-issue-red">Required for Resolved</span>
                  <textarea value={resolutionSummary} onChange={(event) => setResolutionSummary(event.target.value)} rows={3} maxLength={4000} placeholder="Explain what changed and how it addresses the report" className="rounded-lg border border-surface-border bg-surface p-3 text-body-sm font-normal text-ink-primary" />
                </label>
                <label className="flex flex-col gap-1 text-label-sm font-semibold text-ink-secondary">
                  Fix version (optional)
                  <input value={resolutionVersion} onChange={(event) => setResolutionVersion(event.target.value)} maxLength={200} placeholder="Release, model, or agent build" className="rounded-lg border border-surface-border bg-surface px-3 py-2 text-body-sm font-normal text-ink-primary" />
                </label>
              </>}
              <div className="flex justify-end">
                <button type="button" onClick={() => void savePublicUpdate()} className="rounded-lg bg-primary-container px-4 py-2 text-label-sm font-semibold text-on-primary hover:bg-primary">Save user update</button>
              </div>
            </div>
            </CollapsibleSection>
          </section>

          {/* SECTION 3: Claim Checklist Component */}
          <CollapsibleSection key={`claims-${item.id}`} title="Claim-level verification" summary={`${item.claims?.length || 0} recorded assertions`}>
            <div className="flex items-center justify-between">
               <span className="font-metadata text-metadata text-ink-muted font-semibold">{item.claims?.length || 0} Extracted Assertions</span>
            </div>

             <div className="flex flex-col gap-2.5">
               {!item.claims?.length && (
                 <div className="rounded-lg border border-dashed border-surface-border bg-canvas p-4 text-body-sm text-ink-muted">
                   No reviewer claims have been recorded for this feedback yet.
                 </div>
               )}
               {item.claims?.map((claim) => (
                 <div key={claim.id} className="p-3 rounded-lg bg-surface-container-low flex flex-col gap-2 border border-surface-border">
                   <div className="flex items-start justify-between gap-2">
                     <p className="font-body-sm text-body-sm text-ink-primary font-medium">{claim.statement}</p>
                     <span className="px-2.5 py-0.5 rounded-full bg-surface-container text-ink-secondary font-label-sm text-label-sm font-semibold shrink-0">{claim.verdict}</span>
                   </div>
                   <div className="flex items-center justify-between pt-1">
                     <div className="flex items-center gap-1.5">
                       <span className="font-metadata text-metadata text-ink-muted">Linked Evidence:</span>
                       {claim.linkedEvidence?.length ? claim.linkedEvidence.map((evidenceId) => (
                         <span key={evidenceId} className="px-1.5 py-0.5 rounded bg-surface text-ink-secondary font-code-xs text-code-xs font-semibold shadow-xs font-mono">{evidenceId}</span>
                       )) : <span className="font-metadata text-metadata text-ink-muted italic">None bound</span>}
                     </div>
                     {claim.confidence != null && <span className="font-metadata text-metadata text-ink-secondary font-medium">Confidence {(claim.confidence * 100).toFixed(0)}%</span>}
                   </div>
                 </div>
               ))}
             </div>
            </CollapsibleSection>
         </div>

      </div>

      {/* Bottom Sticky Action Bar */}
      <footer className="fixed bottom-0 left-0 right-0 z-30 flex flex-wrap items-center justify-end gap-3 border-t border-surface-border bg-surface px-4 py-3 sm:left-60 sm:px-6">
         <p className="mr-auto hidden text-metadata text-ink-muted xl:block">{attachedEvidenceCount} source references · {savedAnswer ? 'saved diagnosis is read-only' : 'review changes require saving'}</p>

        <div className="flex flex-wrap items-center justify-end gap-space-sm">
          {!terminalState && !['Golden candidate', 'Approved for dataset'].includes(item.state) && <>
            <button
              type="button"
              onClick={() => void saveReviewFields().then(() => triggerToast('Feedback review changes saved.')).catch((error: Error) => triggerToast(error.message))}
              className="px-3.5 py-2 rounded-lg bg-surface hover:bg-state-gray-soft text-ink-secondary hover:text-ink-primary font-label-md text-label-md shadow-xs transition-colors border border-surface-border cursor-pointer"
            >
              Save changes
            </button>
          </>}

          {item.state === 'Review complete' && <button
            type="button"
            onClick={() => void onSaveTriage?.(item.id, { state: 'Evidence review', expected_behavior_verified: false }).then(() => triggerToast('Evidence review reopened.'))}
            className="rounded-lg border border-surface-border bg-surface px-3.5 py-2 font-label-md text-ink-secondary hover:bg-state-gray-soft"
          >Reopen review</button>}

          {['Golden candidate', 'Approved for dataset'].includes(item.state) && (item.state !== 'Golden candidate' || item.expectedBehaviorVerified) && <button
            type="button"
            onClick={() => onNavigate('golden-datasets')}
            className="rounded-lg border border-surface-border bg-surface px-3.5 py-2 font-label-md text-ink-secondary hover:bg-state-gray-soft"
          >Open golden datasets</button>}

          {!terminalState && (!['Golden candidate', 'Approved for dataset'].includes(item.state) || (item.state === 'Golden candidate' && !item.expectedBehaviorVerified)) && <button
            type="button"
            disabled={item.state === 'Evidence review' && (!expectedBehaviorVerified || !expectedBehavior.trim())}
            onClick={() => void advanceLifecycle()}
            className="inline-flex items-center gap-2 rounded-lg bg-primary-container px-4 py-2 font-label-md font-semibold text-on-primary transition-colors hover:bg-primary disabled:cursor-not-allowed disabled:opacity-45"
          >
            <span className="material-symbols-outlined text-[18px]">{item.state === 'Review complete' ? 'playlist_add' : item.state === 'Evidence review' ? 'task_alt' : 'arrow_forward'}</span>
            <span>{lifecycleActionLabel(item.state)}</span>
          </button>}
        </div>
      </footer>

      <AnimatePresence>{showDatasetPicker && <AnimatedDiv key="dataset-picker" surface="backdrop" className="fixed inset-0 z-50 flex items-center justify-center bg-ink-primary/55 p-4" role="presentation">
        <AnimatedSection role="dialog" aria-modal="true" aria-labelledby="dataset-picker-title" className="w-full max-w-lg rounded-2xl border border-surface-border bg-surface p-space-lg shadow-2xl">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 id="dataset-picker-title" className="font-headline-sm text-ink-primary">Add reviewed case to a dataset</h2>
              <p className="mt-1 font-body-sm text-ink-secondary">Choose exactly which golden dataset receives this candidate. It will still need dataset approval before evaluation.</p>
            </div>
            <button type="button" aria-label="Close" onClick={() => setShowDatasetPicker(false)} className="rounded-lg p-1 text-ink-muted hover:bg-state-gray-soft">
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>

          {datasets.length > 0 ? <label className="mt-5 block font-label-sm font-medium text-ink-secondary">
            Target golden dataset
            <select value={datasetTargetId} onChange={(event) => setDatasetTargetId(event.target.value)} className="mt-1.5 w-full rounded-lg border border-surface-border bg-canvas px-3 py-2.5 font-body-sm text-ink-primary">
              <option value="">Choose a dataset…</option>
              {datasets.map((dataset) => <option key={dataset.dataset_id} value={dataset.dataset_id}>{dataset.name} · v{dataset.current_version} · {dataset.case_count || 0} approved · {dataset.pending_reviews || 0} pending</option>)}
            </select>
          </label> : <div className="mt-5 rounded-lg border border-dashed border-surface-border bg-canvas p-4">
            <p className="font-body-sm text-ink-secondary">No golden datasets exist yet. Create one before adding this candidate.</p>
            <button type="button" onClick={() => { setShowDatasetPicker(false); onNavigate('golden-datasets'); }} className="mt-3 font-label-sm font-semibold text-primary hover:underline">Create a golden dataset</button>
          </div>}

          <div className="mt-6 flex justify-end gap-2">
            <button type="button" onClick={() => setShowDatasetPicker(false)} className="rounded-lg border border-surface-border px-3.5 py-2 font-label-md text-ink-secondary hover:bg-state-gray-soft">Cancel</button>
            {datasets.length > 0 && <button type="button" disabled={!datasetTargetId || isPromoting} onClick={() => void addToDataset()} className="rounded-lg bg-dataset-purple px-4 py-2 font-label-md font-semibold text-on-primary disabled:cursor-not-allowed disabled:opacity-50">{isPromoting ? 'Adding…' : 'Add candidate'}</button>}
          </div>
        </AnimatedSection>
      </AnimatedDiv>}</AnimatePresence>
    </div>
  );
};

function lifecycleActionLabel(state: string, expectedBehaviorVerified = false): string {
  switch (state) {
    case 'Submitted': return 'Mark triaged';
    case 'Triaged': return 'Start evidence review';
    case 'Evidence review': return 'Complete review';
    case 'Review complete': return 'Add to golden dataset';
    case 'Golden candidate': return expectedBehaviorVerified ? 'Open golden dataset' : 'Reopen evidence review';
    default: return 'Continue lifecycle';
  }
}
