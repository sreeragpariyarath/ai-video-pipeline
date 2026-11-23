import React from 'react';
import { interpolate } from 'remotion';
import { motionStyle } from './motion';

const ACCENT = '#78e0c2';

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
        color: '#f6f7fb',
        fontWeight: 800,
        lineHeight: 1.08,
        letterSpacing: '-0.04em',
        textWrap: 'balance',
        textShadow: '0 12px 50px rgba(0,0,0,.35)',
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
      border: `1px solid ${accent ? `${ACCENT}88` : 'rgba(255,255,255,.12)'}`,
      borderRadius: 20,
      background: accent
        ? 'linear-gradient(140deg, rgba(120,224,194,.14), rgba(22,31,49,.92))'
        : 'rgba(22,31,49,.88)',
      boxShadow: '0 18px 58px rgba(0,0,0,.24)',
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
    <div style={{ color: '#aab4c7', marginTop: 9, fontSize: 20 }}>{label}</div>
    <div
      style={{
        width: '100%',
        height: 3,
        marginTop: 16,
        background: `linear-gradient(90deg, ${ACCENT} ${Math.max(0, Math.min(100, progress))}%, rgba(255,255,255,.12) 0)`,
      }}
    />
  </CalloutCard>
);
