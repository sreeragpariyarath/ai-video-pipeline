export type VideoFormat = 'short' | 'mid_form' | 'long_form';
export type SceneType =
  | 'title'
  | 'text_focus'
  | 'statistic'
  | 'comparison'
  | 'process'
  | 'diagram'
  | 'timeline'
  | 'illustration'
  | 'conclusion';

export type ScenePlan = {
  scene_plan_id: string;
  script_id: string;
  research_id: string;
  format: VideoFormat;
  target_seconds: number;
  planned_seconds: number;
  scenes: Scene[];
  created_at: string;
};

export type Scene = {
  scene_id: string;
  order: number;
  scene_type: SceneType;
  duration_seconds: number;
  script_segment_ids: string[];
  narration_text: string;
  visual_description: string;
  composition: {
    layout: 'centered' | 'split' | 'stacked' | 'full_bleed' | 'grid';
    alignment: 'start' | 'center' | 'end';
    hierarchy: 'text_first' | 'visual_first' | 'balanced';
    viewport: 'static' | 'push_in' | 'pull_out' | 'pan_left' | 'pan_right';
  };
  motion: {
    entrance: 'none' | 'fade' | 'slide_up' | 'slide_down' | 'slide_left' | 'slide_right' | 'scale';
    exit: 'none' | 'fade' | 'slide_up' | 'slide_down' | 'slide_left' | 'slide_right' | 'scale';
    emphasis: 'none' | 'pulse' | 'scale' | 'underline';
  };
  on_screen_text: Array<{
    text: string;
    role: 'title' | 'subtitle' | 'label' | 'emphasis' | 'caption' | null;
    start_seconds: number | null;
    duration_seconds: number | null;
  }>;
  transition: { type: 'cut' | 'fade' | 'slide'; duration_seconds: number };
};

export type VideoProps = { plan: ScenePlan };

export type VideoProfile = { width: number; height: number; fps: number };

const VIDEO_PROFILES: Record<VideoFormat, VideoProfile> = {
  short: { width: 1080, height: 1920, fps: 30 },
  mid_form: { width: 1920, height: 1080, fps: 30 },
  long_form: { width: 1920, height: 1080, fps: 30 },
};

export const videoProfileForFormat = (format: VideoFormat): VideoProfile => {
  const profile = VIDEO_PROFILES[format];
  if (!profile) throw new Error(`Unsupported video format: ${String(format)}`);
  return profile;
};

export const framesForPlan = (plan: ScenePlan, fps: number): number[] => {
  assertScenePlan(plan);
  if (!Number.isFinite(fps) || fps <= 0) {
    throw new Error('Renderer frame rate must be finite and positive.');
  }
  const totalFrames = Math.round(plan.planned_seconds * fps);
  if (totalFrames < plan.scenes.length) {
    throw new Error(
      `Scene plan is too short for ${plan.scenes.length} scenes at ${fps} fps; ` +
        'each scene needs at least one frame.',
    );
  }
  const remainingFrames = totalFrames - plan.scenes.length;
  const totalSeconds = plan.scenes.reduce((sum, scene) => sum + scene.duration_seconds, 0);
  const exactExtras = plan.scenes.map(
    (scene) => (remainingFrames * scene.duration_seconds) / totalSeconds,
  );
  const extras = exactExtras.map(Math.floor);
  let remainder = remainingFrames - extras.reduce((sum, frames) => sum + frames, 0);
  const order = exactExtras
    .map((value, index) => ({ index, fraction: value - Math.floor(value) }))
    .sort((a, b) => b.fraction - a.fraction || a.index - b.index);
  for (let index = 0; remainder > 0; index += 1, remainder -= 1) {
    extras[order[index % order.length].index] += 1;
  }
  return extras.map((frames) => frames + 1);
};

export const assertScenePlan = (plan: ScenePlan): void => {
  if (!plan || !Array.isArray(plan.scenes) || plan.scenes.length === 0) {
    throw new Error('Scene plan must contain at least one scene.');
  }
  if (!plan.scene_plan_id?.trim() || !plan.script_id?.trim() || !plan.research_id?.trim()) {
    throw new Error('Scene plan, script, and research IDs are required.');
  }
  if (!Number.isFinite(plan.target_seconds) || plan.target_seconds <= 0) {
    throw new Error('Scene plan target duration must be finite and positive.');
  }
  if (!Number.isFinite(plan.planned_seconds) || plan.planned_seconds <= 0) {
    throw new Error('Scene plan duration must be finite and positive.');
  }
  if (!['short', 'mid_form', 'long_form'].includes(plan.format)) {
    throw new Error(`Unsupported video format: ${String(plan.format)}`);
  }
  const ids = new Set<string>();
  const segmentIds = new Set<string>();
  let seconds = 0;
  plan.scenes.forEach((scene, index) => {
    if (!scene || typeof scene !== 'object') {
      throw new Error(`Scene ${index + 1} must be an object.`);
    }
    if (typeof scene.scene_id !== 'string' || !scene.scene_id.trim() || ids.has(scene.scene_id)) {
      throw new Error(`Scene ${index + 1} has a missing or duplicate ID.`);
    }
    ids.add(scene.scene_id);
    if (scene.order !== index + 1) {
      throw new Error('Scene order must be sequential and start at 1.');
    }
    if (!Number.isFinite(scene.duration_seconds) || scene.duration_seconds <= 0) {
      throw new Error(`Scene ${scene.scene_id} must have a finite positive duration.`);
    }
    if (
      ![
        'title', 'text_focus', 'statistic', 'comparison', 'process',
        'diagram', 'timeline', 'illustration', 'conclusion',
      ].includes(scene.scene_type)
    ) {
      throw new Error(`Scene ${scene.scene_id} has an unsupported type.`);
    }
    if (
      !Array.isArray(scene.script_segment_ids) ||
      !scene.script_segment_ids.length ||
      scene.script_segment_ids.some((id) => typeof id !== 'string' || !id.trim())
    ) {
      throw new Error(`Scene ${scene.scene_id} is missing script content.`);
    }
    scene.script_segment_ids.forEach((id) => {
      if (segmentIds.has(id)) {
        throw new Error(`Script segment ${id} is assigned to more than one scene.`);
      }
      segmentIds.add(id);
    });
    if (typeof scene.narration_text !== 'string' || !scene.narration_text.trim()) {
      throw new Error(`Scene ${scene.scene_id} narration must be non-empty.`);
    }
    if (typeof scene.visual_description !== 'string' || !scene.visual_description.trim()) {
      throw new Error(`Scene ${scene.scene_id} visual description must be non-empty.`);
    }
    validateSceneCapabilities(scene);
    seconds += scene.duration_seconds;
  });
  if (Math.abs(seconds - plan.planned_seconds) > 0.01) {
    throw new Error('Planned duration does not match the scene durations.');
  }
};

