import React from 'react';
import { CheckCircle2, HelpCircle, Minus, ShieldAlert, XCircle } from 'lucide-react';

/** Always render a verdict, including Correct, blank and future values. */
export const UserVerdictBadge: React.FC<{ value?: string | null }> = ({ value }) => {
  const submitted = typeof value === 'string' ? value.trim() : '';
  const labels = ['Correct', 'Incorrect', 'Partially correct', 'Unsafe or misleading', 'Not specified'];
  const label = labels.find((entry) => entry.toLowerCase() === submitted.toLowerCase()) || submitted || 'Not specified';
  const Icon = label === 'Correct' ? CheckCircle2 : label === 'Incorrect' ? XCircle : label === 'Unsafe or misleading' ? ShieldAlert : label === 'Not specified' ? Minus : HelpCircle;
  const tone = label === 'Correct' ? 'bg-evidence-soft text-evidence-teal' : ['Incorrect', 'Unsafe or misleading'].includes(label) ? 'bg-issue-soft text-issue-red' : label === 'Partially correct' ? 'bg-review-soft text-review-amber' : 'bg-state-gray-soft text-ink-secondary';
  return <span data-verdict={label} className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1 text-label-sm ${tone}`}><Icon size={14} aria-hidden="true" /><span>{label}</span></span>;
};
