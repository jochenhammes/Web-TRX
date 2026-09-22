/**
 * Web Audio glue for the RX/TX audio channels (see protocol.ts / backend
 * protocol.py's RX_AUDIO / TX_AUDIO binary frames). Deliberately built with
 * ScriptProcessorNode rather than an AudioWorklet -- it is deprecated but
 * needs no separate worklet module file to serve/build correctly, which
 * keeps this whole thing verifiable in one pass against SimBackend without
 * real hardware. Upgrading to AudioWorklet is planned hardening work once
 * real-hardware testing starts (see docs/PROJECT_PLAN.md milestone M5).
 */

/** Schedules incoming PCM16 chunks back-to-back on an AudioContext --
 * a minimal, jitter-buffer-free streaming player. Good enough for
 * SimBackend's steady synthetic tone; a real jitter buffer is M3/M5
 * hardening work once real, bursty network audio is involved. */
export class AudioPlayer {
  private ctx: AudioContext | null = null;
  private nextStartTime = 0;

  ensureStarted(): void {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.nextStartTime = this.ctx.currentTime;
    }
    if (this.ctx.state === "suspended") void this.ctx.resume();
  }

  push(pcm16: Int16Array, sampleRateHz: number): void {
    this.ensureStarted();
    const ctx = this.ctx!;
    const float32 = new Float32Array(pcm16.length);
    for (let i = 0; i < pcm16.length; i++) float32[i] = pcm16[i] / 32768;

    const buffer = ctx.createBuffer(1, float32.length, sampleRateHz);
    buffer.copyToChannel(float32, 0);

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);

    const startAt = Math.max(this.nextStartTime, ctx.currentTime);
    source.start(startAt);
    this.nextStartTime = startAt + buffer.duration;
  }

  stop(): void {
    this.ctx?.close();
    this.ctx = null;
    this.nextStartTime = 0;
  }
}

/** Captures the microphone and delivers PCM16 chunks at the AudioContext's
 * native sample rate via `onChunk`. Caller is responsible for actually
 * sending them (see App.svelte: only while PTT is on and the TX mode is
 * audio-based, matching vendor/pluto-tx's own is_audio_only()/needs_ptt
 * distinction between voice modes and text digimodes like POCSAG). */
export class MicCapture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;

  onChunk: (pcm16: Int16Array, sampleRateHz: number) => void = () => {};

  async start(): Promise<void> {
    if (this.ctx) return;
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.ctx = new AudioContext();
    this.source = this.ctx.createMediaStreamSource(this.stream);
    // 4096-sample buffer: large enough to avoid glitching on this
    // single-threaded ScriptProcessorNode, small enough to keep PTT
    // latency reasonable for the simulator loop.
    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    this.processor.onaudioprocess = (ev) => {
      const input = ev.inputBuffer.getChannelData(0);
      const pcm16 = new Int16Array(input.length);
      for (let i = 0; i < input.length; i++) {
        const s = Math.max(-1, Math.min(1, input[i]));
        pcm16[i] = s < 0 ? s * 32768 : s * 32767;
      }
      this.onChunk(pcm16, this.ctx!.sampleRate);
    };
    this.source.connect(this.processor);
    // ScriptProcessorNode only fires onaudioprocess while connected into
    // the graph towards the destination -- routed through a silent gain
    // node so nothing is actually audible (no local monitoring echo).
    const silence = this.ctx.createGain();
    silence.gain.value = 0;
    this.processor.connect(silence);
    silence.connect(this.ctx.destination);
  }

  stop(): void {
    this.processor?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close();
    this.processor = null;
    this.source = null;
    this.stream = null;
    this.ctx = null;
  }

  get isActive(): boolean {
    return this.ctx !== null;
  }
}
