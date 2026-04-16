import { lazy } from 'react';

let whiteboardCanvasModulePromise: Promise<typeof import('./WhiteboardCanvas')> | null = null;

function loadWhiteboardCanvasModule() {
  whiteboardCanvasModulePromise ??= import('./WhiteboardCanvas');
  return whiteboardCanvasModulePromise;
}

export const LazyWhiteboardCanvas = lazy(() =>
  loadWhiteboardCanvasModule().then((module) => ({ default: module.WhiteboardCanvas })),
);

export function preloadWhiteboardCanvas() {
  return loadWhiteboardCanvasModule();
}