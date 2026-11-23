import React from 'react';
import { interpolate } from 'remotion';
import { motionStyle } from './motion';
import { THEME } from './theme';

const ACCENT = THEME.accent;

export const AnimatedHeading: React.FC<{
  title: string;
  frame: number;
  fps: number;
  size: number;
  alignment: React.CSSProperties['textAlign'];
  preset?: Parameters<typeof motionStyle>[0];
  underline?: boolean;
}> = ({ title, frame, fps, size, alignment, preset = 'rise', underline = false }) => (
  <div style={{ textAlign: alignment, marginBottom: 26 }}>
    <div
      style={{
        width: underline
          ? interpolate(frame, [0, Math.max(1, Math.round(0.45 * fps))], [12, 108], { extrapolateRight: 'clamp' })
          : 76,
        height: 7,
        borderRadius: 20,
        background: ACCENT,
        margin: alignment === 'center' ? '0 auto 22px' : '0 0 22px',
        ...motionStyle(preset, frame, fps, { durationFrames: Math.round(0.45 * fps) }),
      }}
    />
    <div
      style={{
        fontSize: size,
        color: THEME.text,
        fontWeight: 800,
        lineHeight: 1.08,
        letterSpacing: '-0.04em',
        textWrap: 'balance',
        textShadow: '0 2px 18px rgba(42,45,39,.08)',
        ...motionStyle(preset, frame, fps, { durationFrames: Math.round(0.5 * fps), delayFrames: 3 }),
      }}
    >
      {title}
    </div>
  </div>
);

export const CalloutCard: React.FC<{
  children: React.ReactNode;
  frame: number;
  fps: number;
  delayFrames?: number;
  accent?: boolean;
}> = ({ children, frame, fps, delayFrames = 0, accent = false }) => (
  <div
    style={{
      display: 'grid',
      placeItems: 'center',
      minHeight: 76,
      padding: '18px 24px',
      border: `1px solid ${accent ? `${THEME.accent}55` : THEME.line}`,
      borderRadius: 20,
      background: accent
        ? `linear-gradient(140deg, ${THEME.accentSoft}, ${THEME.surface})`
        : THEME.surface,
      boxShadow: `0 18px 58px ${THEME.shadow}`,
      ...motionStyle('rise', frame, fps, { delayFrames, distance: 18 }),
    }}
  >
    {children}
  </div>
);

export const MetricCallout: React.FC<{
  value: string;
  label: string;
  frame: number;
  fps: number;
  progress?: number;
}> = ({ value, label, frame, fps, progress = 1 }) => (
  <CalloutCard frame={frame} fps={fps} accent>
    <div style={{ color: ACCENT, fontSize: 68, fontWeight: 800, lineHeight: 1.05 }}>
      {value}
    </div>
    <div style={{ color: THEME.muted, marginTop: 9, fontSize: 20 }}>{label}</div>
    <div
      style={{
        width: '100%',
        height: 3,
        marginTop: 16,
        background: `linear-gradient(90deg, ${THEME.accentBright} ${Math.max(0, Math.min(100, progress))}%, ${THEME.line} 0)`,
      }}
    />
  </CalloutCard>
);
