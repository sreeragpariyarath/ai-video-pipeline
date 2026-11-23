import React from 'react';
import { Composition } from 'remotion';
import { ScenePlanVideo } from './ScenePlanVideo';
import {
  assertScenePlan,
  framesForPlan,
  type ScenePlan,
  type VideoProps,
  videoProfileForFormat,
} from './sceneTypes';

const samplePlan: ScenePlan = {
  scene_plan_id: 'preview-plan',
  script_id: 'preview-script',
  research_id: 'preview-research',
  format: 'short',
  target_seconds: 6,
  planned_seconds: 6,
  created_at: '2026-11-23T00:00:00Z',
  scenes: [
    {
      scene_id: 'preview-scene-1',
      order: 1,
      scene_type: 'title',
      duration_seconds: 6,
      script_segment_ids: ['preview-segment-1'],
      narration_text: 'Every system has a hidden mechanism.',
      visual_description: 'A clean opening card with a calm, cinematic reveal.',
      composition: {
        layout: 'centered',
        alignment: 'center',
        hierarchy: 'text_first',
        viewport: 'static',
      },
      motion: { entrance: 'fade', exit: 'none', emphasis: 'none' },
      on_screen_text: [
        { text: 'The hidden mechanism', role: 'title', start_seconds: null, duration_seconds: null },
        { text: 'Look beneath the surface', role: 'subtitle', start_seconds: null, duration_seconds: null },
      ],
      transition: { type: 'fade', duration_seconds: 0.45 },
    },
  ],
};

const defaultProps: VideoProps = { plan: samplePlan };

export const Root: React.FC = () => (
  <>
    <Composition<any, VideoProps>
      id="Main"
      component={ScenePlanVideo}
      defaultProps={defaultProps}
      fps={30}
      width={1080}
      height={1920}
      durationInFrames={180}
      calculateMetadata={({ props }) => {
        assertScenePlan(props.plan);
        const profile = videoProfileForFormat(props.plan.format);
        const durationInFrames = framesForPlan(props.plan, profile.fps).reduce(
          (sum, duration) => sum + duration,
          0,
        );
        return { ...profile, durationInFrames };
      }}
    />
  </>
);
