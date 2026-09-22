<script lang="ts">
  import { onMount } from "svelte";

  export let width = 900;
  export let height = 320;
  export let floorDb = -100;
  export let ceilingDb = -20;
  // Display-only zoom: crops the incoming row to its center 1/zoom
  // fraction before rendering. NOT a real zoom-FFT (that needs a bigger
  // FFT computed server-side around the ring buffer, see vendor/pluto-tx
  // pluto_advanced_rx/fft_probe.py's FftProbe.set_zoom() -- meaningful
  // only once a real device feeds actual samples). This is a legitimate,
  // fully client-side stand-in for now: it lets the zoom control and its
  // interaction (Klick-zum-Tunen at the zoomed scale) be built and tested
  // end-to-end against SimBackend before the real thing exists.
  export let zoom = 1;
  // Called with the frequency (Hz) the user clicked, computed from the
  // most recently rendered row's center/span and the current zoom crop.
  export let onClickFreq: ((freqHz: number) => void) | undefined = undefined;

  const spectrumHeight = 90;

  let waterfallCanvas: HTMLCanvasElement;
  let spectrumCanvas: HTMLCanvasElement;
  let wCtx: CanvasRenderingContext2D;
  let sCtx: CanvasRenderingContext2D;
  let lastCenterHz = 0;
  let lastSpanHz = 0;

  onMount(() => {
    wCtx = waterfallCanvas.getContext("2d")!;
    sCtx = spectrumCanvas.getContext("2d")!;
    wCtx.fillStyle = "#04070c";
    wCtx.fillRect(0, 0, width, height);
  });

  // SDR++-like palette: dark blue noise floor through cyan/green to a
  // yellow/red hot peak.
  const STOPS: Array<[number, [number, number, number]]> = [
    [0.0, [6, 10, 40]],
    [0.3, [10, 70, 140]],
    [0.55, [20, 180, 170]],
    [0.78, [240, 220, 60]],
    [1.0, [235, 40, 40]],
  ];

  function dbToColor(db: number): [number, number, number] {
    const t = Math.min(1, Math.max(0, (db - floorDb) / (ceilingDb - floorDb)));
    for (let i = 1; i < STOPS.length; i++) {
      const [t0, c0] = STOPS[i - 1];
      const [t1, c1] = STOPS[i];
      if (t <= t1) {
        const f = (t - t0) / (t1 - t0 || 1);
        return [
          Math.round(c0[0] + (c1[0] - c0[0]) * f),
          Math.round(c0[1] + (c1[1] - c0[1]) * f),
          Math.round(c0[2] + (c1[2] - c0[2]) * f),
        ];
      }
    }
    return STOPS[STOPS.length - 1][1];
  }

  function zoomedSlice(row: Float32Array): Float32Array {
    if (zoom <= 1) return row;
    const n = row.length;
    const keep = Math.max(8, Math.round(n / zoom));
    const start = Math.floor((n - keep) / 2);
    return row.subarray(start, start + keep);
  }

  export function pushRow(row: Float32Array, centerHz?: number, spanHz?: number): void {
    if (!wCtx || !sCtx) return;
    if (centerHz !== undefined) lastCenterHz = centerHz;
    if (spanHz !== undefined) lastSpanHz = spanHz;

    const slice = zoomedSlice(row);
    const n = slice.length;

    // Scroll the waterfall down by one line, draw the new row at the top.
    wCtx.drawImage(waterfallCanvas, 0, 0, width, height - 1, 0, 1, width, height - 1);
    const lineImage = wCtx.createImageData(width, 1);
    for (let x = 0; x < width; x++) {
      const bin = Math.floor((x / width) * n);
      const [r, g, b] = dbToColor(slice[bin]);
      const i = x * 4;
      lineImage.data[i] = r;
      lineImage.data[i + 1] = g;
      lineImage.data[i + 2] = b;
      lineImage.data[i + 3] = 255;
    }
    wCtx.putImageData(lineImage, 0, 0);

    sCtx.fillStyle = "#04070c";
    sCtx.fillRect(0, 0, width, spectrumHeight);
    sCtx.strokeStyle = "#5ad1ff";
    sCtx.lineWidth = 1.25;
    sCtx.beginPath();
    for (let x = 0; x < width; x++) {
      const bin = Math.floor((x / width) * n);
      const t = Math.min(1, Math.max(0, (slice[bin] - floorDb) / (ceilingDb - floorDb)));
      const y = spectrumHeight - t * spectrumHeight;
      if (x === 0) sCtx.moveTo(x, y);
      else sCtx.lineTo(x, y);
    }
    sCtx.stroke();
  }

  function handleClick(ev: MouseEvent, canvas: HTMLCanvasElement): void {
    if (!onClickFreq || lastSpanHz === 0) return;
    const rect = canvas.getBoundingClientRect();
    const xFrac = (ev.clientX - rect.left) / rect.width; // 0..1 across the CURRENT (zoomed) view
    const displayedSpanHz = lastSpanHz / zoom;
    const loHz = lastCenterHz - displayedSpanHz / 2;
    onClickFreq(loHz + xFrac * displayedSpanHz);
  }
</script>

<div class="waterfall-wrap">
  <canvas
    bind:this={spectrumCanvas}
    width={width}
    height={spectrumHeight}
    class="clickable"
    on:click={(e) => handleClick(e, spectrumCanvas)}
  ></canvas>
  <canvas
    bind:this={waterfallCanvas}
    width={width}
    height={height}
    class="clickable"
    on:click={(e) => handleClick(e, waterfallCanvas)}
  ></canvas>
</div>

<style>
  .waterfall-wrap {
    display: flex;
    flex-direction: column;
    gap: 2px;
    background: #000;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    width: fit-content;
  }
  canvas {
    display: block;
  }
  canvas.clickable {
    cursor: crosshair;
  }
</style>
