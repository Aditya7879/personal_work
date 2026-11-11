import React, { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { LoaderCircle } from 'lucide-react';

type ActionButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> & {
  label: string;
  icon: ReactNode;
  compactLabel?: string;
  labelAdornment?: ReactNode;
  trailingIcon?: ReactNode;
  children?: ReactNode;
  tone?: 'outline' | 'ghost' | 'soft';
  size?: 'sm' | 'md';
  expansion?: 'inline' | 'overlay';
  align?: 'start' | 'end';
  loading?: boolean;
  expanded?: boolean;
  containerClassName?: string;
};

/** Presentation only: native button semantics, callbacks and permissions are unchanged. */
export const ActionButton = forwardRef<HTMLButtonElement, ActionButtonProps>(function ActionButton({
  label, icon, compactLabel, labelAdornment, trailingIcon, children, tone = 'outline', size = 'md',
  expansion = 'inline', align = 'start', loading = false, expanded = false, containerClassName = '',
  className = '', type = 'button', title, disabled, 'aria-label': ariaLabel, 'aria-expanded': ariaExpanded, ...props
}, ref) {
  const heldOpen = expanded || loading || ariaExpanded === true || ariaExpanded === 'true';
  // Keep the short caption anchored and append the remainder. Replacing two
  // captions can briefly shrink a button and move it out from under the pointer.
  const reveal = compactLabel ? label.startsWith(compactLabel) ? label.slice(compactLabel.length).trimStart() : `· ${label}` : label;
  return <span className={`action-button-shell ${containerClassName}`} data-expansion={expansion} data-align={align} data-size={size}
    title={disabled ? title || label : undefined}>
    {expansion === 'overlay' && <span className="action-button-footprint" aria-hidden="true"><span className="action-button-icon" />{compactLabel && <span className="action-button-footprint-label">{compactLabel}</span>}{trailingIcon && <span className="action-button-trailing" />}</span>}
    <button {...props} ref={ref} type={type} disabled={disabled} aria-label={ariaLabel || label} aria-expanded={ariaExpanded}
      aria-busy={loading || props['aria-busy']} title={title || label} data-action-button data-action-expanded={heldOpen}
      data-tone={tone} className={`action-button ${className}`}>
      <span className="action-button-icon" aria-hidden="true">{loading ? <LoaderCircle className="motion-safe:animate-spin" /> : icon}</span>
      <span className={`action-button-labels${compactLabel ? ' action-button-labels-prefix' : ''}`} aria-hidden="true">
        {compactLabel && <span className="action-button-prefix">{compactLabel}</span>}
        <span className="action-button-caption action-button-caption-full"><span>{reveal}{labelAdornment}</span></span>
      </span>
      {trailingIcon && <span className="action-button-trailing" aria-hidden="true">{trailingIcon}</span>}
      {children}
    </button>
  </span>;
});
