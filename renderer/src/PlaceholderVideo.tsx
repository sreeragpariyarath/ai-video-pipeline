import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';


export const PlaceholderVideo: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 15, 1020, 1050], [0, 1, 1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const y = interpolate(frame, [0, 25], [40, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <AbsoluteFill style={{ backgroundColor: '#0b0d12', color: '#f4f5f7', justifyContent: 'center', alignItems: 'center', fontFamily: 'Arial, sans-serif' }}>
      <div style={{ opacity, transform: `translateY(${y}px)`, width: '82%', textAlign: 'center' }}>
        <div style={{ color: '#8b93a5', fontSize: 30, letterSpacing: 8, marginBottom: 28 }}>AI VIDEO FACTORY · MVP</div>
        <div style={{ fontWeight: 800, fontSize: 82, lineHeight: 1.08 }}>YOUR EXPLAINER<br/>STARTS HERE</div>
        <div style={{ marginTop: 44, fontSize: 34, color: '#b4bac7' }}>Topic → Story → Motion</div>
      </div>
    </AbsoluteFill>
  );
};
