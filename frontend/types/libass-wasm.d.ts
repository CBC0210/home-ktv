declare module "libass-wasm" {
  interface SubtitlesOctopusOptions {
    video?: HTMLVideoElement;
    canvas?: HTMLCanvasElement;
    container?: HTMLElement;
    subUrl?: string;
    subContent?: string;
    workerUrl?: string;
    legacyWorkerUrl?: string;
    targetFps?: number;
    prescaleFactor?: number;
    renderAhead?: number;
    availableFonts?: Record<string, string>;
    fallbackFont?: string;
  }

  class SubtitlesOctopus {
    constructor(options: SubtitlesOctopusOptions);
    setCurrentTime(time: number): void;
    freeTrack(): void;
    dispose(): void;
  }

  export default SubtitlesOctopus;
}
