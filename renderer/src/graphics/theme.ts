/** Shared light editorial palette for every rendered scene and graphic. */
export const THEME = {
  canvas: '#F7F5EF',
  canvasCool: '#F1F4F2',
  canvasWarm: '#FBF7EA',
  surface: '#FFFEFA',
  surfaceTint: '#EEECE4',
  text: '#202725',
  body: '#3D4844',
  muted: '#56615D',
  subtle: '#75807B',
  accent: '#725400',
  accentBright: '#C18B08',
  accentSoft: '#F5E7B7',
  blue: '#3F7183',
  blueSoft: '#DCE8EB',
  green: '#47745F',
  terracotta: '#A45E49',
  line: '#D8D6CC',
  grid: 'rgba(44, 55, 50, 0.07)',
  shadow: 'rgba(42, 45, 39, 0.10)',
} as const;

export const CHART_COLORS = [THEME.blue, THEME.accentBright, THEME.terracotta, THEME.green] as const;
