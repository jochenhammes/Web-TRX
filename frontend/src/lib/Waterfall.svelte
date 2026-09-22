<script lang="ts">
  import { onMount } from "svelte";

  export let width = 900;
  export let height = 300;
  export let floorDb = -100;
  export let ceilingDb = -20;

  const spectrumHeight = 80;

  let waterfallCanvas: HTMLCanvasElement;
  let spectrumCanvas: HTMLCanvasElement;
  let wCtx: CanvasRenderingContext2D;
  let sCtx: CanvasRenderingContext2D;

  onMount(() => {
    wCtx = waterfallCanvas.getContext("2d")!;
    sCtx = spectrumCanvas.getContext("2d")!;
    wCtx.fillStyle = "#04070d";
    wCtx.fillRect(0, 0, width, height);
  });

  // Simple fixed blue -> cyan -> yellow -> red ramp -- a placeholder good
  // enough to prove the pipeline end-to-end; a real palette/contrast
  // control (floor/ceiling sliders in the UI, not just props) is M2 work
  // (see docs/PROJECT_PLAN.md milestone table).
  const STOPS: Array<[number, [number, number, number]]> = [
    [0.0, [8, 8, 40]],
    [0.35, [10, 90, 160]],
    [0.6, [40, 200, 180]],
    [0.8, [250, 220, 40]],
    [1.0, [230, 30, 30]],
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

  export function pushRow(row: Float32Array): void {
    if (!wCtx || !sCtx) return;
    const n = row.length;

    // Scroll the waterfall down by one line, draw the new row at the top.
    wCtx.drawImage(waterfallCanvas, 0, 0, width, height - 1, 0, 1, width, height - 1);
    const lineImage = wCtx.createImageData(width, 1);
    for (let x = 0; x < width; x++) {
      const bin = Math.floor((x / width) * n);
      const [r, g, b] = dbToColor(row[bin]);
      const i = x * 4;
      lineImage.data[i] = r;
      lineImage.data[i + 1] = g;
      lineImage.data[i + 2] = b;
      lineImage.data[i + 3] = 255;
    }
    wCtx.putImageData(lineImage, 0, 0);

    // Spectrum line above the waterfall, redrawn fresh each row.
    sCtx.fillStyle = "#04070d";
    sCtx.fillRect(0, 0, width, spectrumHeight);
    sCtx.strokeStyle = "#5ad1ff";
    sCtx.beginPath();
    for (let x = 0; x < width; x++) {
      const bin = Math.floor((x / width) * n);
      const t = Math.min(1, Math.max(0, (row[bin] - floorDb) / (ceilingDb - floorDb)));
      const y = spectrumHeight - t * spectrumHeight;
      if (x === 0) sCtx.moveTo(x, y);
      else sCtx.lineTo(x, y);
    }
    sCtx.stroke();
  }
</script>

<div class="waterfall-wrap">
  <canvas bind:this={spectrumCanvas} width={width} height={spectrumHeight}></canvas>
  <canvas bind:this={waterfallCanvas} width={width} height={height}></canvas>
</div>

<style>
  .waterfall-wrap {
    display: flex;
    flex-direction: column;
    gap: 2px;
    background: #000;
    width: fit-content;
  }
  canvas {
    display: block;
  }
</style>
