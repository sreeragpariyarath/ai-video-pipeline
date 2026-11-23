import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import type { Scene } from './sceneTypes';
import { SceneBlocks, SceneChrome, SceneDetails } from './SceneElements';
import { SceneArtwork } from './SceneArtwork';
import { motionStyle } from './graphics/motion';
import { AnimatedHeading } from './graphics/VisualComponents';
import {
  CompositionArtwork,
  compositionPresetFor,
  isVisualFirstPreset,
} from './graphics/CompositionPresets';
import { BackgroundAtmosphere } from './graphics/BackgroundAtmosphere';
import { THEME } from './graphics/theme';

const ACCENT = THEME.accent;

export const SceneVisual: React.FC<{
  scene: Scene;
  durationInFrames: number;
  frameOverride?: number;
  hideChrome?: boolean;
}> = ({
  scene,
  durationInFrames,
  frameOverride,
  hideChrome = false,
}) => {
  const sequenceFrame = useCurrentFrame();
  const frame = frameOverride ?? sequenceFrame;
  const { fps, width, height } = useVideoConfig();
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
  const preset = compositionPresetFor(scene);
  const isSplitVisual = preset === 'split_visual';
  const isHeroOverlay = preset === 'hero_overlay';

  const enterProgress = interpolate(frame, [0, entranceFrames], [0, 1], {
    extrapolateRight: 'clamp',
  });
  const exitProgress = interpolate(frame, [exitStart, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp',
  });
  const entranceStyle = motionStyle(entrance, frame, fps, {
    durationFrames: entranceFrames,
    distance: 42,
  });
  const exitStyle = motionStyle(exit, durationInFrames - frame, fps, {
    durationFrames: exitFrames,
    distance: 26,
  });
  const entranceOpacity = entrance === 'fade'
    ? Number(entranceStyle.opacity ?? enterProgress)
    : scene.transition.type === 'fade'
      ? enterProgress
      : 1;
  const opacity = entranceOpacity *
    (exit === 'none' ? 1 : Number(exitStyle.opacity ?? (1 - exitProgress)));

  const transitionOffsetX = entrance === 'none' && scene.transition.type === 'slide'
    ? (1 - enterProgress) * 42
    : 0;
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
  const isFullBleed = scene.composition.layout === 'full_bleed' || isHeroOverlay;
  const isVisualFirst = scene.composition.hierarchy === 'visual_first' || isVisualFirstPreset(preset);
  const compositionAlignment = preset === 'headline' || isHeroOverlay
    ? 'center'
    : scene.composition.alignment;
  const titleSize = scene.scene_type === 'statistic'
    ? 108
    : scene.scene_type === 'title' || scene.scene_type === 'conclusion'
      ? 86
      : 68;
  const headingEntrance = entrance === 'blur_reveal' || entrance === 'pop'
    ? entrance
    : 'rise';

  return (
    <AbsoluteFill
      style={{
        background: scene.scene_type === 'statistic'
          ? `radial-gradient(circle at 76% 48%, ${THEME.accentSoft}99, transparent 38%), ${THEME.canvasWarm}`
          : ['diagram', 'process', 'timeline'].includes(scene.scene_type)
            ? THEME.canvasCool
            : `radial-gradient(circle at 80% 12%, ${THEME.blueSoft}99, transparent 40%), linear-gradient(145deg, ${THEME.canvas}, #EFEEE8 72%)`,
        color: THEME.text,
        fontFamily: 'Arial, sans-serif',
        justifyContent: 'center',
        alignItems: 'center',
        padding: isFullBleed ? '4%' : '10%',
        overflow: 'hidden',
      }}
    >
      <BackgroundAtmosphere scene={scene} frame={frame} fps={fps} />
      {!isSplitVisual ? <SceneArtwork scene={scene} /> : null}
      {isHeroOverlay ? (
        <CompositionArtwork scene={scene} preset="hero_overlay" frame={frame} fps={fps} />
      ) : null}
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
          transform: `${entranceStyle.transform ?? ''} ${exitStyle.transform ?? ''} translate(${transitionOffsetX + viewportPan}px, 0px) scale(${emphasisScale * viewportScale})`,
          filter: entranceStyle.filter,
          textAlign: compositionAlignment,
          position: 'relative',
          display: isSplitVisual ? 'grid' : 'block',
          gridTemplateColumns: isSplitVisual && width > height ? 'minmax(0, .9fr) minmax(0, 1.1fr)' : 'minmax(0, 1fr)',
          alignItems: 'center',
          gap: isSplitVisual ? 36 : undefined,
        }}
      >
        {isSplitVisual ? (
          <CompositionArtwork scene={scene} preset="split_visual" frame={frame} fps={fps} />
        ) : null}
        <div style={{ minWidth: 0, position: 'relative', zIndex: 1 }}>
          {isVisualFirst ? (
            <SceneBlocks scene={scene} frame={frame} fps={fps} preset={preset} />
          ) : null}
          <AnimatedHeading
            title={title}
            frame={frame}
            fps={fps}
            size={isHeroOverlay ? Math.round(titleSize * 1.1) : titleSize}
            alignment={compositionAlignment}
            preset={headingEntrance}
            underline={scene.motion.emphasis === 'underline'}
          />
          {scene.scene_type === 'statistic' && !scene.graphic ? (
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
            <SceneBlocks scene={scene} frame={frame} fps={fps} preset={preset} />
          ) : null}
          <SceneDetails scene={scene} frame={frame} fps={fps} preset={preset} />
        </div>
      </div>
      {!hideChrome ? <SceneChrome order={scene.order} type={`${scene.scene_type} / ${preset}`} /> : null}
    </AbsoluteFill>
  );
};
