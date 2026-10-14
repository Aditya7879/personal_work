import React, { useState } from 'react';
import { FeedbackItem, ViewPath } from '../types';

interface FeedbackDetailViewProps {
  item: FeedbackItem;
  onNavigate: (view: ViewPath, targetId?: string) => void;
  onPromoteToCandidate?: (item: FeedbackItem) => void;
  onSaveTriage?: (id: string, updates: Record<string, unknown>) => Promise<void>;
}

export const FeedbackDetailView: React.FC<FeedbackDetailViewProps> = ({
  item,
  onNavigate,
  onPromoteToCandidate,
  onSaveTriage,
}) => {
  const [activeRightTab, setActiveRightTab] = useState<'evidence' | 'citations' | 'trace' | 'graph'>('evidence');
  const [evidenceAttached, setEvidenceAttached] = useState<boolean>(true);
  const [selectedRca, setSelectedRca] = useState(item.confirmedRca || 'Not classified');
  const [selectedSubCategory, setSelectedSubCategory] = useState(item.defectSubCategory || 'Not classified');
  const [reviewerNotes, setReviewerNotes] = useState(item.reviewerNotes || '');
  const [recommendedFix, setRecommendedFix] = useState(item.recommendedFix || '');
  const [expectedBehavior, setExpectedBehavior] = useState(item.groundTruthHint || '');
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState('');
  const lifecycle = ['Submitted', 'Triaged', 'Evidence review', 'Golden candidate', 'Approved for dataset'];
  const terminalState = ['Rejected', 'Duplicate', 'Needs more information'].includes(item.state);
  const currentLifecycleIndex = lifecycle.indexOf(item.state);

  const triggerToast = (msg: string) => {
    setToastMessage(msg);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 3000);
  };

  return (
    <div className="flex flex-col w-full gap-space-lg pb-24 animate-in fade-in duration-200">
      {/* Toast Notification */}
      {showToast && (
        <div className="fixed top-18 right-8 z-50 flex items-center gap-space-sm px-space-md py-space-sm bg-surface shadow-xl rounded-xl border border-surface-border animate-in fade-in slide-in-from-top-2">
          <div className="w-6 h-6 rounded-full bg-evidence-soft text-evidence-teal flex items-center justify-center">
            <span className="material-symbols-outlined text-[16px]">check_circle</span>
          </div>
          <div className="flex flex-col">
            <span className="font-title-md text-title-md text-ink-primary font-semibold">{toastMessage}</span>
            <span className="font-metadata text-metadata text-ink-muted">Triage queue updated · Dataset candidate registry synced</span>
          </div>
          <button
            type="button"
            onClick={() => setShowToast(false)}
            className="ml-space-sm text-ink-muted hover:text-ink-primary p-0.5 rounded transition-colors cursor-pointer"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>
      )}

      {/* Top Navigation / Context Header */}
      <section className="bg-surface rounded-xl shadow-sm p-space-md flex flex-wrap items-center justify-between gap-space-md border border-surface-border">
        <div className="flex items-center gap-space-md flex-wrap">
          <button
            type="button"
            onClick={() => onNavigate('feedback-inbox')}
            className="flex items-center gap-1.5 text-ink-secondary hover:text-ink-primary font-label-md text-label-md transition-colors px-2.5 py-1.5 rounded-lg hover:bg-state-gray-soft cursor-pointer"
          >
            <span className="material-symbols-outlined text-[18px]">arrow_back</span>
            <span>Feedback inbox</span>
          </button>

          <div className="h-4 w-px bg-surface-border"></div>

          <div className="flex items-center gap-space-xs bg-surface-container-low px-2.5 py-1 rounded-lg">
            <span className="font-code-sm text-code-sm font-semibold text-primary font-mono">{item.id}</span>
          </div>

          <h1 className="font-headline-sm text-headline-sm text-ink-primary tracking-tight font-semibold">
            {item.title}
          </h1>

          <div className="relative inline-block">
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-review-soft text-review-amber font-label-sm text-label-sm font-semibold shadow-xs">
              <span className="w-1.5 h-1.5 rounded-full bg-review-amber animate-pulse"></span>
               <span>{item.state}</span>
              <span className="material-symbols-outlined text-[16px]">expand_more</span>
            </span>
          </div>
        </div>

        {/* Actions Right */}
        <div className="flex items-center gap-space-sm flex-wrap">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-surface-container-low rounded-lg shadow-xs hover:bg-state-gray-soft cursor-pointer transition-colors border border-surface-border">
             <span className="w-5 h-5 rounded-full bg-primary-container text-on-primary text-[10px] flex items-center justify-center">{(item.assignedReviewer || '—').slice(0, 1).toUpperCase()}</span>
             <span className="font-label-sm text-label-sm text-ink-primary font-medium">{item.assignedReviewer || 'Unassigned'}</span>
            <span className="material-symbols-outlined text-[16px] text-ink-muted">unfold_more</span>
          </div>

          <button
            type="button"
            onClick={() => {
              if (onSaveTriage) void onSaveTriage(item.id, { state: 'Duplicate' }).then(() => onNavigate('feedback-inbox'));
            }}
            className="px-3 py-1.5 rounded-lg bg-surface text-ink-secondary hover:text-ink-primary font-label-sm text-label-sm hover:bg-state-gray-soft transition-colors shadow-xs border border-surface-border cursor-pointer"
          >
            Mark duplicate
          </button>

          <button
            aria-label="More Options"
            type="button"
            onClick={() => triggerToast('More options opened')}
            className="p-1.5 rounded-lg bg-surface text-ink-secondary hover:text-ink-primary hover:bg-state-gray-soft transition-colors shadow-xs border border-surface-border cursor-pointer"
          >
            <span className="material-symbols-outlined text-[20px]">more_horiz</span>
          </button>
        </div>
      </section>

      {/* Main 3-Column Workspace */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-space-lg items-start">
        {/* LEFT COLUMN: Metadata & Workflow (3 cols) */}
        <div className="xl:col-span-3 flex flex-col gap-space-md">
          {/* User Feedback Card */}
          <div className="bg-surface rounded-xl p-space-md shadow-sm flex flex-col gap-space-md border border-surface-border">
            <div className="flex items-center justify-between">
              <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted font-semibold">
                Feedback Signal
              </span>
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-issue-soft text-issue-red font-label-sm text-label-sm font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-issue-red"></span>
                {item.userVerdict}
              </span>
            </div>

            <blockquote className="bg-surface-container-low rounded-lg p-3 text-body-sm text-ink-secondary italic relative border-l-2 border-primary">
              <span className="material-symbols-outlined text-primary/20 text-[28px] absolute top-1.5 right-2 select-none">
                format_quote
              </span>
              "{item.fullQuote || item.excerpt}"
            </blockquote>

            {item.runContext?.source === 'legacy_csv_import' && (
              <div className="rounded-lg border border-surface-border bg-canvas p-3">
                <h3 className="mb-2 font-metadata uppercase tracking-wider text-ink-muted">Imported feedback context</h3>
                <div className="flex flex-col gap-2 text-body-sm text-ink-secondary">
                  {(['data_source', 'sub_domain', 'answer_status', 'follow_up', 'developer_remarks', 'resolution', 'language'] as const).map((key) => {
                    const value = item.runContext?.[key];
                    if (value == null || value === '') return null;
                    return <div key={key}><span className="font-label-sm font-semibold text-ink-primary">{key.replaceAll('_', ' ')}:</span> <span className="whitespace-pre-wrap">{String(value)}</span></div>;
                  })}
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-2 bg-state-gray-soft/40 p-2.5 rounded-lg">
              <div>
                <span className="font-metadata text-metadata text-ink-muted block">Impact</span>
                <span className="font-label-sm text-label-sm text-issue-red font-semibold">{item.impact} Priority</span>
              </div>
              <div>
                <span className="font-metadata text-metadata text-ink-muted block">Reported</span>
                <span className="font-label-sm text-label-sm text-ink-primary">{item.reportedTime}</span>
              </div>
              <div className="col-span-2 pt-1">
                <span className="font-metadata text-metadata text-ink-muted block">Reporter</span>
                <span className="font-code-xs text-code-xs text-ink-primary truncate block font-medium font-mono">
                  {item.reporter}
                </span>
              </div>
            </div>

            {/* Tags */}
            <div className="flex flex-col gap-1.5 pt-1">
              <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted font-semibold">
                Taxonomy Tags
              </span>
              <div className="flex flex-wrap gap-1.5">
                {item.tags.map((tag) => (
                  <span key={tag} className="px-2 py-0.5 rounded bg-surface-container-low text-ink-secondary font-code-xs text-code-xs font-mono">
                    {tag}
                  </span>
                ))}
              </div>
            </div>

            {item.correlatedReports?.length ? <div className="flex flex-col gap-1.5 pt-2 border-t border-surface-border">
              <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted font-semibold">
                Correlated Reports
              </span>
              <div className="flex items-center gap-2 p-2 rounded-lg bg-surface-container-low hover:bg-state-gray-soft text-ink-primary transition-colors cursor-pointer">
                <span className="material-symbols-outlined text-[16px] text-primary">link</span>
                <div className="flex flex-col min-w-0">
                   <span className="font-label-sm text-label-sm font-medium truncate">{item.correlatedReports.length} related feedback reports</span>
                  <span className="font-code-xs text-code-xs text-ink-muted truncate font-mono">
                     {item.correlatedReports.join(', ')}
                  </span>
                </div>
              </div>
            </div> : null}
          </div>

          {/* Stepping Workflow Path */}
          <div className="bg-surface rounded-xl p-space-md shadow-sm flex flex-col gap-space-md border border-surface-border">
            <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted font-semibold">
              Quality Lifecycle Path
            </span>
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
          </div>
        </div>

        {/* CENTER COLUMN: Investigation & Assessment (5 cols) */}
        <div className="xl:col-span-5 flex flex-col gap-space-md">
          {/* SECTION 1: Original Run Context */}
          <section className="bg-surface rounded-xl p-space-md shadow-sm flex flex-col gap-space-md border border-surface-border">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[20px]">smart_toy</span>
                <h2 className="font-headline-sm text-headline-sm text-ink-primary font-semibold">Original Run Context</h2>
              </div>
              <span className="font-code-xs text-code-xs bg-surface-container-low px-2 py-0.5 rounded text-ink-muted font-mono">
                 Latency not captured
              </span>
            </div>

            {/* Telemetry pills */}
            <div className="grid grid-cols-2 gap-2 text-label-sm">
              <div className="bg-surface-container-low p-2 rounded-lg">
                <span className="font-metadata text-metadata text-ink-muted block">Run ID</span>
                <span className="font-code-xs text-code-xs font-semibold text-primary font-mono">{item.runId}</span>
              </div>
              <div className="bg-surface-container-low p-2 rounded-lg">
                <span className="font-metadata text-metadata text-ink-muted block">Agent &amp; Model</span>
                <span className="font-body-sm text-body-sm text-ink-primary font-medium truncate block">
                  {item.agentName} · {item.model}
                </span>
              </div>
              <div className="col-span-2 bg-surface-container-low p-2 rounded-lg flex items-center justify-between">
                <div>
                  <span className="font-metadata text-metadata text-ink-muted block">Prompt Spec</span>
                   <span className="font-code-xs text-code-xs text-ink-secondary font-mono">Not captured</span>
                </div>
                <span className="px-2 py-0.5 bg-evidence-soft text-evidence-teal font-code-xs text-code-xs rounded font-mono">
                   Runtime parameters not captured
                </span>
              </div>
            </div>

            {/* Question */}
            <div className="flex flex-col gap-1">
              <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted font-semibold">
                Evaluated User Prompt
              </span>
              <div className="p-3 rounded-lg bg-surface-container-low font-body-md text-body-md font-medium text-ink-primary border border-surface-border">
                "{item.prompt}"
              </div>
            </div>

            {/* Final Agent Answer Box */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted font-semibold">
                  Generated Agent Response
                </span>
                <span className="font-metadata text-metadata text-ink-muted flex items-center gap-1 font-semibold">
                  {item.highlightedDefect ? 'Defect excerpt attached' : 'Answer snapshot'}
                </span>
              </div>
               <div className="p-3.5 rounded-lg bg-canvas text-body-md text-ink-secondary leading-relaxed border border-surface-border whitespace-pre-wrap">
                 {item.generatedAnswer || 'No answer snapshot was attached to this feedback.'}
               </div>
            </div>
          </section>

          {/* SECTION 2: Reviewer Assessment */}
          <section className="bg-surface rounded-xl p-space-md shadow-sm flex flex-col gap-space-md border border-surface-border">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-primary-container text-[20px]">fact_check</span>
                <h2 className="font-headline-sm text-headline-sm text-ink-primary font-semibold">Reviewer Assessment</h2>
              </div>
              <span className="px-2 py-0.5 rounded-full bg-indigo-soft text-primary-container font-metadata text-metadata font-semibold">
                {item.confirmedRca ? 'Reviewer confirmed' : 'Needs review'}
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-space-md">
              {/* Confirmed RCA */}
              <div className="flex flex-col gap-1">
                <label className="font-metadata text-metadata text-ink-muted uppercase font-semibold">Confirmed RCA</label>
                <select
                  value={selectedRca}
                  onChange={(e) => setSelectedRca(e.target.value)}
                  className="p-2.5 rounded-lg bg-surface-container-low text-ink-primary font-label-md font-semibold border border-transparent hover:border-surface-border focus:outline-none cursor-pointer"
                >
                 <option value="Not classified">Not classified</option>
                 <option value="Retrieval failure">Retrieval failure</option>
                  <option value="Knowledge/source gap">Knowledge / source gap</option>
                  <option value="Reasoning error">Reasoning error</option>
                  <option value="Citation failure">Citation failure</option>
                  <option value="Table interpretation error">Table interpretation error</option>
                  <option value="Wrong region or scope">Wrong region or scope</option>
                </select>
              </div>

              {/* Sub-category */}
              <div className="flex flex-col gap-1">
                <label className="font-metadata text-metadata text-ink-muted uppercase font-semibold">Defect Sub-category</label>
                <select
                  value={selectedSubCategory}
                  onChange={(e) => setSelectedSubCategory(e.target.value)}
                  className="p-2.5 rounded-lg bg-surface-container-low text-ink-primary font-label-md border border-transparent hover:border-surface-border focus:outline-none cursor-pointer"
                >
                   <option value="Not classified">Not classified</option>
                   <option value="Outdated vector chunk in top-k">Outdated vector chunk in top-k</option>
                  <option value="Embedding distance threshold too low">Embedding distance threshold too low</option>
                  <option value="PDF table line break collapse">PDF table line break collapse</option>
                  <option value="Incorrect paragraph anchor">Incorrect paragraph anchor</option>
                </select>
              </div>
            </div>

            {/* Rationale */}
            <div className="flex flex-col gap-1">
              <label className="font-metadata text-metadata text-ink-muted uppercase font-semibold">Expected behavior for a golden case</label>
              <textarea value={expectedBehavior} onChange={(event) => setExpectedBehavior(event.target.value)} rows={3} placeholder="Write reviewer-verified expected behavior; user feedback text is not ground truth." className="w-full rounded-lg border border-surface-border bg-canvas p-3 text-body-sm text-ink-primary" />
            </div>

            <div className="flex flex-col gap-1">
              <label className="font-metadata text-metadata text-ink-muted uppercase font-semibold">
                Reviewer Root Cause Rationale
              </label>
              <textarea value={reviewerNotes} onChange={(event) => setReviewerNotes(event.target.value)} rows={3} placeholder="Record reviewer rationale" className="w-full rounded-lg border border-surface-border bg-canvas p-3 text-body-sm text-ink-primary" />
            </div>

            {/* Recommended Fix */}
            <div className="flex flex-col gap-1">
              <label className="font-metadata text-metadata text-ink-muted uppercase font-semibold">
                Recommended Remediation
              </label>
              <textarea value={recommendedFix} onChange={(event) => setRecommendedFix(event.target.value)} rows={2} placeholder="Optional recommended remediation" className="w-full rounded-lg border border-surface-border bg-indigo-soft/30 p-3 text-body-sm text-ink-primary" />
            </div>
          </section>

          {/* SECTION 3: Claim Checklist Component */}
          <section className="bg-surface rounded-xl p-space-md shadow-sm flex flex-col gap-space-md border border-surface-border">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[20px]">checklist_rtl</span>
                <h2 className="font-headline-sm text-headline-sm text-ink-primary font-semibold">Claim-Level Verification</h2>
              </div>
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
           </section>
         </div>

         {/* RIGHT COLUMN: Evidence, Citations & Trace Tabs (4 cols) */}
        <div className="xl:col-span-4 flex flex-col gap-space-md">
          <div className="bg-surface rounded-xl shadow-sm p-space-md flex flex-col gap-space-md border border-surface-border">
            {/* Tab Header */}
            <div className="flex items-center justify-between bg-surface-container-low p-1 rounded-lg">
              <button
                type="button"
                onClick={() => setActiveRightTab('evidence')}
                className={`flex-1 py-1.5 rounded-md font-label-sm text-label-sm transition-all cursor-pointer ${
                  activeRightTab === 'evidence'
                    ? 'bg-surface text-primary-container font-semibold shadow-xs'
                    : 'text-ink-muted hover:text-ink-primary'
                }`}
              >
                 Evidence ({item.evidence?.length || 0})
              </button>
              <button
                type="button"
                onClick={() => setActiveRightTab('citations')}
                className={`flex-1 py-1.5 rounded-md font-label-sm text-label-sm transition-all cursor-pointer ${
                  activeRightTab === 'citations'
                    ? 'bg-surface text-primary-container font-semibold shadow-xs'
                    : 'text-ink-muted hover:text-ink-primary'
                }`}
              >
                Citations
              </button>
              <button
                type="button"
                onClick={() => setActiveRightTab('trace')}
                className={`flex-1 py-1.5 rounded-md font-label-sm text-label-sm transition-all cursor-pointer ${
                  activeRightTab === 'trace'
                    ? 'bg-surface text-primary-container font-semibold shadow-xs'
                    : 'text-ink-muted hover:text-ink-primary'
                }`}
              >
                Trace
              </button>
              <button
                type="button"
                onClick={() => setActiveRightTab('graph')}
                className={`flex-1 py-1.5 rounded-md font-label-sm text-label-sm transition-all cursor-pointer ${
                  activeRightTab === 'graph'
                    ? 'bg-surface text-primary-container font-semibold shadow-xs'
                    : 'text-ink-muted hover:text-ink-primary'
                }`}
              >
                Graph
              </button>
            </div>

            {/* Evidence and provenance captured with the feedback record */}
            {activeRightTab === 'evidence' && (
              item.evidence?.length ? (
                <div className="flex flex-col gap-3">
                  {item.evidence.map((evidence, index) => (
                    <article key={`${evidence.id || index}`} className="rounded-xl border border-surface-border bg-surface-container-lowest p-space-md">
                      <div className="flex items-center gap-2">
                        {evidence.id && <span className="rounded bg-evidence-soft px-2 py-0.5 font-code-xs font-semibold text-evidence-teal">[{evidence.id}]</span>}
                        <span className="font-label-sm font-semibold text-ink-primary">{evidence.source || 'Source not recorded'}</span>
                        {evidence.page != null && <span className="font-metadata text-ink-muted">p. {evidence.page}</span>}
                      </div>
                      {evidence.excerpt && <blockquote className="mt-3 border-l-2 border-evidence-teal bg-canvas p-3 text-body-sm text-ink-secondary">{evidence.excerpt}</blockquote>}
                    </article>
                  ))}
                </div>
              ) : <EmptyEvidence text="No evidence snapshot was attached to this feedback." />
            )}
            {activeRightTab === 'citations' && (
              item.evidence?.length ? <div className="flex flex-col gap-2">{item.evidence.map((evidence, index) => <div key={evidence.id || index} className="rounded-lg border border-surface-border bg-canvas p-3"><span className="font-code-xs font-semibold text-evidence-teal">{evidence.id || `Evidence ${index + 1}`}</span><p className="mt-1 text-body-sm text-ink-primary">{evidence.source || 'Citation source not recorded'}{evidence.page != null ? ` · page ${evidence.page}` : ''}</p></div>)}</div> : <EmptyEvidence text="No citation records were attached to this feedback." />
            )}
            {activeRightTab === 'trace' && <EmptyEvidence text="Agent retrieval trace was not included in this feedback export." />}
            {activeRightTab === 'graph' && <EmptyEvidence text="No graph snapshot was attached to this feedback." />}
          </div>
        </div>
      </div>

      {/* Bottom Sticky Action Bar */}
      <footer className="fixed bottom-0 left-60 right-0 h-16 bg-surface/95 backdrop-blur-sm shadow-xl z-30 px-margin flex items-center justify-between border-t border-surface-border">
        <div className="flex items-center gap-space-md">
          <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-state-gray"></span>
              <span className="font-label-sm text-label-sm text-ink-primary font-medium">
                Feedback workflow state
            </span>
          </div>
          <span className="text-outline-variant select-none">|</span>
          <span className="font-metadata text-metadata text-ink-muted font-mono">
             Evidence {item.evidence?.length || 0} attached · {item.claims?.length || 0} claims recorded
          </span>
        </div>

        <div className="flex items-center gap-space-sm">
          <button
            type="button"
            onClick={() => {
              if (!onSaveTriage) return;
              void onSaveTriage(item.id, {
                confirmed_rca: selectedRca === 'Not classified' ? null : selectedRca,
                subcategory: selectedSubCategory === 'Not classified' ? null : selectedSubCategory,
                reviewer_notes: reviewerNotes,
                recommended_fix: recommendedFix,
                expected_behavior: expectedBehavior,
                state: 'Evidence review',
              }).then(() => triggerToast('Reviewer assessment saved.'))
                .catch((error: Error) => triggerToast(error.message));
            }}
            className="px-3.5 py-2 rounded-lg bg-surface hover:bg-state-gray-soft text-ink-secondary hover:text-ink-primary font-label-md text-label-md shadow-xs transition-colors border border-surface-border cursor-pointer"
          >
            Save draft
          </button>

          <button
            type="button"
            onClick={() => {
              if (onSaveTriage) void onSaveTriage(item.id, { state: 'Needs more information' }).then(() => triggerToast('Feedback marked as needing more information.'));
            }}
            className="px-3.5 py-2 rounded-lg bg-surface hover:bg-state-gray-soft text-ink-secondary hover:text-ink-primary font-label-md text-label-md shadow-xs transition-colors border border-surface-border cursor-pointer"
          >
            Request more information
          </button>

          <button
            type="button"
            onClick={() => {
              if (!onSaveTriage) return;
              void onSaveTriage(item.id, { state: 'Rejected' })
                .then(() => { triggerToast('Feedback rejected.'); onNavigate('feedback-inbox'); })
                .catch((error: Error) => triggerToast(error.message));
            }}
            className="px-3.5 py-2 rounded-lg bg-issue-soft hover:bg-red-100 text-issue-red font-label-md text-label-md transition-colors cursor-pointer"
          >
            Reject feedback
          </button>

          <button
            type="button"
            onClick={() => {
              if (onPromoteToCandidate) {
                onPromoteToCandidate(item);
              } else {
                triggerToast('Candidate promoted to Golden Dataset v1.4!');
                onNavigate('golden-datasets');
              }
            }}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-dataset-purple hover:bg-tertiary-container text-on-primary font-label-md text-label-md font-semibold shadow-md transition-all active:scale-[0.98] cursor-pointer"
          >
            <span className="material-symbols-outlined text-[18px]">star</span>
            <span>Create golden candidate</span>
          </button>
        </div>
      </footer>
    </div>
  );
};

function EmptyEvidence({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-surface-border bg-canvas p-4 text-body-sm text-ink-muted">{text}</div>;
}
