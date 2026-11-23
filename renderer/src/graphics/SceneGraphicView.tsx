import React from 'react';
import { interpolate } from 'remotion';
import type { SceneGraphic } from '../sceneTypes';
import { motionStyle, staggerDelayFrames } from './motion';
import { CalloutCard, MetricCallout } from './VisualComponents';
import { CHART_COLORS, THEME } from './theme';

const ACCENT = THEME.accent;
const MUTED = THEME.muted;

const numberFor = (text: string): number => {
  const match = text.match(/^[\$\u20ac\u00a3]?(-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?)\s*([KMBT%]?)$/i);
  if (!match) return Number.NaN;
  const multiplier = { K: 1e3, M: 1e6, B: 1e9, T: 1e12 }[
    match[2].toUpperCase() as 'K' | 'M' | 'B' | 'T'
  ] ?? 1;
  return Number(match[1].replace(/,/g, '')) * multiplier;
};

const displayCounter = (text: string, progress: number): string => {
  const match = text.match(/^([\$\u20ac\u00a3]?)(-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?)(\s*[KMBT%]?)$/i);
  if (!match) return text;
  const suffix = match[3].trim();
  const scale = { K: 1e3, M: 1e6, B: 1e9, T: 1e12 }[suffix.toUpperCase() as 'K' | 'M' | 'B' | 'T'] ?? 1;
  const end = numberFor(text) / scale;
  const decimals = (match[2].replace(/,/g, '').split('.')[1] ?? '').length;
  const current = (end * progress).toFixed(decimals);
  return `${match[1]}${current}${match[3]}`;
};

const AnimatedChart: React.FC<{ graphic: SceneGraphic; frame: number; fps: number }> = ({
  graphic,
  frame,
  fps,
}) => {
  const progress = interpolate(frame, [0, Math.max(1, Math.round(0.8 * fps))], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const values = graphic.data.map((point) => numberFor(point.value_text));
  const scale = Math.max(1, ...values.map((value) => Math.abs(value)));

  if (graphic.kind === 'percentage_ring') {
    const value = Math.max(0, Math.min(100, values[0]));
    const radius = 116;
    const circumference = 2 * Math.PI * radius;
    const visible = (value / 100) * progress;
    return (
      <svg width="100%" viewBox="0 0 500 330" role="img" aria-label={`${graphic.title}: ${graphic.data[0].value_text}`}>
        <circle cx="250" cy="148" r={radius} fill="none" stroke={THEME.line} strokeWidth="26" />
        <circle
          cx="250" cy="148" r={radius} fill="none" stroke={ACCENT} strokeWidth="26"
          strokeDasharray={circumference} strokeDashoffset={circumference * (1 - visible)}
          strokeLinecap="round" transform="rotate(-90 250 148)"
        />
        <text x="250" y="164" textAnchor="middle" fill={THEME.text} fontSize="62" fontWeight="800">
          {graphic.data[0].value_text}
        </text>
        <text x="250" y="310" textAnchor="middle" fill={MUTED} fontSize="23">{graphic.data[0].label}</text>
      </svg>
    );
  }

  if (graphic.kind === 'progress_bar') {
    const value = Math.max(0, Math.min(100, values[0]));
    return (
      <div style={{ padding: '34px 22px', display: 'grid', gap: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', color: MUTED, fontSize: 23 }}>
          <span>{graphic.data[0].label}</span><strong style={{ color: THEME.text }}>{graphic.data[0].value_text}</strong>
        </div>
        <div style={{ height: 22, borderRadius: 20, background: THEME.line, overflow: 'hidden' }}>
          <div style={{ width: `${value * progress}%`, height: '100%', borderRadius: 20, background: `linear-gradient(90deg, ${THEME.blue}, ${ACCENT})` }} />
        </div>
      </div>
    );
  }

  if (graphic.kind === 'number_counter') {
    const shown = displayCounter(graphic.data[0].value_text, progress);
    return (
      <MetricCallout
        value={shown}
        label={graphic.data[0].label}
        frame={frame}
        fps={fps}
        progress={progress * 100}
      />
    );
  }

  const chartTop = 38;
  const chartBottom = 278;
  const chartHeight = chartBottom - chartTop;
  const slotWidth = 760 / graphic.data.length;
  const points = values.map((value, index) => ({
    x: 80 + slotWidth * index + slotWidth / 2,
    y: chartBottom - (value / scale) * chartHeight,
    label: graphic.data[index].label,
    valueText: graphic.data[index].value_text,
  }));
  const linePath = points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${chartBottom - (chartBottom - point.y) * progress}`).join(' ');

  return (
    <svg width="100%" viewBox="0 0 900 360" role="img" aria-label={graphic.title}>
      <line x1="70" y1={chartBottom} x2="850" y2={chartBottom} stroke={THEME.line} strokeWidth="2" />
      {[0.25, 0.5, 0.75, 1].map((step) => (
        <line key={step} x1="70" y1={chartBottom - chartHeight * step} x2="850" y2={chartBottom - chartHeight * step} stroke={THEME.grid} strokeWidth="1" />
      ))}
      {graphic.kind === 'line_graph' ? (
        <>
          <path d={linePath} fill="none" stroke={ACCENT} strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" />
          {points.map((point, index) => (
            <g key={`${point.label}-${index}`} style={motionStyle('pop', frame, fps, { delayFrames: staggerDelayFrames(index, fps) })}>
              <circle cx={point.x} cy={chartBottom - (chartBottom - point.y) * progress} r="11" fill={ACCENT} />
              <text x={point.x} y={chartBottom + 36} textAnchor="middle" fill={MUTED} fontSize="19">{point.label}</text>
              <text x={point.x} y={chartBottom - (chartBottom - point.y) * progress - 18} textAnchor="middle" fill={THEME.text} fontSize="20" fontWeight="700">{point.valueText}</text>
            </g>
          ))}
        </>
      ) : points.map((point, index) => {
        const barWidth = Math.min(84, slotWidth * 0.52);
        const barHeight = (chartBottom - point.y) * progress;
        return (
          <g key={`${point.label}-${index}`} style={motionStyle('rise', frame, fps, { delayFrames: staggerDelayFrames(index, fps) })}>
            <rect x={point.x - barWidth / 2} y={chartBottom - barHeight} width={barWidth} height={barHeight} rx="12" fill={CHART_COLORS[index % CHART_COLORS.length]} />
            <text x={point.x} y={chartBottom + 36} textAnchor="middle" fill={MUTED} fontSize="19">{point.label}</text>
            <text x={point.x} y={chartBottom - barHeight - 14} textAnchor="middle" fill={THEME.text} fontSize="19" fontWeight="700">{point.valueText}</text>
          </g>
        );
      })}
    </svg>
  );
};

export const SceneGraphicView: React.FC<{ graphic: SceneGraphic; frame: number; fps: number }> = ({
  graphic,
  frame,
  fps,
}) => graphic.kind === 'number_counter' ? (
  <div style={{ display: 'grid', gap: 12, maxWidth: 760, margin: '0 auto' }}>
    <AnimatedChart graphic={graphic} frame={frame} fps={fps} />
  </div>
) : (
  <CalloutCard frame={frame} fps={fps} accent>
    <div style={{ width: '100%', color: THEME.text, textAlign: 'center', fontSize: 25, fontWeight: 700, marginBottom: 12 }}>
      {graphic.title}
    </div>
    <AnimatedChart graphic={graphic} frame={frame} fps={fps} />
  </CalloutCard>
);
