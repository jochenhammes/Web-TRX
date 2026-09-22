<script lang="ts">
  import { onMount } from "svelte";
  import Waterfall from "./lib/Waterfall.svelte";
  import Login from "./lib/Login.svelte";
  import { WebTrxClient, type ServerEvent, type SpectrumRow, type AudioChunk } from "./lib/ws";
  import { AudioPlayer, MicCapture } from "./lib/audio";
  import { checkSession, logout as apiLogout, fetchTxLog, type TxLogEntry } from "./lib/auth";

  // Only "sim" actually connects right now (SimBackend.DEVICE_TYPES) --
  // the real pluto/hackrf/rtlsdr/soundcard/aioc choices from
  // vendor/pluto-tx get added once GnuRadioBackend exists (see
  // docs/PROJECT_PLAN.md); listing them here already would just be
  // clickable dead ends.
  const DEVICE_TYPES: [string, string][] = [["sim", "Simulator"]];
  const MODES: [string, string][] = [
    ["fm", "FM"],
    ["ssb", "SSB (USB)"],
    ["lsb", "SSB (LSB)"],
    ["m17", "M17"],
    ["pocsag", "POCSAG"],
  ];
  const isAudioMode = (mode: string) => mode !== "pocsag";

  let waterfall: Waterfall;
  const client = new WebTrxClient();
  const audioPlayer = new AudioPlayer();
  const mic = new MicCapture();

  let authChecked = false;
  let authenticated = false;
  let wsConnected = false;
  let backendName = "";
  let events: string[] = [];
  let txLog: TxLogEntry[] = [];

  // -- RX state --
  let rxDeviceType = "sim";
  let rxScanned: [string, string][] = [];
  let rxConnection = "";
  let rxConnected = false;
  let rxMode = "fm";
  let rxFreqHz = 432_500_000;
  let floorDb = -100;
  let ceilingDb = -20;
  let zoom = 1;
  let audioOn = false;

  // -- TX state --
  let txDeviceType = "sim";
  let txScanned: [string, string][] = [];
  let txConnection = "";
  let txConnected = false;
  let txMode = "pocsag";
  let txFreqHz = 432_500_000;
  let ctcssHz = "";
  let srcCallsign = "";
  let dstCallsign = "@ALL";
  let ric = 1234567;
  let pocsagText = "DE DA2JH";
  let keyed = false;
  let micError = "";

  function log(line: string): void {
    events = [line, ...events].slice(0, 80);
  }

  client.onOpen = () => {
    wsConnected = true;
    log("WS verbunden");
  };
  client.onClose = () => {
    wsConnected = false;
    log("WS getrennt");
  };
  client.onEvent = (e: ServerEvent) => {
    if (e.event === "hello") backendName = String(e.backend);
    if (e.event === "connected") {
      if (e.direction === "rx") rxConnected = true;
      if (e.direction === "tx") txConnected = true;
    }
    if (e.event === "disconnected") {
      if (e.direction === "rx") rxConnected = false;
      if (e.direction === "tx") txConnected = false;
    }
    if (e.event === "scanned") {
      const devices = Object.entries(e.devices as Record<string, string>);
      if (e.direction === "rx") rxScanned = devices;
      if (e.direction === "tx") txScanned = devices;
    }
    if (e.event === "keyed") keyed = true;
    if (e.event === "unkeyed") {
      keyed = false;
      void refreshTxLog();
    }
    if (e.event === "estop") {
      keyed = false;
      void refreshTxLog();
    }
    log(`${e.event} ${JSON.stringify(e)}`);
  };
  client.onSpectrum = (s: SpectrumRow) => waterfall?.pushRow(s.row, s.centerHz, s.spanHz);
  client.onAudio = (a: AudioChunk) => {
    if (audioOn) audioPlayer.push(a.pcm16, a.sampleRateHz);
  };

  function connectWs(): void {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    client.connect(`${proto}://${location.host}/ws`);
  }

  async function refreshTxLog(): Promise<void> {
    txLog = await fetchTxLog(20);
  }

  async function handleLoginSuccess(): Promise<void> {
    authenticated = true;
    connectWs();
    await refreshTxLog();
  }

  async function doLogout(): Promise<void> {
    client.close();
    await apiLogout();
    location.reload(); // simplest full reset of all client-side session state
  }

  onMount(() => {
    void (async () => {
      authenticated = await checkSession();
      authChecked = true;
      if (authenticated) {
        connectWs();
        await refreshTxLog();
      }
    })();
    return () => client.close();
  });

  // -- RX actions --
  function scanRx(): void {
    client.request("scan", { direction: "rx", device_type: rxDeviceType });
  }
  function connectRx(): void {
    client.request("connect", { direction: "rx", device_type: rxDeviceType, connection: rxConnection });
  }
  function disconnectRx(): void {
    client.request("disconnect", { direction: "rx" });
  }
  function selectRxMode(): void {
    client.request("select_mode", { direction: "rx", mode: rxMode, params: {} });
  }
  function tuneRx(): void {
    client.request("tune", { direction: "rx", freq_hz: rxFreqHz });
  }
  function onWaterfallClick(freqHz: number): void {
    rxFreqHz = Math.round(freqHz / 100) * 100;
    tuneRx();
  }
  function toggleAudio(): void {
    audioOn = !audioOn;
    if (audioOn) audioPlayer.ensureStarted();
  }

  // -- TX actions --
  function scanTx(): void {
    client.request("scan", { direction: "tx", device_type: txDeviceType });
  }
  function connectTx(): void {
    client.request("connect", { direction: "tx", device_type: txDeviceType, connection: txConnection });
  }
  function disconnectTx(): void {
    client.request("disconnect", { direction: "tx" });
  }
  function txModeParams(): Record<string, unknown> {
    if (txMode === "fm") return ctcssHz ? { ctcss_hz: Number(ctcssHz) } : {};
    if (txMode === "m17") return { src_callsign: srcCallsign, dst_callsign: dstCallsign };
    if (txMode === "pocsag") return { ric, text: pocsagText };
    return {};
  }
  function selectTxMode(): void {
    client.request("select_mode", { direction: "tx", mode: txMode, params: txModeParams() });
  }
  function tuneTx(): void {
    client.request("tune", { direction: "tx", freq_hz: txFreqHz });
  }
  function estop(): void {
    client.request("estop");
    if (mic.isActive) mic.stop();
  }

  // Audio TX modes (FM/SSB/LSB/M17): press-and-hold PTT, mic streamed for
  // the duration. POCSAG: a single click, the backend keys, sends the
  // message and auto-unkeys itself (see SimBackend.ptt()) -- no mic
  // involved, matching vendor/pluto-tx's own text-digimode PTT model.
  async function startAudioTx(): Promise<void> {
    if (!isAudioMode(txMode)) return;
    client.request("ptt_on");
    try {
      mic.onChunk = (pcm16, sr) => client.sendTxAudio(sr, pcm16);
      await mic.start();
      micError = "";
    } catch (err) {
      micError = `Mikrofon: ${(err as Error).message}`;
      log(`error mic: ${(err as Error).message}`);
    }
  }
  function stopAudioTx(): void {
    if (!isAudioMode(txMode)) return;
    client.request("ptt_off");
    mic.stop();
  }
  function pocsagPtt(): void {
    client.request("ptt_on"); // one-shot; SimBackend/real POCSAG both auto-unkey, see docs/PROJECT_PLAN.md section 4
  }

  function fmtFreq(hz: number | null): string {
    return hz === null ? "—" : `${(hz / 1e6).toFixed(4)} MHz`;
  }
  function fmtTime(epochS: number): string {
    return new Date(epochS * 1000).toLocaleTimeString();
  }
  function fmtDuration(startedAt: number, endedAt: number | null): string {
    if (endedAt === null) return "läuft…";
    return `${(endedAt - startedAt).toFixed(1)} s`;
  }
