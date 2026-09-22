<script lang="ts">
  import { onMount } from "svelte";
  import Waterfall from "./lib/Waterfall.svelte";
  import { WebTrxClient, type ServerEvent } from "./lib/ws";

  let waterfall: Waterfall;
  let connected = false;
  let backendName = "";
  let events: string[] = [];
  let rxFreqHz = 432_500_000;
  let txFreqHz = 432_500_000;
  let pocsagText = "DE DA2JH";
  let keyed = false;

  const client = new WebTrxClient();

  function log(line: string): void {
    events = [line, ...events].slice(0, 50);
  }

  client.onOpen = () => {
    connected = true;
    log("WS verbunden");
  };
  client.onClose = () => {
    connected = false;
    log("WS getrennt");
  };
  client.onEvent = (e: ServerEvent) => {
    if (e.event === "hello") backendName = String(e.backend);
    if (e.event === "keyed") keyed = true;
    if (e.event === "unkeyed") keyed = false;
    if (e.event === "estop") keyed = false;
    log(`${e.event} ${JSON.stringify(e)}`);
  };
  client.onSpectrum = (s) => waterfall?.pushRow(s.row);

  onMount(() => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    client.connect(`${proto}://${location.host}/ws`);
    return () => client.close();
  });

  function connectRx(): void {
    client.request("connect", { direction: "rx", device_type: "sim" });
    client.request("select_mode", { direction: "rx", mode: "fm", params: {} });
  }
  function connectTx(): void {
    client.request("connect", { direction: "tx", device_type: "sim" });
    client.request("select_mode", {
      direction: "tx",
      mode: "pocsag",
      params: { ric: 99, text: pocsagText },
    });
  }
  function tuneRx(): void {
    client.request("tune", { direction: "rx", freq_hz: rxFreqHz });
  }
  function tuneTx(): void {
    client.request("tune", { direction: "tx", freq_hz: txFreqHz });
  }
  function pttOn(): void {
    client.request("ptt_on");
  }
  function pttOff(): void {
    client.request("ptt_off");
  }
  function estop(): void {
    client.request("estop");
  }
</script>

<main>
  <h1>
    Web-TRX
    <span class="status" class:ok={connected}>
      {connected ? `verbunden (${backendName})` : "getrennt"}
    </span>
  </h1>

  <section>
    <h2>RX</h2>
    <button on:click={connectRx}>RX verbinden (sim, FM)</button>
    <input type="number" bind:value={rxFreqHz} step="1000" />
    <button on:click={tuneRx}>Tune</button>
    <Waterfall bind:this={waterfall} />
  </section>

  <section>
    <h2>TX &mdash; POCSAG</h2>
    <button on:click={connectTx}>TX verbinden (sim, POCSAG)</button>
    <input type="number" bind:value={txFreqHz} step="1000" />
    <button on:click={tuneTx}>Tune</button>
    <input type="text" bind:value={pocsagText} placeholder="Text" />
    <button on:click={pttOn} disabled={keyed}>PTT</button>
    <button on:click={pttOff} disabled={!keyed}>Unkey</button>
    <button class="estop" on:click={estop}>NOTAUS</button>
    <span>{keyed ? "\u{1F534} KEYED" : "⚪ idle"}</span>
  </section>

  <section>
    <h2>Events</h2>
    <ul class="events">
      {#each events as e}
        <li>{e}</li>
      {/each}
    </ul>
  </section>
</main>

<style>
  :global(body) {
    background: #0b0e14;
    color: #d8e1ee;
    font-family: system-ui, sans-serif;
    margin: 0;
    padding: 16px;
  }
  h1 {
    font-size: 1.2rem;
  }
  .status {
    font-size: 0.8rem;
    padding: 2px 8px;
    border-radius: 4px;
    background: #402020;
    margin-left: 8px;
  }
  .status.ok {
    background: #204020;
  }
  section {
    margin-bottom: 20px;
  }
  .estop {
    background: #a02020;
    color: white;
    font-weight: bold;
  }
  .events {
    max-height: 200px;
    overflow-y: auto;
    font-family: monospace;
    font-size: 0.75rem;
    list-style: none;
    padding: 0;
  }
</style>
