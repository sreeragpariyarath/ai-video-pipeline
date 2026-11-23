import React from 'react';
import { AbsoluteFill, Sequence, useVideoConfig } from 'remotion';
import { SceneVisual } from './SceneVisual';
import { assertScenePlan, framesForPlan, type VideoProps } from './sceneTypes';

export const ScenePlanVideo: React.FC<VideoProps> = ({ plan }) => {
  assertScenePlan(plan);
  const { fps } = useVideoConfig();
  const sceneFrames = framesForPlan(plan, fps);
  let from = 0;

  return (
    <AbsoluteFill style={{ backgroundColor: '#0b101b' }}>
      {plan.scenes.map((scene, index) => {
        const durationInFrames = sceneFrames[index];
        const start = from;
        from += durationInFrames;
        return (
          <Sequence
            key={scene.scene_id}
            name={`${String(scene.order).padStart(2, '0')} - ${scene.scene_type}`}
            from={start}
            durationInFrames={durationInFrames}
          >
            <SceneVisual scene={scene} durationInFrames={durationInFrames} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
