import React from 'react';
import type { BackgroundLayer, Scene } from '../sceneTypes';
import { THEME } from './theme';

const COLORS: Record<BackgroundLayer['palette'], string> = {
  mint: THEME.green,
  blue: THEME.blue,
  violet: '#78678B',
  amber: THEME.accent,
  neutral: THEME.subtle,
};

const ANCHORS: Record<BackgroundLayer['anchor'], string> = {
  top_left: '18% 18%',
  top_right: '82% 18%',
  center: '50% 50%',
  bottom_left: '18% 82%',
  bottom_right: '82% 82%',
};

const hash = (value: string): number => {
  let result = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    result = Math.imul(result ^ value.charCodeAt(index), 16777619);
  }
  return result >>> 0;
};

const positions = (seed: string, count: number) => {
  let state = hash(seed) || 1;
  return Array.from({ length: count }, (_, index) => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    const x = 4 + (state % 920) / 10;
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    const y = 4 + (state % 920) / 10;
    return { x, y, phase: (state % 628) / 100, radius: 2 + ((state >>> 8) % 4), index };
  });
};

export const BackgroundAtmosphere: React.FC<{
  scene: Scene;
  frame: number;
  fps: number;
}> = ({ scene, frame, fps }) => {
  const layers = scene.atmosphere?.layers ?? [];
  if (!layers.length) return null;
  const points = positions(scene.scene_id, 18);
  const seconds = frame / Math.max(1, fps);

  return (
    <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none', isolation: 'isolate', zIndex: 0 }}>
      {layers.map((layer) => {
        const color = COLORS[layer.palette];
        const anchor = ANCHORS[layer.anchor];
        const opacity = layer.intensity;
        const drift = layer.motion === 'drift';
        const shift = drift ? Math.sin(seconds * 0.22) * 1.8 : 0;

        if (layer.kind === 'gradient_shift') {
          return (
            <div key={layer.kind} style={{ position: 'absolute', inset: '-8%', opacity, transform: `translate(${shift}%, ${-shift}%)`, background: `radial-gradient(ellipse at ${anchor}, ${color}44, transparent 58%), radial-gradient(ellipse at 72% 74%, ${THEME.blueSoft}99, transparent 54%)` }} />
          );
        }
        if (layer.kind === 'grid') {
          return (
            <div key={layer.kind} style={{ position: 'absolute', inset: 0, opacity, backgroundImage: `linear-gradient(${color} 1px, transparent 1px), linear-gradient(90deg, ${color} 1px, transparent 1px)`, backgroundSize: '72px 72px', maskImage: 'radial-gradient(ellipse at center, #000 5%, transparent 78%)' }} />
          );
        }
        if (layer.kind === 'grain') {
          return (
            <svg key={layer.kind} width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, opacity: opacity * 0.65 }}>
              <filter id={`grain-${scene.order}`}><feTurbulence type="fractalNoise" baseFrequency="0.82" numOctaves="2" stitchTiles="stitch" /></filter>
              <rect width="100%" height="100%" filter={`url(#grain-${scene.order})`} opacity="0.28" />
            </svg>
          );
        }
        if (layer.kind === 'particles') {
          return (
            <svg key={layer.kind} width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, opacity }}>
              {points.slice(0, 14).map((point) => {
                const y = (point.y + (drift ? Math.sin(seconds * 0.28 + point.phase) * 1.4 : 0) + 100) % 100;
                return <circle key={point.index} cx={point.x} cy={y} r={point.radius / 12} fill={color} opacity={0.62} />;
              })}
            </svg>
          );
        }
        if (layer.kind === 'soft_light') {
          return (
            <div key={layer.kind} style={{ position: 'absolute', inset: '-4%', opacity, background: `radial-gradient(ellipse at ${anchor}, ${color}44, transparent 48%)`, transform: `translateY(${drift ? Math.sin(seconds * 0.18) * 1.2 : 0}%)` }} />
          );
        }
        if (layer.kind === 'geometry') {
          return (
            <svg key={layer.kind} width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, opacity }}>
              <circle cx={anchor.includes('left') ? 12 : anchor.includes('right') ? 88 : 50} cy={anchor.startsWith('top') ? 16 : anchor.startsWith('bottom') ? 84 : 50} r="23" fill="none" stroke={color} strokeWidth="0.12" />
              <circle cx={anchor.includes('left') ? 12 : anchor.includes('right') ? 88 : 50} cy={anchor.startsWith('top') ? 16 : anchor.startsWith('bottom') ? 84 : 50} r="30" fill="none" stroke={color} strokeWidth="0.08" />
              <path d="M 0 82 Q 50 55 100 78" fill="none" stroke={color} strokeWidth="0.1" />
            </svg>
          );
        }
        return (
          <div key={layer.kind} style={{ position: 'absolute', inset: '-2%', opacity, background: `linear-gradient(155deg, transparent 22%, ${color}33 48%, transparent 73%)`, transform: `translate(${drift ? shift * (1 + layer.intensity * 3) : 0}%, ${drift ? -shift * 0.5 : 0}%) scale(1.04)` }} />
        );
      })}
    </div>
  );
};
