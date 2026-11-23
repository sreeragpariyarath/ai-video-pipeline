import React from 'react';
import type { Scene } from './sceneTypes';
import { motionStyle, staggerDelayFrames } from './graphics/motion';
import { SceneGraphicView } from './graphics/SceneGraphicView';
import { THEME } from './graphics/theme';
import type { CompositionPreset } from './graphics/CompositionPresets';
import { isGroupedPreset } from './graphics/CompositionPresets';

const colors = {
  panel: THEME.surface,
  accent: THEME.accent,
  muted: THEME.body,
  text: THEME.text,
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
  return motionStyle('rise', frame, fps, {
    durationFrames: Math.round(0.34 * fps),
    delayFrames: staggerDelayFrames(index, fps),
    distance: 22,
  });
};

export const SceneBlocks: React.FC<{ scene: Scene; frame: number; fps: number; preset: Exclude<CompositionPreset, 'auto'> }> = ({
  scene,
  frame,
  fps,
  preset,
}) => {
  if (scene.graphic) {
    return <SceneGraphicView graphic={scene.graphic} frame={frame} fps={fps} />;
  }
  const items = secondaryText(scene)
    .filter(({ index }) => isVisible(scene, index, frame, fps))
    .slice(0, 4);
  const isProcess = scene.scene_type === 'process' || scene.scene_type === 'timeline' || preset === 'process_walkthrough' || preset === 'timeline';
  const isTimeline = scene.scene_type === 'timeline' || preset === 'timeline';
  const isDiagram = scene.scene_type === 'diagram' || preset === 'diagram';
  const isStatistic = scene.scene_type === 'statistic' || preset === 'number_explainer';
  const isQuote = preset === 'quote_callout';
  const isCardLayout =
    scene.scene_type === 'comparison' ||
    preset === 'comparison_two' ||
    preset === 'comparison_three' ||
    scene.composition.layout === 'split' ||
    scene.composition.layout === 'grid';
  const isStackedLayout = scene.composition.layout === 'stacked';
  if (
    !items.length ||
    (!isProcess && !isDiagram && !isStatistic && !isCardLayout && !isStackedLayout && !isQuote)
  ) return null;

  if (isQuote) {
    return (
      <div
        style={{
          maxWidth: 980,
          margin: '0 auto 30px',
          padding: '28px 38px 34px',
          borderLeft: `5px solid ${colors.accent}`,
          borderRadius: '0 22px 22px 0',
          background: `linear-gradient(110deg, ${THEME.accentSoft}99, ${THEME.surface})`,
          boxShadow: `0 18px 56px ${THEME.shadow}`,
        }}
      >
        <div style={{ color: colors.accent, fontSize: 62, fontWeight: 800, lineHeight: .7, marginBottom: 18 }}>“</div>
        {items.slice(0, 2).map(({ item, index }) => (
          <div key={`${item.text}-${index}`} style={{ color: colors.text, fontSize: 30, lineHeight: 1.3, ...revealStyle(frame, index, fps) }}>
            {item.text}
          </div>
        ))}
      </div>
    );
  }

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
          background: `linear-gradient(140deg, ${THEME.accentSoft}, ${THEME.surface})`,
          boxShadow: `0 20px 70px ${THEME.shadow}`,
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
    const columnCount = preset === 'comparison_three' ? 3 : 2;
    const cards = scene.scene_type === 'comparison' || preset === 'comparison_two' || preset === 'comparison_three'
      ? items.slice(0, columnCount)
      : items;
    return (
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${Math.min(columnCount, cards.length)}, minmax(0, 1fr))`,
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
              background: index === 0 ? colors.panel : THEME.accentSoft,
              border: `1px solid ${index === 0 ? THEME.line : `${colors.accent}66`}`,
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

export const SceneDetails: React.FC<{ scene: Scene; frame: number; fps: number; preset: Exclude<CompositionPreset, 'auto'> }> = ({
  scene,
  frame,
  fps,
  preset,
}) => {
  const isGrouped =
    scene.scene_type === 'comparison' ||
    isGroupedPreset(preset) ||
    preset === 'quote_callout' ||
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
      color: THEME.subtle,
      fontSize: 18,
      letterSpacing: 3,
      textTransform: 'uppercase',
    }}
  >
    <span>{String(order).padStart(2, '0')}</span>
    <span>{type.replace('_', ' ')}</span>
  </div>
);
