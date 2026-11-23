import React from 'react';
import { interpolate } from 'remotion';
import type { Scene } from './sceneTypes';

const colors = {
  panel: 'rgba(22, 31, 49, 0.88)',
  accent: '#78e0c2',
  muted: '#aab4c7',
  text: '#f6f7fb',
};

const isVisible = (scene: Scene, index: number, frame: number, fps: number) => {
  const text = scene.on_screen_text[index];
  const start = Math.max(0, Math.round((text.start_seconds ?? 0) * fps));
  const end = text.duration_seconds === null
    ? Number.POSITIVE_INFINITY
    : start + Math.max(1, Math.round(text.duration_seconds * fps));
  return frame >= start && frame < end;
};

const secondaryText = (scene: Scene) => {
  const title =
    scene.on_screen_text.find((item) => item.role === 'title')?.text ??
    scene.on_screen_text[0]?.text ??
    scene.narration_text;
  return scene.on_screen_text
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.text !== title);
};

const revealStyle = (frame: number, index: number, fps: number) => {
  const start = index * Math.max(1, Math.round(0.12 * fps));
  const opacity = interpolate(frame, [start, start + Math.max(1, Math.round(0.22 * fps))], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const y = interpolate(frame, [start, start + Math.max(1, Math.round(0.22 * fps))], [18, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return { opacity, transform: `translateY(${y}px)` };
};

export const SceneBlocks: React.FC<{ scene: Scene; frame: number; fps: number }> = ({
  scene,
  frame,
  fps,
}) => {
  const items = secondaryText(scene)
    .filter(({ index }) => isVisible(scene, index, frame, fps))
    .slice(0, 4);
  const isProcess = scene.scene_type === 'process' || scene.scene_type === 'timeline';
  const isTimeline = scene.scene_type === 'timeline';
  const isDiagram = scene.scene_type === 'diagram';
  const isStatistic = scene.scene_type === 'statistic';
  const isCardLayout =
    scene.scene_type === 'comparison' ||
    scene.composition.layout === 'split' ||
    scene.composition.layout === 'grid';
  const isStackedLayout = scene.composition.layout === 'stacked';
  if (
    !items.length ||
    (!isProcess && !isDiagram && !isStatistic && !isCardLayout && !isStackedLayout)
  ) return null;

  if (isStatistic) {
    const emphasis = items.find(({ item }) => item.role === 'emphasis') ?? items[0];
    return (
      <div
        style={{
          display: 'inline-grid',
          justifyItems: 'center',
          minWidth: '42%',
          margin: '0 auto 34px',
          padding: '18px 38px 24px',
          border: `1px solid ${colors.accent}88`,
          borderRadius: 28,
          background: 'linear-gradient(140deg, rgba(120, 224, 194, .14), rgba(22, 31, 49, .9))',
          boxShadow: '0 20px 70px rgba(0,0,0,.24)',
          ...revealStyle(frame, emphasis.index, fps),
        }}
      >
        <div style={{ color: colors.accent, fontSize: 68, fontWeight: 800, lineHeight: 1.1 }}>
          {emphasis.item.text}
        </div>
      </div>
    );
  }

  if (isTimeline) {
    return (
      <div
        style={{
          position: 'relative',
          display: 'grid',
          gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))`,
          gap: 18,
          marginBottom: 42,
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: '8%',
            right: '8%',
            top: 14,
            height: 2,
            background: `linear-gradient(90deg, transparent, ${colors.accent}, transparent)`,
          }}
        />
        {items.map(({ item, index }) => (
          <div
            key={`${item.text}-${index}`}
            style={{ paddingTop: 34, textAlign: 'center', ...revealStyle(frame, index, fps) }}
          >
            <div
              style={{
                position: 'relative',
                zIndex: 1,
                width: 16,
                height: 16,
                margin: '-28px auto 20px',
                borderRadius: '50%',
                background: colors.accent,
                boxShadow: `0 0 0 8px ${colors.accent}22`,
              }}
            />
            <div style={{ color: colors.muted, fontSize: 23, lineHeight: 1.3 }}>{item.text}</div>
          </div>
        ))}
      </div>
    );
  }

  if (isDiagram) {
    return (
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${items.length > 2 ? 2 : items.length}, minmax(0, 1fr))`,
          gap: 18,
          marginBottom: 40,
        }}
      >
        {items.map(({ item, index }) => (
          <div
            key={`${item.text}-${index}`}
            style={{
              minHeight: 86,
              display: 'grid',
              placeItems: 'center',
              padding: 20,
              borderRadius: 20,
              background: colors.panel,
              border: `1px solid ${colors.accent}66`,
              color: colors.muted,
              fontSize: 24,
              textAlign: 'center',
              ...revealStyle(frame, index, fps),
            }}
          >
            {item.text}
          </div>
        ))}
      </div>
    );
  }

  if (isProcess) {
    return (
      <div style={{ display: 'flex', gap: 18, alignItems: 'center', marginBottom: 42 }}>
        {items.map(({ item }, index) => (
          <React.Fragment key={`${item.text}-${index}`}>
            <div
              style={{
                flex: 1,
                minHeight: 96,
                border: `1px solid ${colors.accent}66`,
                borderRadius: 18,
                background: colors.panel,
                display: 'grid',
                placeItems: 'center',
                padding: 18,
                fontSize: 25,
                color: colors.muted,
                ...revealStyle(frame, index, fps),
              }}
            >
              {item.text}
            </div>
            {index < items.length - 1 ? (
              <div style={{ color: colors.accent, fontSize: 30 }}>&gt;</div>
            ) : null}
          </React.Fragment>
        ))}
      </div>
    );
  }

  if (isCardLayout) {
    const cards = scene.scene_type === 'comparison' ? items.slice(0, 2) : items;
    return (
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${cards.length > 1 ? 2 : 1}, minmax(0, 1fr))`,
          gap: 18,
          marginBottom: 38,
        }}
      >
        {cards.map(({ item }, index) => (
          <div
            key={`${item.text}-${index}`}
            style={{
              minHeight: 86,
              padding: '22px 26px',
              borderRadius: 22,
              background: index === 0 ? colors.panel : 'rgba(120, 224, 194, .12)',
              border: `1px solid ${index === 0 ? '#ffffff22' : `${colors.accent}66`}`,
              color: index === 0 ? colors.muted : colors.text,
              fontSize: 27,
              textAlign: 'center',
              display: 'grid',
              placeItems: 'center',
              ...revealStyle(frame, index, fps),
            }}
          >
            {item.text}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gap: 12, marginBottom: 34 }}>
      {items.map(({ item }, index) => (
        <div
          key={`${item.text}-${index}`}
          style={{
            padding: '14px 20px',
            borderLeft: `3px solid ${colors.accent}`,
            background: colors.panel,
            color: colors.muted,
            fontSize: 25,
            textAlign: 'left',
            ...revealStyle(frame, index, fps),
          }}
        >
          {item.text}
        </div>
      ))}
    </div>
  );
};

export const SceneDetails: React.FC<{ scene: Scene; frame: number; fps: number }> = ({
  scene,
  frame,
  fps,
}) => {
  const isGrouped =
    scene.scene_type === 'process' ||
    scene.scene_type === 'timeline' ||
    scene.scene_type === 'comparison' ||
    ['split', 'grid', 'stacked'].includes(scene.composition.layout);
  if (isGrouped) return null;

  return (
    <div style={{ display: 'grid', gap: 22, marginTop: 30 }}>
      {secondaryText(scene).map(({ item, index }) => {
        if (!isVisible(scene, index, frame, fps)) return null;
        const role = item.role;
        return (
          <div
            key={`${item.text}-${index}`}
            style={{
              color: role === 'emphasis' ? colors.accent : colors.muted,
              fontSize: role === 'caption' || role === 'label' ? 25 : 34,
              fontWeight: role === 'emphasis' ? 700 : 400,
              lineHeight: 1.35,
              ...revealStyle(frame, index, fps),
            }}
          >
            {item.text}
          </div>
        );
      })}
    </div>
  );
};

export const SceneChrome: React.FC<{ order: number; type: string }> = ({ order, type }) => (
  <div
    style={{
      position: 'absolute',
      bottom: 48,
      left: '10%',
      right: '10%',
      display: 'flex',
      justifyContent: 'space-between',
      color: '#718097',
      fontSize: 18,
      letterSpacing: 3,
      textTransform: 'uppercase',
    }}
  >
    <span>{String(order).padStart(2, '0')}</span>
    <span>{type.replace('_', ' ')}</span>
  </div>
);
