import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence } from 'motion/react';
import { AgentEnvironment, clearReadCache, getMyFeedback, MyFeedbackEvent, MyFeedbackRecord, MyFeedbackListResponse, PublicFeedbackStatus, publicFeedbackStatuses } from '../api/feedbackApi';
import { AnswerMarkdown } from './AnswerMarkdown';
import { ColumnFilter } from './ColumnFilter';
import { AnswerHistorySelection, AnswerHistoryView } from './AnswerHistoryView';
import { BusinessDomainPanel } from './BusinessDomainPanel';
import { HorizontalTableScroll } from './HorizontalTableScroll';
import { FeedbackEditView } from './FeedbackEditView';
import { formatRcaLabel } from '../utils/formatRcaLabel';
import { CollapsibleSection } from './CollapsibleSection';
import { ContentPreview } from './ContentPreview';
import { AnimatedDiv, AnimatedSection } from './UiMotion';
import { containDialogFocus, useDialogFocus } from '../utils/dialogFocus';
import { ArrowRight, FilterX, Pencil } from 'lucide-react';
import { ActionButton } from './ActionButton';
import { answerUserVerdict, confirmationVerdict, reviewMessage } from '../utils/answerReview';

function latestReporterVerdict(item: MyFeedbackRecord): string {
  const review = item.answerReview;
  return review?.displayAnswerId || review?.answerId
    ? review.userVerdict || confirmationVerdict(review.confirmation) || 'Not yet reviewed'
    : item.userVerdict;
}

interface MyFeedbackViewProps {
  environmentId?: string;
  environmentName?: string;
  data: MyFeedbackListResponse | null;
  loading: boolean;
  page: number;
  search: string;
  domain: string;
  environment: AgentEnvironment | 'All';
  domains: string[];
  filtersLoading: boolean;
  status: PublicFeedbackStatus | 'All';
  onPageChange: (page: number) => void;
  onSearchChange: (search: string) => void;
  onDomainChange: (domain: string) => void;
  onEnvironmentChange: (environment: AgentEnvironment | 'All') => void;
  onStatusChange: (status: PublicFeedbackStatus | 'All') => void;
  onClearFilters: () => void;
  onDataChanged: () => void;
  openRequest?: { feedbackId: string; sequence: number } | null;
}

function statusClass(status: PublicFeedbackStatus): string {
  if (status === 'Resolved') return 'bg-evidence-soft text-evidence-teal';
  if (status === 'Needs information') return 'bg-review-soft text-review-amber';
  if (status === 'Not planned' || status === 'Duplicate') return 'bg-state-gray-soft text-ink-secondary';
  return 'bg-indigo-soft text-primary-container';
}

function formatDate(value: string): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date);
}

