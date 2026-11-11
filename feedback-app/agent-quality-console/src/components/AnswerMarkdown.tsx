import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function AnswerMarkdown({ content }: { content: string }) {
  return (
    <div className="answer-markdown rounded-lg border border-surface-border bg-canvas px-3.5 py-3 text-body-md text-ink-secondary">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