</script>

{#if !authChecked}
  <div class="loading">Web-TRX &mdash; lade&hellip;</div>
{:else if !authenticated}
  <Login onSuccess={handleLoginSuccess} />
{:else}
<header class="topbar">
  <h1>Web-TRX</h1>
  <span class="status-pill" class:ok={wsConnected}>
    {wsConnected ? `verbunden · ${backendName}` : "getrennt"}
  </span>
  <div class="spacer"></div>
  <button on:click={doLogout}>Abmelden</button>
  <button class="danger" on:click={estop}>NOTAUS</button>
</header>

<div class="layout">
  <section class="panel rx-panel">
    <div class="panel-title">Empfang (RX)</div>

    <div class="row">
      <select bind:value={rxDeviceType}>
        {#each DEVICE_TYPES as [v, l]}<option value={v}>{l}</option>{/each}
      </select>
      <button on:click={scanRx}>Scan</button>
      <select bind:value={rxConnection}>
        <option value="">(auto)</option>
        {#each rxScanned as [v, l]}<option value={v}>{l}</option>{/each}
      </select>
      {#if !rxConnected}
        <button class="primary" on:click={connectRx}>Verbinden</button>
      {:else}
        <button on:click={disconnectRx}>Trennen</button>
      {/if}
    </div>

    <div class="row">
      <select bind:value={rxMode} on:change={selectRxMode} disabled={!rxConnected}>
        {#each MODES as [v, l]}<option value={v}>{l}</option>{/each}
      </select>
      <button on:click={toggleAudio}>{audioOn ? "\u{1F50A} RX-Audio an" : "\u{1F507} RX-Audio aus"}</button>
    </div>

    <div class="row">
      <input class="freq-readout" type="number" bind:value={rxFreqHz} step="100" />
      <span class="unit">Hz</span>
      <button on:click={tuneRx} disabled={!rxConnected}>Tune</button>
    </div>

    <Waterfall bind:this={waterfall} {floorDb} {ceilingDb} {zoom} onClickFreq={onWaterfallClick} />

    <div class="row sliders">
      <div class="field">
        <label for="floorDb">Floor {floorDb} dB</label>
        <input id="floorDb" type="range" min="-130" max="-40" bind:value={floorDb} />
      </div>
      <div class="field">
        <label for="ceilingDb">Ceiling {ceilingDb} dB</label>
        <input id="ceilingDb" type="range" min="-80" max="0" bind:value={ceilingDb} />
      </div>
      <div class="field">
        <label for="zoomInput">Zoom ×{zoom}</label>
        <input id="zoomInput" type="range" min="1" max="8" step="1" bind:value={zoom} />
      </div>
    </div>
  </section>

  <section class="panel tx-panel">
    <div class="panel-title">Senden (TX)</div>

    <div class="row">
      <select bind:value={txDeviceType}>
        {#each DEVICE_TYPES as [v, l]}<option value={v}>{l}</option>{/each}
      </select>
      <button on:click={scanTx}>Scan</button>
      <select bind:value={txConnection}>
        <option value="">(auto)</option>
        {#each txScanned as [v, l]}<option value={v}>{l}</option>{/each}
      </select>
      {#if !txConnected}
        <button class="primary" on:click={connectTx}>Verbinden</button>
      {:else}
        <button on:click={disconnectTx}>Trennen</button>
      {/if}
    </div>

    <div class="row">
      <select bind:value={txMode} on:change={selectTxMode} disabled={!txConnected}>
        {#each MODES as [v, l]}<option value={v}>{l}</option>{/each}
      </select>
    </div>

    <div class="row">
      <input class="freq-readout" type="number" bind:value={txFreqHz} step="100" />
      <span class="unit">Hz</span>
      <button on:click={tuneTx} disabled={!txConnected}>Tune</button>
    </div>

    {#if txMode === "fm"}
      <div class="row">
        <div class="field">
          <label for="ctcssHz">CTCSS Hz (leer = aus)</label>
          <input id="ctcssHz" type="text" bind:value={ctcssHz} placeholder="z.B. 88.5" on:change={selectTxMode} />
        </div>
      </div>
    {:else if txMode === "m17"}
      <div class="row">
        <div class="field">
          <label for="srcCallsign">Quell-Rufzeichen</label>
          <input id="srcCallsign" type="text" bind:value={srcCallsign} on:change={selectTxMode} />
        </div>
        <div class="field">
          <label for="dstCallsign">Ziel-Rufzeichen</label>
          <input id="dstCallsign" type="text" bind:value={dstCallsign} on:change={selectTxMode} />
        </div>
      </div>
    {:else if txMode === "pocsag"}
      <div class="row">
        <div class="field">
          <label for="ric">RIC</label>
          <input id="ric" type="number" bind:value={ric} on:change={selectTxMode} />
        </div>
        <div class="field" style="flex:1">
          <label for="pocsagText">Text</label>
          <input id="pocsagText" type="text" bind:value={pocsagText} on:change={selectTxMode} />
        </div>
      </div>
    {/if}

    <div class="row ptt-row">
      {#if isAudioMode(txMode)}
        <button
          class="ptt"
          class:active={keyed}
          disabled={!txConnected}
          on:mousedown={startAudioTx}
          on:mouseup={stopAudioTx}
          on:mouseleave={() => keyed && stopAudioTx()}
        >
          {keyed ? "\u{1F534} SENDET — halten" : "PTT (halten)"}
        </button>
      {:else}
        <button class="ptt" class:active={keyed} disabled={!txConnected || keyed} on:click={pocsagPtt}>
          {keyed ? "\u{1F534} SENDET" : "Aussenden"}
        </button>
      {/if}
      <button class="danger" on:click={estop}>NOTAUS</button>
    </div>
    {#if micError}<div class="mic-error">{micError}</div>{/if}
  </section>
</div>

<div class="row bottom-panels">
  <section class="panel log-panel">
    <div class="panel-title">TX-Verlauf</div>
    <ul class="tx-log">
      {#each txLog as entry (entry.id)}
        <li>
          <span class="mode-tag">{entry.mode.toUpperCase()}</span>
          <span>{fmtFreq(entry.freq_hz)}</span>
          <span class="dim">{fmtTime(entry.started_at)}</span>
          <span class="dim">{fmtDuration(entry.started_at, entry.ended_at)}</span>
          {#if Object.keys(entry.params).length}
            <span class="dim">{JSON.stringify(entry.params)}</span>
          {/if}
        </li>
      {:else}
        <li class="dim">Noch keine Aussendungen.</li>
      {/each}
    </ul>
  </section>

  <section class="panel log-panel">
    <div class="panel-title">Events</div>
    <ul class="events">
      {#each events as e}
        <li>{e}</li>
      {/each}
    </ul>
  </section>
</div>
{/if}

<style>
  :global(body) {
    padding: 16px;
  }

  .topbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }
  .spacer {
    flex: 1;
  }
  .status-pill {
    font-size: 0.72rem;
    padding: 3px 10px;
    border-radius: 999px;
    background: var(--danger-dim);
    color: var(--text);
    letter-spacing: 0.03em;
  }
  .status-pill.ok {
    background: #14382a;
    color: var(--ok);
  }

  .layout {
    display: grid;
    grid-template-columns: 1fr 340px;
    gap: 16px;
    align-items: start;
  }
  /* Grid items default to a min-width of their content's min-content size,
     which lets an unwrapped row of controls blow out the 340px TX column
     past the viewport -- min-width: 0 lets the track's own width win, and
     .row wraps so controls reflow instead of overflowing it. */
  .rx-panel,
  .tx-panel {
    min-width: 0;
  }
  @media (max-width: 900px) {
    .layout {
      grid-template-columns: 1fr;
    }
  }

  .panel {
    margin-bottom: 16px;
  }

  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
    flex-wrap: wrap;
  }
  .row.sliders {
    align-items: stretch;
    gap: 16px;
  }
  .row.sliders .field {
    flex: 1;
    min-width: 90px;
  }
  .unit {
    color: var(--text-dim);
    font-size: 0.75rem;
  }

  select,
  .freq-readout,
  input[type="text"],
  input[type="number"] {
    min-width: 0;
  }
  .freq-readout {
    flex: 1;
  }

  .ptt-row {
    margin-top: 4px;
  }
  button.ptt {
    flex: 1;
    padding: 10px;
    font-weight: 700;
    letter-spacing: 0.03em;
    background: var(--bg-2);
    border: 1px solid var(--border-light);
  }
  button.ptt.active {
    background: var(--danger);
    border-color: var(--danger);
    color: #fff;
    box-shadow: 0 0 14px rgba(255, 77, 77, 0.6);
  }

  .mic-error {
    color: var(--danger);
    font-size: 0.75rem;
    margin-top: 4px;
  }

  .events {
    max-height: 220px;
    overflow-y: auto;
    font-family: var(--mono);
    font-size: 0.72rem;
    list-style: none;
    padding: 0;
    margin: 0;
    color: var(--text-dim);
  }
  .events li {
    padding: 2px 0;
    border-bottom: 1px solid var(--border);
  }

  .loading {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    color: var(--text-dim);
  }

  .bottom-panels {
    align-items: stretch;
  }
  .bottom-panels .panel {
    flex: 1;
    min-width: 0;
    margin-bottom: 0;
  }

  .tx-log {
    max-height: 220px;
    overflow-y: auto;
    font-size: 0.78rem;
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .tx-log li {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    padding: 4px 0;
    border-bottom: 1px solid var(--border);
  }
  .mode-tag {
    font-family: var(--mono);
    font-weight: 700;
    color: var(--accent);
    min-width: 4.5em;
  }
  .dim {
    color: var(--text-dim);
    font-size: 0.75rem;
  }
</style>
