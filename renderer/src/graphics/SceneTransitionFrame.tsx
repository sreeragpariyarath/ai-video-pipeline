import React from 'react';
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Scene } from '../sceneTypes';
import { SceneVisual } from '../SceneVisual';

const revealStyle = (scene: Scene, progress: number): React.CSSProperties => {
  const { type, direction = 'left', shape = 'circle' } = scene.transition;
  const remaining = `${(1 - progress) * 100}%`;
  if (type === 'fade') return { opacity: progress };
  if (type === 'slide' || type === 'push') {
    const distance = type === 'push' ? 62 : 100;
    const offset = (1 - progress) * distance;
    const x = direction === 'left' ? offset : direction === 'right' ? -offset : 0;
    const y = direction === 'up' ? offset : direction === 'down' ? -offset : 0;
    const scale = type === 'push' ? 1.08 - progress * 0.08 : 1;
    return { transform: `translate(${x}%, ${y}%) scale(${scale})` };
  }
  if (type === 'zoom') {
    return { opacity: progress, transform: `scale(${0.82 + progress * 0.18})` };
  }
  if (type === 'wipe') {
    const clipPath = direction === 'left'
      ? `inset(0 ${remaining} 0 0)`
      : direction === 'right'
        ? `inset(0 0 0 ${remaining})`
        : direction === 'up'
          ? `inset(0 0 ${remaining} 0)`
          : `inset(${remaining} 0 0 0)`;
    return { clipPath };
  }
  if ((type === 'shape_reveal' || type === 'mask') && shape === 'diamond') {
    const top = 50 - progress * 100;
    const side = 50 + progress * 100;
    return { clipPath: `polygon(50% ${top}%, ${side}% 50%, 50% ${side}%, ${top}% 50%)` };
  }
  const radius = `${progress * 155}%`;
  const clipPath = shape === 'ellipse'
    ? `ellipse(${radius} ${radius} at 50% 50%)`
    : `circle(${radius} at 50% 50%)`;
  return { clipPath };
};

export const SceneTransitionFrame: React.FC<{
  scene: Scene;
  previousScene?: Scene;
  durationInFrames: number;
  previousDurationInFrames?: number;
}> = ({ scene, previousScene, durationInFrames, previousDurationInFrames = 1 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const transitionFrames = Math.min(
    durationInFrames,
    Math.max(1, Math.round(scene.transition.duration_seconds * fps)),
  );
  const progress = interpolate(frame, [0, Math.max(1, transitionFrames - 1)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const active = scene.transition.type !== 'cut' && scene.transition.duration_seconds > 0;
  const previousHoldFrame = Math.max(
    0,
    previousDurationInFrames - Math.min(previousDurationInFrames, Math.round(0.35 * fps)) - 1,
  );

  if (!active) return <SceneVisual scene={scene} durationInFrames={durationInFrames} />;
  return (
    <AbsoluteFill>
      {previousScene ? (
        <Sequence from={0} durationInFrames={transitionFrames} layout="none">
          <SceneVisual
            scene={previousScene}
            durationInFrames={previousDurationInFrames}
            frameOverride={previousHoldFrame}
            hideChrome
          />
        </Sequence>
      ) : null}
      <div style={{ position: 'absolute', inset: 0, zIndex: 1, ...revealStyle(scene, progress) }}>
        <SceneVisual scene={scene} durationInFrames={durationInFrames} />
      </div>
    </AbsoluteFill>
  );
};
