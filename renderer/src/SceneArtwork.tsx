import React from 'react';
import type { Scene } from './sceneTypes';
import { THEME } from './graphics/theme';

const hashId = (value: string): number =>
  [...value].reduce((hash, char) => (hash * 31 + char.charCodeAt(0)) >>> 0, 7);

export const SceneArtwork: React.FC<{ scene: Scene }> = ({ scene }) => {
  if (!['illustration', 'diagram', 'statistic'].includes(scene.scene_type)) return null;

  const seed = hashId(scene.scene_id);
  const x = 130 + (seed % 180);
  const y = 170 + ((seed >>> 5) % 180);
  const accent = seed % 2 ? THEME.blue : THEME.accentBright;

  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 480 560"
      preserveAspectRatio="xMidYMid meet"
      style={{
        position: 'absolute',
        width: 'min(48vw, 620px)',
        height: 'min(56vh, 820px)',
        right: '5%',
        top: '18%',
        opacity: scene.scene_type === 'statistic' ? 0.26 : 0.46,
        pointerEvents: 'none',
        overflow: 'visible',
      }}
    >
      <defs>
        <linearGradient id={`art-${scene.order}`} x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor={accent} stopOpacity=".9" />
          <stop offset="1" stopColor={THEME.blue} stopOpacity=".12" />
        </linearGradient>
      </defs>
      {scene.scene_type === 'statistic' ? (
        <>
          <circle cx="240" cy="280" r="175" fill="none" stroke={accent} strokeOpacity=".45" strokeWidth="2" />
          <circle cx="240" cy="280" r="142" fill="none" stroke={accent} strokeOpacity=".26" strokeWidth="18" />
          <circle cx="240" cy="280" r="8" fill={accent} />
          <path d="M240 105 A175 175 0 0 1 391 192" fill="none" stroke={accent} strokeWidth="8" strokeLinecap="round" />
        </>
      ) : scene.scene_type === 'diagram' ? (
        <>
          <path d="M105 160 L240 275 L375 160 M240 275 L240 430" fill="none" stroke={accent} strokeOpacity=".58" strokeWidth="4" />
          {[ [105, 160], [375, 160], [240, 275], [240, 430] ].map(([cx, cy], index) => (
            <g key={index}>
              <circle cx={cx} cy={cy} r="45" fill={`url(#art-${scene.order})`} />
              <circle cx={cx} cy={cy} r="51" fill="none" stroke={accent} strokeOpacity=".3" strokeWidth="2" />
            </g>
          ))}
        </>
      ) : (
        <>
          <circle cx={x} cy={y} r="150" fill={`url(#art-${scene.order})`} />
          <circle cx={x} cy={y} r="195" fill="none" stroke={accent} strokeOpacity=".3" strokeWidth="2" />
          <rect
            x={260 - (seed % 48)}
            y={245 + (seed % 32)}
            width="142"
            height="142"
            rx="32"
            fill={THEME.surface}
            fillOpacity=".8"
            stroke={accent}
            strokeOpacity=".65"
            strokeWidth="3"
            transform={`rotate(${(seed % 32) - 16} 330 320)`}
          />
          <path d="M75 465 C180 390 270 520 405 415" fill="none" stroke={accent} strokeOpacity=".6" strokeWidth="5" />
          <circle cx="82" cy="104" r="12" fill={accent} />
          <circle cx="404" cy="484" r="8" fill={accent} />
        </>
      )}
    </svg>
  );
};
