import React from 'react';
import { AbsoluteFill, Sequence, useVideoConfig } from 'remotion';
import { SceneTransitionFrame } from './graphics/SceneTransitionFrame';
import { assertScenePlan, framesForPlan, type VideoProps } from './sceneTypes';
import { THEME } from './graphics/theme';

export const ScenePlanVideo: React.FC<VideoProps> = ({ plan }) => {
  assertScenePlan(plan);
  const { fps } = useVideoConfig();
  const sceneFrames = framesForPlan(plan, fps);
  let from = 0;

  return (
    <AbsoluteFill style={{ backgroundColor: THEME.canvas }}>
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
            <SceneTransitionFrame
              scene={scene}
              previousScene={index > 0 ? plan.scenes[index - 1] : undefined}
              durationInFrames={durationInFrames}
              previousDurationInFrames={index > 0 ? sceneFrames[index - 1] : undefined}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