export const MyFeedbackView: React.FC<MyFeedbackViewProps> = ({
  data,
  loading,
  page,
  search,
  domain,
  environment,
  domains,
  filtersLoading,
  status,
  onPageChange,
  onSearchChange,
  onDomainChange,
  onEnvironmentChange,
  onStatusChange,
  onClearFilters,
  onDataChanged,
  openRequest,
  environmentId,
  environmentName,
}) => {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const activeDetailId = useRef(selectedId);
  activeDetailId.current = selectedId;
  const [detailReload, setDetailReload] = useState(0);
  const [selectedFeedback, setSelectedFeedback] = useState<MyFeedbackRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [reviewRequest, setReviewRequest] = useState<{ feedbackId: string; sequence: number } | null>(null);
  const [reviewFocused, setReviewFocused] = useState(false);
  const [historySelection, setHistorySelection] = useState<AnswerHistorySelection | null>(null);
  const detailTitle = useRef<HTMLHeadingElement>(null);
  const pageSize = data?.pageSize || 20;
  const totalPages = Math.max(1, Math.ceil((data?.total || 0) / pageSize));
  const hasFilters = Boolean(search) || domain !== 'All' || environment !== 'All' || status !== 'All';

  useEffect(() => {
    if (!openRequest) return;
    clearReadCache(); setEditing(false); setSelectedFeedback(null);
    setReviewFocused(true); setReviewRequest(previous => ({ feedbackId: openRequest.feedbackId, sequence: (previous?.sequence || 0) + 1 }));
    setSelectedId(openRequest.feedbackId); setDetailReload((value) => value + 1);
  }, [openRequest?.sequence]);

  useEffect(() => {
    if (!selectedId) {
      setSelectedFeedback(null);
      setDetailLoading(false);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    void getMyFeedback(selectedId, true)
      .then((record) => {
        if (cancelled) return;
        setSelectedFeedback(record);
        setEditing(false);
      })
      .catch(() => { if (!cancelled) setSelectedFeedback(null); })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [selectedId, detailReload]);
  useEffect(() => { if (selectedId && !detailLoading) detailTitle.current?.focus({ preventScroll: true }); }, [selectedId, detailLoading]);

  const refreshDetails = async () => {
    clearReadCache();
    const id = activeDetailId.current;
    if (!id) return;
    const updated = await getMyFeedback(id, true);
    if (activeDetailId.current !== id) return;
    setSelectedFeedback(updated);
    onDataChanged();
  };

  const openReview = (id: string) => {
    setEditing(false); setReviewFocused(true); setSelectedId(id);
    setReviewRequest(previous => ({ feedbackId: id, sequence: (previous?.sequence || 0) + 1 }));
  };
  const historyEnvironmentId = reviewFocused
    ? selectedFeedback?.answerReview?.environmentId || selectedFeedback?.mainEnvironmentId || selectedFeedback?.environmentId || undefined
    : environmentId || selectedFeedback?.mainEnvironmentId || selectedFeedback?.environmentId || undefined;
  const historyEnvironmentName = !reviewFocused && environmentId ? environmentName : selectedFeedback?.answerReview?.environmentLabel || selectedFeedback?.mainEnvironmentLabel || selectedFeedback?.environmentLabel || undefined;
  const selectedHistory = historySelection?.feedbackId === selectedFeedback?.id ? historySelection : null;
  const selectedUserVerdict = selectedHistory?.selected ? answerUserVerdict(selectedHistory.selected, selectedHistory.history) : selectedFeedback?.userVerdict;

  return (
    <div className="flex flex-col gap-space-lg">
      <header className="flex flex-wrap items-end justify-between gap-space-md">
        <div>
          <p className="font-metadata uppercase tracking-wider text-ink-muted">Your submissions</p>
          <h1 className="mt-1 font-headline-lg text-ink-primary">My feedback</h1>
          <p className="mt-1 max-w-2xl font-body-md text-ink-secondary">Track what you’ve sent us, see where it stands, and read the resolution when it’s available.</p>
        </div>
      </header>

      <section className="overflow-hidden rounded-xl border border-surface-border bg-surface shadow-sm">
        <div className="flex flex-wrap items-center gap-3 border-b border-surface-border p-space-md">
          <div className="relative min-w-0 basis-full flex-1 lg:basis-64 lg:max-w-md">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[18px] text-ink-muted">search</span>
            <input
              value={search}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="Search your feedback"
              aria-label="Search your feedback"
              className="h-10 w-full rounded-lg border border-surface-border bg-canvas pl-10 pr-3 text-body-sm text-ink-primary outline-none focus:border-primary-container"
            />
          </div>
          <p className="text-metadata text-ink-muted">Click a column’s filter icon to narrow your feedback.</p>
          {hasFilters && <ActionButton label="Clear filters" icon={<FilterX />} tone="ghost" onClick={onClearFilters} />}
        </div>

        <HorizontalTableScroll label="My feedback">
          <table aria-label="My feedback" className="w-full min-w-[1100px] text-left">
            <thead className="sticky top-0 z-20 bg-surface-container-low text-metadata uppercase tracking-wide text-ink-muted">
              <tr>
                <th className="px-4 py-3 font-semibold">Feedback</th>
                <th className="px-4 py-3 font-semibold"><ColumnFilter label="Domain" value={domain} options={domains.map((value) => ({ value, label: value }))} allLabel="All domains" loading={filtersLoading} onChange={onDomainChange} /></th>
                <th className="px-4 py-3 font-semibold"><ColumnFilter label="Environment" value={environment} options={[{ value: 'nonprod', label: 'Non-production' }, { value: 'prod', label: 'Production' }, { value: 'unknown', label: 'Not recorded' }]} allLabel="All environments" onChange={(value) => onEnvironmentChange(value as AgentEnvironment | 'All')} /></th>
                <th className="px-4 py-3 font-semibold">Submitted</th>
                <th className="px-4 py-3 font-semibold">Last updated</th>
                <th className="px-4 py-3 font-semibold"><ColumnFilter label="Status" value={status} options={publicFeedbackStatuses.map((value) => ({ value, label: value }))} allLabel="All statuses" onChange={(value) => onStatusChange(value as PublicFeedbackStatus | 'All')} /></th>
                <th className="table-column-actions sticky right-0 z-30 min-w-24 border-l border-surface-border bg-surface-container-low px-4 py-3 text-right font-semibold">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border text-body-sm">
              {loading && !data ? (
                <tr><td colSpan={7}><div className="space-y-2 p-space-md" role="status" aria-label="Loading your feedback">{Array.from({ length: 5 }, (_, index) => <div key={index} className="skeleton h-14 rounded-lg" />)}</div></td></tr>
              ) : data?.items.length ? data.items.map((item) => (
                <tr key={item.id} className="transition-colors hover:bg-canvas/80">
                  <td className="max-w-[440px] px-4 py-3">
                    <div className="max-w-[420px] font-label-md font-semibold text-ink-primary">{item.title || 'Feedback submission'}</div>
                    <div className="mt-0.5 max-w-[420px] truncate text-ink-muted">{item.feedbackText}</div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <button type="button" aria-label={`Your verdict: ${latestReporterVerdict(item)}. Review updated answer for ${item.id}`} onClick={() => openReview(item.id)} className="rounded-full bg-surface-container-low px-2 py-0.5 text-metadata text-ink-secondary underline decoration-dotted underline-offset-2 outline-none hover:bg-indigo-soft focus-visible:ring-2 focus-visible:ring-primary" title="Review the saved answer's reporter verdict. The submitted verdict and AI/RCA assessments are separate.">Your verdict: {latestReporterVerdict(item)}</button>
                      {(item.answerReview?.displayAnswerId || item.answerReview?.answerId) && <span className="text-metadata text-ink-muted">Updated answer{item.answerReview.displayAnswerRevision ? ` · input r${item.answerReview.displayAnswerRevision}` : ''} · submitted verdict: {item.userVerdict}</span>}
                      <span className="rounded-full bg-surface-container-low px-2 py-0.5 text-metadata text-ink-secondary">{item.impact} impact</span>
                      {item.issueCategories.slice(0, 2).map((category) => <span key={category} className="rounded-full bg-surface-container-low px-2 py-0.5 text-metadata text-ink-muted">{category}</span>)}
                      {item.issueCategories.length > 2 && <span className="text-metadata text-ink-muted">+{item.issueCategories.length - 2}</span>}
                    </div>
                    {item.answerReview && <div className="mt-2 text-metadata"><button type="button" onClick={() => openReview(item.id)} className={`text-left underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-primary ${item.answerReview.state === 'available' ? 'font-semibold text-evidence-teal' : 'text-ink-muted'}`}>{item.answerReview.state === 'available' ? reviewMessage(item.answerReview) : item.answerReview.state === 'already_responded' ? 'Updated answer · response recorded' : item.answerReview.state === 'processing' ? 'Fresh answer check in progress' : 'Check updated-answer review'}</button></div>}
                    <div className="mt-1 font-code-xs text-ink-muted">{item.id}</div>
                  </td>
                  <td className="max-w-[240px] px-4 py-3 text-ink-secondary">{item.domain}</td>
                  <td className="px-4 py-3 text-ink-secondary"><span>{item.mainEnvironmentLabel || (item.environment === 'prod' ? 'Production' : item.environment === 'nonprod' ? 'Non-production' : 'Not recorded')}</span>{item.mainEnvironmentId && item.mainEnvironmentId !== item.environmentId && <p className="mt-1 text-metadata text-ink-muted">Promoted · originally {item.environmentLabel || (item.environment === 'nonprod' ? 'Non-production' : item.environment === 'prod' ? 'Production' : 'not recorded')}</p>}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-ink-secondary">{formatDate(item.submittedAt)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-ink-secondary">{formatDate(item.updatedAt)}</td>
                  <td className="px-4 py-3"><span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-1 font-label-sm font-semibold ${statusClass(item.publicStatus)}`}>{item.publicStatus}</span></td>
                  <td className="table-column-actions sticky right-0 z-10 border-l border-surface-border bg-surface px-4 py-3 text-right">
                    <ActionButton label="View feedback" aria-label="View" icon={<ArrowRight />} tone="soft" size="sm" expansion="overlay" align="end" onClick={() => { setReviewFocused(false); setReviewRequest(null); setSelectedId(item.id); }} />
                  </td>
                </tr>
              )) : <tr><td colSpan={7}><div className="flex min-h-64 flex-col items-center justify-center px-6 py-12 text-center">
                <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-soft text-primary-container"><span aria-hidden="true" className="material-symbols-outlined">inbox</span></span>
                <h2 className="mt-4 font-title-md text-ink-primary">No feedback found</h2>
                <p className="mt-1 max-w-sm text-body-sm text-ink-secondary">{hasFilters ? 'No submissions match these filters. Choose a different value from a column header, or clear your filters.' : 'Your submissions will appear here. You’ll be able to follow their status and see any resolution details.'}</p>
                {hasFilters ? <button type="button" onClick={onClearFilters} className="mt-4 rounded-lg border border-surface-border px-4 py-2 font-label-sm font-semibold text-primary hover:bg-indigo-soft">Clear filters</button> : <p className="mt-4 text-body-sm text-ink-muted">Use Submit feedback in the header to create your first submission.</p>}
              </div></td></tr>}
            </tbody>
          </table>
        </HorizontalTableScroll>
        {data && <footer className="flex items-center justify-between gap-3 border-t border-surface-border px-4 py-3 text-body-sm text-ink-secondary">
          <span>{data.total} submission{data.total === 1 ? '' : 's'}</span>
          <div className="flex items-center gap-2">
            <button type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)} className="rounded-lg border border-surface-border px-3 py-1.5 disabled:opacity-40">Previous</button>
            <span>{page} / {totalPages}</span>
            <button type="button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)} className="rounded-lg border border-surface-border px-3 py-1.5 disabled:opacity-40">Next</button>
          </div>
        </footer>}
      </section>

      {createPortal(<AnimatePresence>{selectedId && (
        <FeedbackDrawer key={selectedId} disabled={editing} onClose={() => { setSelectedId(null); setEditing(false); }}>
            <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-surface-border bg-surface p-4 sm:p-5">
              <div className="min-w-0"><p className="font-metadata uppercase tracking-wider text-ink-muted">Feedback details</p><h2 ref={detailTitle} data-dialog-autofocus tabIndex={-1} className="mt-1 break-words font-headline-sm text-ink-primary outline-none">{selectedFeedback?.title || 'Loading…'}</h2>{selectedFeedback && <p className="mt-1 font-code-xs text-ink-muted">{selectedFeedback.id}</p>}</div>
              <div className="flex shrink-0 items-center gap-2">
                {selectedFeedback?.canEdit && <ActionButton data-feedback-edit label="Edit submission" icon={<Pencil />} onClick={() => setEditing(true)} />}
                {!selectedFeedback?.canEdit && <span className="hidden text-metadata text-ink-muted sm:inline">Editing closed</span>}
                <button type="button" onClick={() => { setSelectedId(null); setEditing(false); }} aria-label="Close details" className="rounded-lg p-2 text-ink-muted hover:bg-state-gray-soft"><span className="material-symbols-outlined">close</span></button>
              </div>
            </header>
            {detailLoading ? <div className="space-y-3 p-space-lg" role="status"><div className="skeleton h-20 rounded-xl" /><div className="skeleton h-40 rounded-xl" /></div> : selectedFeedback && <div className="flex flex-col gap-4 p-4 sm:p-5">
              {selectedFeedback.mainEnvironmentId && <section aria-label="Current and original environments" className="rounded-lg border border-surface-border bg-canvas p-3"><p className="text-label-sm font-semibold text-ink-primary">Main environment: {selectedFeedback.mainEnvironmentLabel || selectedFeedback.mainEnvironmentKind}</p><p className="mt-1 text-metadata text-ink-secondary">Originally reported in {selectedFeedback.environmentLabel || (selectedFeedback.environment === 'nonprod' ? 'Non-production' : selectedFeedback.environment === 'prod' ? 'Production' : 'an unknown environment')}. The original submission and answers remain unchanged.</p></section>}
              <BusinessDomainPanel key={selectedFeedback.id} context={selectedFeedback} canEdit={false} onSave={async () => {}} />
              <AnswerHistoryView feedbackId={selectedFeedback.id} context={selectedFeedback} environmentId={historyEnvironmentId} environmentName={historyEnvironmentName} onDataChanged={refreshDetails} onSelectionChange={setHistorySelection} expandRequest={openRequest?.feedbackId === selectedFeedback.id ? openRequest.sequence : undefined} reviewRequest={reviewRequest?.feedbackId === selectedFeedback.id ? reviewRequest.sequence : undefined} />
              <div className="grid gap-3 rounded-xl border border-surface-border bg-canvas p-4 sm:grid-cols-4">
                <div><p className="font-metadata uppercase tracking-wide text-ink-muted">Current status</p><span className={`mt-1 inline-flex rounded-full px-2.5 py-1 font-label-sm font-semibold ${statusClass(selectedFeedback.publicStatus)}`}>{selectedFeedback.publicStatus}</span></div>
                <div><p className="font-metadata uppercase tracking-wide text-ink-muted">Your verdict · {selectedHistory?.selected ? 'selected answer' : 'submitted answer'}</p><button type="button" aria-label="Review or change your answer verdict" onClick={() => openReview(selectedFeedback.id)} className="mt-1 text-left font-label-sm font-semibold text-primary underline underline-offset-2" title="Review the updated answer without editing your original submitted verdict">{selectedUserVerdict} · Review updated answer</button><p className="mt-1 text-metadata text-ink-muted">Submitted verdict: {selectedFeedback.userVerdict}</p></div>
                <div><p className="font-metadata uppercase tracking-wide text-ink-muted">Business impact</p><p className="mt-1 font-label-sm font-semibold text-ink-primary">{selectedFeedback.impact}</p></div>
                <div><p className="font-metadata uppercase tracking-wide text-ink-muted">Fix version</p><p className="mt-1 font-label-sm font-semibold text-ink-primary">{selectedFeedback.resolutionVersion || 'Not recorded'}</p></div>
              </div>
              {(!environmentId || environmentId === selectedFeedback.environmentId) && <ReporterReviewSummary feedback={selectedFeedback} />}
              {selectedFeedback.publicStatus === 'Resolved' && selectedFeedback.resolutionSummary && <section className="rounded-xl border border-surface-border bg-canvas p-4"><h3 className="font-label-md font-semibold text-ink-primary">Resolution</h3><p className="mt-2 whitespace-pre-wrap text-body-sm text-ink-secondary">{selectedFeedback.resolutionSummary}</p>{selectedFeedback.resolvedAt && <p className="mt-2 text-metadata text-ink-muted">Resolved {formatDate(selectedFeedback.resolvedAt)}</p>}</section>}
              <>
                {selectedFeedback.question && <section><h3 className="mb-2 font-label-md font-semibold text-ink-primary">Question</h3><ContentPreview label="Submitted question" compact><p className="whitespace-pre-wrap">{selectedFeedback.question}</p></ContentPreview></section>}
                <CollapsibleSection key={`notes-${selectedFeedback.id}`} title="Your feedback & expected answer" summary="Details you submitted">
                <section><h3 className="mb-2 font-label-md font-semibold text-ink-primary">Your feedback</h3><ContentPreview label="Submitted feedback" compact><p className="whitespace-pre-wrap">{selectedFeedback.feedbackText || 'No additional written feedback was included in this submission.'}</p></ContentPreview></section>
                {selectedFeedback.issueCategories.length > 0 && <section><h3 className="font-label-md font-semibold text-ink-primary">Categories you selected</h3><div className="mt-2 flex flex-wrap gap-2">{selectedFeedback.issueCategories.map((category) => <span key={category} className="rounded-full bg-surface-container-low px-3 py-1 text-label-sm text-ink-secondary">{category}</span>)}</div></section>}
                <section className="mt-4"><h3 className="mb-2 font-label-md font-semibold text-ink-primary">Expected answer you submitted</h3>{selectedFeedback.expectedBehavior ? <><ContentPreview label="Submitted expected answer"><p className="whitespace-pre-wrap">{selectedFeedback.expectedBehavior}</p></ContentPreview><p className="mt-2 text-metadata text-ink-muted">{selectedFeedback.expectedBehaviorVerified ? 'Reviewed against source evidence' : 'Not yet verified by the review team'}</p></> : <p className="mt-2 text-body-sm text-ink-muted">No expected answer was recorded for this submission.</p>}</section>
                </CollapsibleSection>
              </>
              {selectedFeedback.legacyContext && <CollapsibleSection key={`legacy-${selectedFeedback.id}`} title="Original submission details" summary="Imported references and historical context">
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {selectedFeedback.legacyContext.dataSource && <LegacyField label="Data source" value={selectedFeedback.legacyContext.dataSource} />}
                  {selectedFeedback.legacyContext.subDomain && <LegacyField label="Submitted subdomain" value={selectedFeedback.legacyContext.subDomain} />}
                  {selectedFeedback.legacyContext.answerStatus && <LegacyField label="Original answer status" value={selectedFeedback.legacyContext.answerStatus} />}
                  {selectedFeedback.legacyContext.language && <LegacyField label="Language" value={selectedFeedback.legacyContext.language} />}
                  {selectedFeedback.legacyContext.followUp && <LegacyField label="Follow-up" value={selectedFeedback.legacyContext.followUp} />}
                </div>
                {selectedFeedback.legacyContext.priorResolution && <div className="mt-3 rounded-lg border border-review-amber/20 bg-review-soft/50 p-3"><p className="font-label-sm font-semibold text-ink-primary">Previously recorded resolution</p><p className="mt-1 whitespace-pre-wrap text-body-sm text-ink-secondary">{selectedFeedback.legacyContext.priorResolution}</p><p className="mt-2 text-metadata text-ink-muted">Imported historical note; not independently verified by this review workflow.</p></div>}
              </CollapsibleSection>}
              <section><h3 className="mb-2 font-label-md font-semibold text-ink-primary">Agent response</h3><ContentPreview key={`${selectedFeedback.id}-${selectedFeedback.revision}`} label="Submitted agent response">{selectedFeedback.agentResponse ? <AnswerMarkdown content={selectedFeedback.agentResponse} /> : <p className="text-body-sm text-ink-muted">No response snapshot is available for this submission.</p>}</ContentPreview></section>
              <CollapsibleSection key={`status-${selectedFeedback.id}`} title="Status history" summary={`${selectedFeedback.events.length} recorded updates`}><ol className="flex flex-col gap-3 border-l-2 border-surface-border pl-4">
                {selectedFeedback.events.map((event: MyFeedbackEvent) => <li key={event.id} className="relative"><span className="absolute -left-[22px] top-1 h-2.5 w-2.5 rounded-full bg-primary-container ring-4 ring-surface"/><p className="font-label-sm font-semibold text-ink-primary">{event.status}</p><p className="mt-0.5 text-body-sm text-ink-secondary">{event.message}</p><p className="mt-1 text-metadata text-ink-muted">{formatDate(event.createdAt)}</p></li>)}
              </ol></CollapsibleSection>
            </div>}
        </FeedbackDrawer>
      )}</AnimatePresence>, document.body)}
      <AnimatePresence>{editing && selectedFeedback && <FeedbackEditView key={selectedFeedback.id} feedback={selectedFeedback} onCancel={() => setEditing(false)} onSaved={(updated) => { setSelectedFeedback(updated); setEditing(false); onDataChanged(); }} />}</AnimatePresence>
    </div>
  );
};

function FeedbackDrawer({ children, disabled, onClose }: { children: React.ReactNode; disabled: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLElement>(null);
  useDialogFocus(dialog);
  return <AnimatedDiv surface="backdrop" inert={disabled} className="fixed inset-0 z-50 flex justify-end bg-ink-primary/20 pt-14" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <AnimatedSection ref={dialog} surface="drawer" role="dialog" aria-modal="true" aria-label="Feedback details" tabIndex={-1} onKeyDown={(event) => containDialogFocus(event, onClose)} className="flex h-full w-full max-w-4xl flex-col overflow-y-auto border-l border-surface-border bg-surface shadow-2xl outline-none">
      {children}
    </AnimatedSection>
  </AnimatedDiv>;
}

function LegacyField({ label, value }: { label: string; value: string }) {
  return <div><p className="font-metadata uppercase tracking-wide text-ink-muted">{label}</p><p className="mt-1 whitespace-pre-wrap text-body-sm text-ink-secondary">{value}</p></div>;
}

function ReporterReviewSummary({ feedback }: { feedback: MyFeedbackRecord }) {
  if (feedback.publicStatus === 'Resolved' && feedback.resolutionSummary && !feedback.reviewedCause && !feedback.reviewedDefect && !feedback.preliminaryCause && !feedback.publicMessage && !feedback.proposedFix) return null;
  return <section className="rounded-xl border border-surface-border p-4" aria-label="RCA / review reason">
    <h3 className="font-label-md font-semibold text-ink-primary">Submitted answer’s RCA / review reason</h3><p className="mt-1 text-metadata text-ink-muted">This assessment belongs to the submitted answer. Updated answers have their own user verdict, AI comparison and RCA in answer history.</p>
    {feedback.reviewedCause && <p className="mt-2 text-body-sm text-ink-secondary"><strong>Confirmed cause:</strong> {formatRcaLabel(feedback.reviewedCause)}</p>}
    {feedback.reviewedDefect && <p className="mt-1 text-body-sm text-ink-secondary"><strong>RCA defect:</strong> {formatRcaLabel(feedback.reviewedDefect)}</p>}
    {feedback.preliminaryCause && <div className="mt-3 rounded-lg border border-surface-border bg-canvas p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-label-sm font-medium text-ink-primary">Preliminary AI cause · not verified</p>{feedback.preliminaryCauseConfidence != null && <span className="text-metadata text-ink-muted">{Math.round(feedback.preliminaryCauseConfidence * 100)}% confidence</span>}</div><p className="mt-1 text-body-sm font-semibold text-ink-primary">{formatRcaLabel(feedback.preliminaryCause)}</p>{feedback.preliminarySubdomain && <p className="mt-1 text-body-sm text-ink-secondary"><strong>Suggested subdomain:</strong> {formatRcaLabel(feedback.preliminarySubdomain)}</p>}{feedback.preliminaryCauseRationale && <div className="mt-2"><ContentPreview label="Preliminary review reason" compact><p className="whitespace-pre-wrap">{feedback.preliminaryCauseRationale}</p></ContentPreview></div>}<p className="mt-2 text-metadata text-ink-muted">This AI suggestion may change after evidence review.</p></div>}
    {feedback.publicMessage && <p className="mt-2 whitespace-pre-wrap text-body-sm text-ink-secondary">{feedback.publicMessage}</p>}
    {feedback.preliminaryDefect && <p className="mt-2 text-body-sm text-ink-secondary"><strong>Suggested RCA defect · not verified:</strong> {formatRcaLabel(feedback.preliminaryDefect)}</p>}
    {feedback.resolutionSummary && feedback.publicStatus !== 'Resolved' && <p className="mt-2 whitespace-pre-wrap text-body-sm text-ink-secondary">{feedback.resolutionSummary}</p>}
    {feedback.proposedFix && <div className="mt-3 rounded-lg border border-surface-border p-3"><p className="text-label-sm font-medium text-ink-primary">Proposed remediation · not confirmed shipped</p><p className="mt-1 whitespace-pre-wrap text-body-sm text-ink-secondary">{feedback.proposedFix}</p></div>}
    {!feedback.reviewedCause && !feedback.preliminaryCause && !feedback.proposedFix && !feedback.publicMessage && !feedback.resolutionSummary && <p className="mt-2 text-body-sm text-ink-muted">The review team hasn’t shared a cause or reason yet.</p>}
  </section>;
}
