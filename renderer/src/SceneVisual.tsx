import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Scene } from './sceneTypes';
import { SceneBlocks, SceneChrome, SceneDetails } from './SceneElements';
import { SceneArtwork } from './SceneArtwork';

const ACCENT = '#78e0c2';

export const SceneVisual: React.FC<{ scene: Scene; durationInFrames: number }> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const entranceFrames = Math.max(
    1,
    Math.min(
      Math.max(1, durationInFrames - 1),
      Math.round((scene.transition.duration_seconds || 0.35) * fps),
      Math.round(0.65 * fps),
    ),
  );
  const exitFrames = Math.max(1, Math.min(Math.round(0.35 * fps), durationInFrames));
  const exitStart = Math.max(0, durationInFrames - exitFrames);
  const entrance = scene.motion.entrance;
  const exit = scene.motion.exit;

  const enterProgress = interpolate(frame, [0, entranceFrames], [0, 1], {
    extrapolateRight: 'clamp',
  });
  const exitProgress = interpolate(frame, [exitStart, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp',
  });
  const enterOffset = (1 - enterProgress) * 42;
  const exitOffset = exitProgress * 26;
  const opacity = entrance === 'fade' || scene.transition.type === 'fade'
    ? enterProgress * (exit === 'fade' ? 1 - exitProgress : 1)
    : 1 - (exit === 'fade' ? exitProgress : 0);

  const enterX = entrance === 'slide_left'
    ? enterOffset
    : entrance === 'slide_right'
      ? -enterOffset
      : scene.transition.type === 'slide'
        ? enterOffset
        : 0;
  const enterY = entrance === 'slide_up'
    ? enterOffset
    : entrance === 'slide_down'
      ? -enterOffset
      : 0;
  const exitX = exit === 'slide_left'
    ? -exitOffset
    : exit === 'slide_right'
      ? exitOffset
      : 0;
  const exitY = exit === 'slide_up'
    ? -exitOffset
    : exit === 'slide_down'
      ? exitOffset
      : 0;

  const entranceScale = entrance === 'scale' ? 0.94 + enterProgress * 0.06 : 1;
  const exitScale = exit === 'scale' ? 1 - exitProgress * 0.06 : 1;
  const emphasisScale = ['pulse', 'scale'].includes(scene.motion.emphasis)
    ? 1 + Math.max(0, Math.sin((frame / fps) * Math.PI * 2)) * 0.015
    : 1;
  const viewportScale = scene.composition.viewport === 'push_in'
    ? 1 + (frame / Math.max(1, durationInFrames)) * 0.035
    : scene.composition.viewport === 'pull_out'
      ? 1.035 - (frame / Math.max(1, durationInFrames)) * 0.035
      : 1;
  const viewportPan = scene.composition.viewport === 'pan_left'
    ? 14 - (frame / Math.max(1, durationInFrames)) * 28
    : scene.composition.viewport === 'pan_right'
      ? -14 + (frame / Math.max(1, durationInFrames)) * 28
      : 0;

  const title =
    scene.on_screen_text.find((item) => item.role === 'title')?.text ??
    scene.on_screen_text[0]?.text ??
    scene.narration_text;
  const isFullBleed = scene.composition.layout === 'full_bleed';
  const isVisualFirst = scene.composition.hierarchy === 'visual_first';
  const titleSize = scene.scene_type === 'statistic'
    ? 108
    : scene.scene_type === 'title' || scene.scene_type === 'conclusion'
      ? 86
      : 68;
  const underlineWidth = scene.motion.emphasis === 'underline'
    ? interpolate(frame, [0, entranceFrames], [12, 108], { extrapolateRight: 'clamp' })
    : 76;

  return (
    <AbsoluteFill
      style={{
        background: scene.scene_type === 'statistic'
          ? 'radial-gradient(circle at 76% 48%, rgba(120, 224, 194, .16), transparent 36%), #09111d'
          : ['diagram', 'process', 'timeline'].includes(scene.scene_type)
            ? '#0b101b'
            : 'radial-gradient(circle at 80% 12%, rgba(88, 135, 174, .22), transparent 38%), linear-gradient(145deg, #111a2a, #080c14 68%)',
        color: '#f6f7fb',
        fontFamily: 'Arial, sans-serif',
        justifyContent: 'center',
        alignItems: 'center',
        padding: isFullBleed ? '4%' : '10%',
        overflow: 'hidden',
      }}
    >
      <SceneArtwork scene={scene} />
      <div
        style={{
          position: 'absolute',
          width: '62%',
          height: 1,
          top: '19%',
          right: '-8%',
          background: `linear-gradient(90deg, transparent, ${ACCENT}, transparent)`,
          opacity: 0.38,
          transform: `rotate(-24deg) translateX(${viewportPan}px)`,
        }}
      />
      <div
        style={{
          width: '100%',
          maxWidth: isFullBleed ? 'none' : '1450px',
          opacity,
          transform: `translate(${enterX + exitX + viewportPan}px, ${enterY + exitY}px) scale(${entranceScale * exitScale * emphasisScale * viewportScale})`,
          textAlign: scene.composition.alignment,
        }}
      >
        {isVisualFirst ? (
          <SceneBlocks scene={scene} frame={frame} fps={fps} />
        ) : null}
        <div
          style={{
            width: underlineWidth,
            height: 7,
            borderRadius: 20,
            background: ACCENT,
            margin: scene.composition.alignment === 'center' ? '0 auto 30px' : '0 0 30px',
          }}
        />
        <div
          style={{
            maxWidth: '100%',
            marginLeft: scene.composition.alignment === 'center' ? 'auto' : 0,
            marginRight: scene.composition.alignment === 'center' ? 'auto' : 0,
            fontSize: titleSize,
            color: scene.scene_type === 'statistic' ? ACCENT : '#f6f7fb',
            fontWeight: 800,
            lineHeight: 1.08,
            letterSpacing: '-0.04em',
            textWrap: 'balance',
            textShadow: '0 12px 50px rgba(0,0,0,.35)',
          }}
        >
          {title}
        </div>
        {scene.scene_type === 'statistic' ? (
          <div
            style={{
              width: 'min(74%, 650px)',
              height: 3,
              margin: '30px auto 0',
              background: `linear-gradient(90deg, transparent, ${ACCENT}, transparent)`,
            }}
          />
        ) : null}
        {!isVisualFirst ? (
          <SceneBlocks scene={scene} frame={frame} fps={fps} />
        ) : null}
        <SceneDetails scene={scene} frame={frame} fps={fps} />
      </div>
      <SceneChrome order={scene.order} type={scene.scene_type} />
    </AbsoluteFill>
  );
};
