/**
 * Client for the Web-TRX WebSocket protocol -- mirrors
 * backend/web_trx/protocol.py exactly (frame layouts, field order, byte
 * order). Text frames are JSON events/requests; binary frames start with a
 * 1-byte type tag.
 */

const FRAME_SPECTRUM = 0x01;
const FRAME_RX_AUDIO = 0x02;
const FRAME_TX_AUDIO = 0x03;

export interface SpectrumRow {
  generation: number;
  centerHz: number;
  spanHz: number;
  row: Float32Array;
}

export interface AudioChunk {
  sampleRateHz: number;
  pcm16: Int16Array;
}

export interface ServerEvent {
  event: string;
  [key: string]: unknown;
}

export class WebTrxClient {
  private ws: WebSocket | null = null;

  onEvent: (e: ServerEvent) => void = () => {};
  onSpectrum: (s: SpectrumRow) => void = () => {};
  onAudio: (a: AudioChunk) => void = () => {};
  onOpen: () => void = () => {};
  onClose: () => void = () => {};

  connect(url: string): void {
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => this.onOpen();
    ws.onclose = () => this.onClose();
    ws.onmessage = (ev: MessageEvent) => {
      if (typeof ev.data === "string") {
        this.onEvent(JSON.parse(ev.data) as ServerEvent);
      } else {
        this.handleBinary(ev.data as ArrayBuffer);
      }
    };
    this.ws = ws;
  }

  private handleBinary(buf: ArrayBuffer): void {
    const view = new DataView(buf);
    const type = view.getUint8(0);
    if (type === FRAME_SPECTRUM) {
      // Matches protocol._SPECTRUM_HEADER = struct.Struct("<BIdd"): 1 + 4 + 8 + 8 = 21 bytes.
      const generation = view.getUint32(1, true);
      const centerHz = view.getFloat64(5, true);
      const spanHz = view.getFloat64(13, true);
      const row = new Float32Array(buf.slice(21));
      this.onSpectrum({ generation, centerHz, spanHz, row });
    } else if (type === FRAME_RX_AUDIO) {
      // Matches protocol._AUDIO_HEADER = struct.Struct("<BI"): 1 + 4 = 5 bytes.
      const sampleRateHz = view.getUint32(1, true);
      const pcm16 = new Int16Array(buf.slice(5));
      this.onAudio({ sampleRateHz, pcm16 });
    }
  }

  request(name: string, params: Record<string, unknown> = {}): void {
    this.ws?.send(JSON.stringify({ request: name, ...params }));
  }

  sendTxAudio(sampleRateHz: number, pcm16: Int16Array): void {
    const frame = new Uint8Array(5 + pcm16.byteLength);
    const header = new DataView(frame.buffer);
    header.setUint8(0, FRAME_TX_AUDIO);
    header.setUint32(1, sampleRateHz, true);
    frame.set(new Uint8Array(pcm16.buffer, pcm16.byteOffset, pcm16.byteLength), 5);
    this.ws?.send(frame);
  }

  close(): void {
    this.ws?.close();
    this.ws = null;
  }
}
