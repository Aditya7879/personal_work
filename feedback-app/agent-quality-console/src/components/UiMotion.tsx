import React, { forwardRef } from 'react';
import { motion, useIsPresent, useReducedMotion, type HTMLMotionProps } from 'motion/react';
import { surfaceMotion, uiEase, type SurfaceMotion } from '../utils/uiMotion';

/** An exiting surface remains visible briefly, but can no longer receive input. */
export const AnimatedDiv = forwardRef<HTMLDivElement, HTMLMotionProps<'div'> & { surface?: SurfaceMotion }>(function AnimatedDiv({ surface = 'popover', ...props }, ref) {
  const reduced = useReducedMotion();
  const present = useIsPresent();
  return <motion.div {...surfaceMotion(surface, Boolean(reduced))} {...props} ref={ref} data-motion-surface={surface} inert={!present || props.inert} aria-hidden={!present || props['aria-hidden']} style={{ ...props.style, pointerEvents: present ? props.style?.pointerEvents : 'none' }} />;
});

export const AnimatedSection = forwardRef<HTMLElement, HTMLMotionProps<'section'> & { surface?: SurfaceMotion }>(function AnimatedSection({ surface = 'dialog', ...props }, ref) {
  const reduced = useReducedMotion();
  const present = useIsPresent();
  return <motion.section {...surfaceMotion(surface, Boolean(reduced))} {...props} ref={ref} data-motion-surface={surface} inert={!present || props.inert} aria-hidden={!present || props['aria-hidden']} style={{ ...props.style, pointerEvents: present ? props.style?.pointerEvents : 'none' }} />;
});

/** Animate both directions without unmounting drafts, selections or scrollable answers. */
export function AnimatedCollapse({ open, children, ...props }: Omit<HTMLMotionProps<'div'>, 'children'> & { open: boolean; children: React.ReactNode }) {
  const reduced = useReducedMotion();
  return <motion.div {...props} data-motion-collapse data-open={open} initial={false}
    animate={{ height: open ? 'auto' : 0, opacity: open ? 1 : 0, overflow: 'hidden', visibility: 'visible', transitionEnd: { overflow: open ? 'visible' : 'hidden', visibility: open ? 'visible' : 'hidden' } }}
    transition={{ type: 'tween', duration: reduced ? 0 : open ? 0.20 : 0.16, ease: uiEase }}
    aria-hidden={!open} inert={!open}>
    {children}
  </motion.div>;
}
