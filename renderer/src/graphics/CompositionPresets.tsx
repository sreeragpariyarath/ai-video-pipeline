import React from 'react';
import type { Scene } from '../sceneTypes';
import { motionStyle } from './motion';
import { THEME } from './theme';

export type CompositionPreset = NonNullable<Scene['composition']['preset']>;

const DEFAULT_BY_SCENE: Record<Scene['scene_type'], Exclude<CompositionPreset, 'auto'>> = {
  title: 'headline',
  text_focus: 'quote_callout',
  statistic: 'number_explainer',
  comparison: 'comparison_two',
  process: 'process_walkthrough',
  diagram: 'diagram',
  timeline: 'timeline',
  illustration: 'split_visual',
  conclusion: 'hero_overlay',
};

export const compositionPresetFor = (scene: Scene): Exclude<CompositionPreset, 'auto'> => {
  const preset = scene.composition.preset;
  return !preset || preset === 'auto' ? DEFAULT_BY_SCENE[scene.scene_type] : preset;
};

export const isVisualFirstPreset = (preset: Exclude<CompositionPreset, 'auto'>): boolean =>
  [
    'comparison_two', 'comparison_three', 'timeline', 'process_walkthrough', 'diagram',
  ].includes(preset);

export const isGroupedPreset = (preset: Exclude<CompositionPreset, 'auto'>): boolean =>
  [
    'comparison_two', 'comparison_three', 'timeline', 'process_walkthrough', 'diagram',
  ].includes(preset);

export const CompositionArtwork: React.FC<{
  scene: Scene;
  preset: 'split_visual' | 'hero_overlay';
  frame: number;
  fps: number;
}> = ({ scene, preset, frame, fps }) => {
  const split = preset === 'split_visual';
  const gradientId = `composition-art-${scene.order}`;
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 720 600"
      preserveAspectRatio="xMidYMid meet"
      style={{
        width: split ? '100%' : '62%',
        height: 'auto',
        aspectRatio: '6 / 5',
        position: split ? 'relative' : 'absolute',
        left: split ? undefined : '40%',
        right: split ? undefined : '-6%',
        top: split ? undefined : '11%',
        opacity: split ? 1 : 0.14,
        pointerEvents: 'none',
        ...motionStyle('rise', frame, fps, { durationFrames: Math.round(0.7 * fps), distance: 24 }),
      }}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={THEME.accentBright} stopOpacity=".9" />
          <stop offset="1" stopColor={THEME.blue} stopOpacity=".18" />
        </linearGradient>
      </defs>
      <circle cx="360" cy="292" r="218" fill={`url(#${gradientId})`} opacity=".34" />
      <circle cx="360" cy="292" r="250" fill="none" stroke={THEME.accent} strokeOpacity=".32" strokeWidth="3" />
      <path d="M134 356 C230 152 404 455 584 178" fill="none" stroke={THEME.accent} strokeOpacity=".8" strokeWidth="8" strokeLinecap="round" />
      <rect x="222" y="198" width="276" height="188" rx="34" fill={THEME.surface} fillOpacity=".94" stroke={THEME.accent} strokeOpacity=".58" strokeWidth="3" />
      <rect x="254" y="235" width="70" height="116" rx="13" fill={THEME.accentBright} fillOpacity=".72" />
      <rect x="350" y="276" width="52" height="75" rx="13" fill={THEME.blue} fillOpacity=".68" />
      <rect x="428" y="218" width="40" height="133" rx="13" fill={THEME.green} fillOpacity=".78" />
      <circle cx="143" cy="145" r="12" fill={THEME.accent} />
      <circle cx="590" cy="438" r="9" fill={THEME.blue} />
    </svg>
  );
};
