import type { MotionProps } from 'motion/react';

export type SurfaceMotion = 'backdrop' | 'dialog' | 'drawer' | 'popover' | 'notice' | 'editor';

/** Short, non-bouncy motion: entering explains placement; exiting gets out of the way. */
export const uiEase = [0.22, 1, 0.36, 1] as const;

const surfaces = {
  backdrop: { from: { opacity: 0 }, to: { opacity: 1 }, out: { opacity: 0 }, enter: 0.14, leave: 0.12 },
  dialog: { from: { opacity: 0, y: 10, scale: 0.985 }, to: { opacity: 1, y: 0, scale: 1 }, out: { opacity: 0, y: 6, scale: 0.99 }, enter: 0.18, leave: 0.14 },
  drawer: { from: { opacity: 0, x: 32 }, to: { opacity: 1, x: 0 }, out: { opacity: 0, x: 24 }, enter: 0.22, leave: 0.16 },
  popover: { from: { opacity: 0, y: -4, scale: 0.99 }, to: { opacity: 1, y: 0, scale: 1 }, out: { opacity: 0, y: -2, scale: 0.99 }, enter: 0.14, leave: 0.10 },
  notice: { from: { opacity: 0, y: -6 }, to: { opacity: 1, y: 0 }, out: { opacity: 0, y: -4 }, enter: 0.18, leave: 0.12 },
  // Editors contain fixed confirmation dialogs: never transform their containing block.
  editor: { from: { opacity: 0 }, to: { opacity: 1 }, out: { opacity: 0 }, enter: 0.16, leave: 0.12 },
} satisfies Record<SurfaceMotion, unknown>;

export function surfaceMotion(kind: SurfaceMotion, reducedMotion: boolean): MotionProps {
  const surface = surfaces[kind];
  return {
    initial: reducedMotion ? false : 'closed',
    animate: 'open',
    exit: 'closing',
    variants: {
      closed: surface.from,
      open: { ...surface.to, transition: { type: 'tween', duration: reducedMotion ? 0 : surface.enter, ease: uiEase } },
      closing: { ...(reducedMotion ? { ...surface.to, opacity: 0 } : surface.out), transition: { type: 'tween', duration: reducedMotion ? 0 : surface.leave, ease: uiEase } },
    },
  };
}
