import React from 'react';
import { Composition } from 'remotion';
import { PlaceholderVideo } from './PlaceholderVideo';

export const Root: React.FC = () => (
  <Composition
    id="Main"
    component={PlaceholderVideo}
    durationInFrames={1050}
    fps={30}
    width={1080}
    height={1920}
  />
);