const contains = (options: readonly string[], value: unknown): boolean =>
  typeof value === 'string' && options.includes(value);

const validateSceneCapabilities = (scene: Scene): void => {
  const layouts = ['centered', 'split', 'stacked', 'full_bleed', 'grid'] as const;
  const alignments = ['start', 'center', 'end'] as const;
  const hierarchies = ['text_first', 'visual_first', 'balanced'] as const;
  const viewports = ['static', 'push_in', 'pull_out', 'pan_left', 'pan_right'] as const;
  const motions = ['none', 'fade', 'slide_up', 'slide_down', 'slide_left', 'slide_right', 'scale'] as const;
  const emphasis = ['none', 'pulse', 'scale', 'underline'] as const;
  const transitions = ['cut', 'fade', 'slide'] as const;
  const roles = ['title', 'subtitle', 'label', 'emphasis', 'caption'] as const;

  if (!scene.composition || !contains(layouts, scene.composition.layout)) {
    throw new Error(`Scene ${scene.scene_id} has an unsupported layout.`);
  }
  if (!contains(alignments, scene.composition.alignment)) {
    throw new Error(`Scene ${scene.scene_id} has an unsupported alignment.`);
  }
  if (!contains(hierarchies, scene.composition.hierarchy)) {
    throw new Error(`Scene ${scene.scene_id} has an unsupported visual hierarchy.`);
  }
  if (!contains(viewports, scene.composition.viewport)) {
    throw new Error(`Scene ${scene.scene_id} has an unsupported viewport treatment.`);
  }
  if (!scene.motion || !contains(motions, scene.motion.entrance) || !contains(motions, scene.motion.exit)) {
    throw new Error(`Scene ${scene.scene_id} has unsupported motion.`);
  }
  if (!contains(emphasis, scene.motion.emphasis)) {
    throw new Error(`Scene ${scene.scene_id} has unsupported emphasis motion.`);
  }
  if (!scene.transition || !contains(transitions, scene.transition.type)) {
    throw new Error(`Scene ${scene.scene_id} has an unsupported transition.`);
  }
  const transitionSeconds = scene.transition.duration_seconds;
  if (!Number.isFinite(transitionSeconds) || transitionSeconds < 0 || transitionSeconds > 2) {
    throw new Error(`Scene ${scene.scene_id} transition duration must be between 0 and 2 seconds.`);
  }
  if (scene.transition.type === 'cut' && transitionSeconds !== 0) {
    throw new Error(`Scene ${scene.scene_id} cut transition must have zero duration.`);
  }
  if (scene.transition.type !== 'cut' && transitionSeconds === 0) {
    throw new Error(`Scene ${scene.scene_id} ${scene.transition.type} transition needs a positive duration.`);
  }
  if (transitionSeconds >= scene.duration_seconds && transitionSeconds > 0) {
    throw new Error(`Scene ${scene.scene_id} transition must be shorter than the scene.`);
  }
  if (!Array.isArray(scene.on_screen_text)) {
    throw new Error(`Scene ${scene.scene_id} on-screen text must be a list.`);
  }
  scene.on_screen_text.forEach((overlay, index) => {
    if (!overlay || typeof overlay.text !== 'string' || !overlay.text.trim()) {
      throw new Error(`Scene ${scene.scene_id} overlay ${index + 1} needs text.`);
    }
    if (overlay.role !== null && !contains(roles, overlay.role)) {
      throw new Error(`Scene ${scene.scene_id} overlay ${index + 1} has an unsupported role.`);
    }
    const start = overlay.start_seconds;
    const duration = overlay.duration_seconds;
    if (start !== null && (!Number.isFinite(start) || start < 0 || start >= scene.duration_seconds)) {
      throw new Error(`Scene ${scene.scene_id} overlay ${index + 1} starts outside the scene.`);
    }
    if (duration !== null && (!Number.isFinite(duration) || duration <= 0)) {
      throw new Error(`Scene ${scene.scene_id} overlay ${index + 1} duration must be positive.`);
    }
    if (duration !== null && (start ?? 0) + duration > scene.duration_seconds) {
      throw new Error(`Scene ${scene.scene_id} overlay ${index + 1} timing exceeds the scene.`);
    }
  });
};
