declare module "@pipecat-ai/client" {
  export class PipecatClient {
    constructor(options: any);
    connect(): Promise<void>;
    disconnect(): void;
    startAudio(): Promise<void>;
    stopAudio(): Promise<void>;
    on(event: string, cb: (payload: any) => void): void;
  }
}
