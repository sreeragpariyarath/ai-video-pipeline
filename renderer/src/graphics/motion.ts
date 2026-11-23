import { interpolate, spring } from 'remotion';
import type { CSSProperties } from 'react';

export type MotionPreset =
  | 'none'
  | 'fade'
  | 'rise'
  | 'slide_left'
  | 'slide_right'
  | 'slide_up'
  | 'slide_down'
  | 'scale_in'
  | 'scale'
  | 'pop'
  | 'blur_reveal';

/** Frame-derived animation styles shared by scene compositions and graphic primitives. */
export const motionStyle = (
  preset: MotionPreset,
  frame: number,
  fps: number,
  options: { durationFrames?: number; delayFrames?: number; distance?: number } = {},
): CSSProperties => {
  const duration = Math.max(1, options.durationFrames ?? Math.round(0.42 * fps));
  const localFrame = Math.max(0, frame - (options.delayFrames ?? 0));
  const progress = interpolate(localFrame, [0, duration], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const distance = options.distance ?? 30;
  const opacity = preset === 'none' ? 1 : progress;
  const rise = preset === 'rise' || preset === 'slide_up';
  const slideDown = preset === 'slide_down';
  const slideLeft = preset === 'slide_left';
  const slideRight = preset === 'slide_right';
  const translation = rise
    ? `translateY(${(1 - progress) * distance}px)`
    : slideDown
      ? `translateY(${(progress - 1) * distance}px)`
      : slideLeft
        ? `translateX(${(progress - 1) * distance}px)`
        : slideRight
          ? `translateX(${(1 - progress) * distance}px)`
          : '';
  const scale = preset === 'scale' || preset === 'scale_in'
    ? 0.88 + progress * 0.12
    : preset === 'pop'
      ? 0.72 + spring({ frame: localFrame, fps, config: { damping: 12, stiffness: 180, mass: 0.65 } }) * 0.28
      : 1;
  return {
    opacity,
    transform: `${translation} scale(${scale})`.trim(),
    filter: preset === 'blur_reveal' ? `blur(${(1 - progress) * 12}px)` : undefined,
  };
};

export const staggerDelayFrames = (index: number, fps: number, stepSeconds = 0.09): number =>
  Math.max(0, index) * Math.max(1, Math.round(fps * stepSeconds));
