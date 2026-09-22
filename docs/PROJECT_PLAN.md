# Web-TRX — Projektplan

Einheitliche Weboberfläche für `pluto-tx`/`pluto-advanced-rx` (Sende- und
Empfangs-App für ADALM-PLUTO, HackRF One und RTL-SDR). Ziel: ein Funkamateur
bedient die am Server angeschlossenen SDRs vollständig über den Browser —
Senden und Empfangen, inklusive Wasserfall/Spektrum, Audio und Digimodes.

## 1. Rahmenbedingungen (Setting)

- Ein Server, ein oder mehrere SDRs (Pluto/Pluto+, HackRF One, RTL-SDR,
  Soundkarte/AIOC als TX-Backend für externe Funkgeräte).
- **Immer genau ein Nutzer** — kein Multi-Tenant-Betrieb, kein
  Rechte-/Rollenmodell nötig. Vereinfacht die Server-Architektur erheblich
  (ein globaler Session-State, keine Scheduling-Logik für konkurrierende
  Zugriffe).
- Nutzer ist immer lizenzierter Funkamateur — Verantwortung für
  Frequenzwahl/Bandplan/Leistung bleibt beim Betreiber, wie im bestehenden
  `pluto-tx` auch.
- Modernes Web-Frontend + Backend auf dem Server; Zugriff übers Netzwerk,
  ggf. Internet mit VPN.
- **Backend soll möglichst wenig neu entwickeln** — die eigentliche
  Signalverarbeitung (Flowgraphs, Geräteabstraktion, Sicherheitsschicht)
  kommt aus `pluto-tx`/`pluto-advanced-rx`/`pluto-cli`.
- RX-Kernstück: flüssiger Wasserfall + Spektrum mit einfachen Tune-/Zoom-/
  Fenster-Werkzeugen, analog zu SDR++ (das ebenfalls auf Webtechnologien
  setzt).

## 2. Wiederverwendbare Bausteine aus `pluto-tx` (Bestandsaufnahme)

`pluto-tx` ist bereits fast genau das, was das Web-TRX-Backend braucht, nur
mit Qt-GUI bzw. stdout-JSON statt Web-API als Frontend:

| Baustein | Datei | Wiederverwendung |
|---|---|---|
| `PlutoTxFlowgraph` | `pluto_tx/flowgraph.py` | komplette TX-Signalkette, alle Modi (`MODE_FM`, `MODE_SSB`, `MODE_M17`, `MODE_POCSAG`, …), direkt importierbar |
| `AdvancedRxFlowgraph` | `pluto_advanced_rx/flowgraph.py` | komplette RX-Signalkette inkl. Digimode-Decoder |
| `PlutoSafety` | `pluto_tx/safety.py` | GNU-Radio-unabhängige Abschaltschicht (`force_safe_state()`), NOTAUS-Grundlage |
| Geräteabstraktion | `pluto_tx/devices/*`, `pluto_advanced_rx/devices/*` | Pluto/HackRF/RTL-SDR/Soundcard/AIOC einheitlich, inkl. Scan/Probe |
| `FftProbe` | `pluto_advanced_rx/fft_probe.py` | **Der Schlüsselbaustein für den Web-Wasserfall.** Reiner Python/NumPy-`gr.sync_block`, berechnet FFT-Zeilen laufend und stellt sie pollbar bereit (`get_latest_row(generation)`), inkl. Zoom-FFT und Video-Averaging, alles ohne Flowgraph-Rebuild. Muss nur noch statt an einen Qt-Timer an eine WebSocket-Push-Schleife gehängt werden. |
| JSON-Event-Schema | `pluto_cli/runtime.py`, `pluto_cli/README.md §6` | fertiges, dokumentiertes Ereignisformat (`keyed`, `m17_fields`, `pocsag_message`, `meshtastic_frame`, `filebroadcast_progress`, `error`, …) — Vorlage für das WebSocket-Protokoll, keine Neuerfindung nötig |
| Signal-/Shutdown-Handling | `pluto_cli/runtime.py` (`install_safety_handlers`, `run_tx_session`, `run_rx_session`) | Muster für sichere Zustandsübergänge (SIGINT/SIGTERM/Exception → `shutdown_safe()`), 1:1 auf einen Server-Prozess übertragbar |
| Bandplan/PHY-Konstanten | `pluto_tx/config.py`, `pluto_advanced_rx/config.py` | Bandpläne, M17-/LoRa-PHY-Parameter, Presets |

**Echte Lücken**, die es in `pluto-tx` nicht gibt und die Web-TRX neu bauen
muss:

1. **Netzwerk-Streaming von Spektrum/Wasserfall.** `pluto-cli` sagt es
   explizit: *"No live waterfall/spectrum display. headless by design"*.
   `FftProbe` existiert nur GUI-seitig, gepollt von einem Qt-Timer.
2. **Netzwerk-Audio (bidirektional).** GUI-Apps nutzen lokale ALSA/PipeWire-
   Geräte. Mikrofon-Erfassung im Browser → Server (TX) und Demod-Audio
   Server → Browser (RX) existieren nirgends.
3. **Das eigentliche Web-Frontend** — es gibt aktuell nur Qt-GUI und CLI.
4. **Eine Dauerprozess-Session-Verwaltung** statt CLI-Einzelaufrufen (Connect/
   Disconnect, Moduswechsel, Tuning — alles muss jetzt interaktiv über eine
   laufende Verbindung laufen statt per Kommandozeilen-Flag beim Start).

### Architekturentscheidung: Wie bindet Web-TRX den `pluto-tx`-Code ein?

`pluto-cli` selbst ist die Blaupause: *"a separate top-level package that
imports and reuses `pluto_tx`'s/`pluto_advanced_rx`'s existing flowgraph/
device/audio code directly"*. Web-TRX' Backend folgt demselben Muster —
**es importiert `PlutoTxFlowgraph`/`AdvancedRxFlowgraph`/`FftProbe`/
`PlutoSafety` als Python-Bibliothek**, statt nur `pluto-cli` als
Subprozess zu kapseln. Grund: Nur der direkte Import gibt Zugriff auf
`FftProbe.get_latest_row()` (Wasserfall) und auf die rohen Audio-Sinks/
-Quellen (Netzwerk-Audio) — beides sitzt unterhalb dessen, was `pluto-cli`
als Kommandozeilen-Oberfläche exponiert.

Konkret: `pluto-tx` wird als **Git-Submodule** (fest gepinnter Commit) in
`Web-TRX/vendor/pluto-tx` eingebunden — strikt lesend, nie verändert von
hier aus (deckt sich mit der bereits vereinbarten Read-only-Regel für das
Repo). Ein Versions-Bump ist ein bewusster, einzelner Schritt (Submodule-
Pointer aktualisieren), kein laufendes Editieren. `pluto-cli` selbst bleibt
zusätzlich nutzbar für einfache One-Shot-Admin-Aufgaben (z. B. Scan-Skripte),
ist aber nicht der Hauptpfad der Laufzeit-Kommunikation.

Lizenz-Hinweis: `pluto-tx` ist GPLv3 — Web-TRX' Backend (das es importiert)
muss GPLv3-kompatibel bleiben.

## 3. Zielarchitektur

```
Browser (SPA)                         Server
┌─────────────────────────┐           ┌──────────────────────────────────────┐
│ Wasserfall/Spektrum      │  WS bin   │  FastAPI/Uvicorn                     │
│ (WebGL Canvas)           │◄─────────►│  ├─ /ws  (control JSON + binary)     │
│ Audio (Web Audio API)    │  WS bin   │  │   ├─ Control-Handler (Connect,    │
│ Steuerpanels pro Modus   │  WS text  │  │   │   Scan, Mode-Select, PTT,     │
│ Login/Session            │  REST     │  │   │   Tune, Params)              │
└─────────────────────────┘           │  │   ├─ Spectrum-Bridge (FftProbe)   │
                                       │  │   └─ Audio-Bridge (RX→WS, WS→TX)  │
                                       │  ├─ Session-State-Machine            │
                                       │  │   (genau 1 aktive TX- ODER        │
                                       │  │    RX-Session je Gerät)           │
                                       │  ├─ Auth (Shared-Token/Passwort)     │
                                       │  ├─ TX-Aktivitätslog (SQLite/JSONL)  │
                                       │  └─ vendor/pluto-tx (Submodule,      │
                                       │      importiert wie pluto_cli)       │
                                       │        ├─ PlutoTxFlowgraph           │
                                       │        ├─ AdvancedRxFlowgraph        │
                                       │        ├─ PlutoSafety                │
                                       │        └─ FftProbe                   │
                                       └──────────────────────────────────────┘
                                                      │ libiio / SoapySDR / USB
                                                      ▼
                                          Pluto(+) / HackRF / RTL-SDR / AIOC
```

**Protokoll:** eine WebSocket-Verbindung pro Browser-Session.
- Text-Frames: JSON, Erweiterung des bestehenden `pluto-cli`-Event-Schemas
  um Steuerkommandos (`connect`, `scan`, `select_mode`, `tune`, `set_gain`,
  `ptt_on/off`, `set_power_ceiling`, `estop`, …) und deren Antworten/Events.
- Binär-Frames: 1-Byte-Typkennung + Payload — `0x01` Spektrum-/Wasserfall-
  Zeile (Float32Array dB-Werte, aus `FftProbe`), `0x02` Audio-Paket
  (Richtung RX→Browser), `0x03` Audio-Paket (Richtung Browser→TX, Mic).

**Audio-Codec:** Start mit PCM16 über WS (einfach, verifizierbar), Wechsel
auf Opus (WebCodecs/AudioWorklet-Encoder) sobald Bandbreite über VPN/
Internet ein Thema wird — bei Sprachmodi (FM/SSB/M17) mit potenziell
schwacher Anbindung lieber früh einplanen als spät nachrüsten.

**Backend-Threading:** GNU-Radio-Flowgraphs sind nicht async-nativ. Muster:
Flowgraph-Steuerung läuft in einem dedizierten Worker-Thread (analog zu
`pluto_cli/runtime.py`s Tick-Loop, nur dass `time.sleep()`-Ticks durch eine
Thread-sichere Queue ersetzt werden, die der asyncio-Eventloop des
WebSocket-Servers konsumiert). `FftProbe`s bestehendes Lock-/Generation-
Muster passt dafür unverändert.

**Auth:** kein Multi-User-Modell nötig — ein gemeinsames Server-Passwort/
Token reicht, da immer nur ein lizenzierter Betreiber zugreift. Trotzdem
sinnvoll: TLS/WSS-Terminierung per Reverse-Proxy (nginx/Caddy), und beim
Betrieb über Internet dringend VPN (WireGuard) statt offener Exposition —
hier geht es um eine Sendeanlage, nicht nur um Daten.

**TX-Aktivitätslog:** jede Aussendung (Zeit, Modus, Frequenz, Parameter,
Rufzeichen wo vorhanden) persistent protokollieren — sinnvoll für
Nachvollziehbarkeit einer ferngesteuerten Station, baut direkt auf den
ohnehin vorhandenen `keyed`/`unkeyed`/`pocsag_message`/`meshtastic_frame`-
Events auf.

## 4. Betriebsarten-Analyse für die Minimalversion

Pflicht laut Vorgabe: **FM, SSB, M17, POCSAG**. Analyse, warum genau diese
vier eine gute, bewusst kleine MVP-Grenze sind (nicht additiv "irgendwas
draufpacken"):

| Modus | Backend fertig? | Zusatz-Install | Braucht Audio-Stream | UI-Komplexität | Regulatorik |
|---|---|---|---|---|---|
| **FM** | ✅ ja | – | ja (bidirektional) | mittel (CTCSS/DCS-Feld) | niedrig |
| **SSB (USB/LSB)** | ✅ ja | – | ja (bidirektional) | niedrig (Sideband-Wahl) | niedrig |
| **M17** | ✅ ja | `install-m17.sh` | ja (bidirektional) + Metadaten (`m17_fields`) | mittel (Rufzeichenfelder, LSF-Anzeige) | niedrig |
| **POCSAG** | ✅ ja | – | **nein** (reines Text/Daten-Digimode) | niedrig (RIC/Text-Formular, Tabelle) | mittel (nur Amateurfunk-Bänder) |
| FreeDV 2020/2020B | ✅ ja | – (transitiv mit gnuradio) | ja | mittel | niedrig |
| RADE | ✅ ja | `install-rade.sh` | ja | mittel | niedrig |
| PSK31 / RTTY | ✅ ja | – | nein (Text) | niedrig | niedrig |
| Waterfall Writer | ✅ ja | – | nein, aber Wasserfall-Bild-Rendering | hoch (eigene Visualisierung) | niedrig |
| File Broadcast | ✅ ja | – | nein, Datei-Up-/Download | mittel | niedrig |
| Meshtastic / MeshCore | ✅ ja | `install-lora.sh` (+pip) | nein | hoch (Identität, Verschlüsselung, Kanäle, Bandplan-Warnhinweise) | hoch |
| Baseband (fldigi-Bridge) | ✅ ja | – | ja (roh) | niedrig | niedrig |

**Warum genau FM/SSB/M17/POCSAG als V1-Grenze — jenseits der reinen
Vorgabe:** Die vier zusammen zwingen dazu, alle drei fundamentalen
Datenpfade der Plattform einmal komplett durchzubauen, bevor die Breite
wächst:

1. **POCSAG zuerst als "Walking Skeleton"** — kein Audio, nur Text/Daten.
   Beweist Steuerkanal, Wasserfall-Pipeline, Session-State-Machine, Safety/
   E-STOP und das komplette Frontend-Grundgerüst, ohne dass gleichzeitig
   die schwierigste Baustelle (Audio-Streaming) mit hineinspielt. Kleinste
   sinnvolle Ende-zu-Ende-Strecke (RX-Tabelle + TX-Formular).
2. **FM** fügt die bidirektionale Echtzeit-Audio-Pipeline hinzu (Mic-Capture
   im Browser, Demod-Audio-Wiedergabe) — das aufwändigste neue Stück
   Infrastruktur im ganzen Projekt.
3. **SSB** ist danach nahezu geschenkt — gleiche Audio-Pipeline, nur
   Sideband-Auswahl on top.
4. **M17** beweist, dass sich die Audio-Pipeline auf Digital-Voice
   verallgemeinert (anderer Flowgraph-Innenteil, aber gleicher Transport)
   und bringt zusätzlich den Metadaten-Overlay-Fall (`m17_fields`) mit —
   relevant für spätere Modi wie Meshtastic/MeshCore, die ebenfalls
   strukturierte Empfangsdaten statt nur Audio liefern.

Alle vier sind zudem bereits vollständig serverseitig implementiert
(POCSAG/FM/SSB sogar ganz ohne Zusatz-Install), decken die drei
UI-Grundmuster ab, die alle weiteren Modi wiederverwenden werden
(Wasserfall+Tuning, Audio-Panel, Text/Tabellen-Digimode), und sind
regulatorisch harmlos genug, um sich in V1 nicht mit LoRa-Bandplan-
Sonderfällen aufzuhalten.

**Priorisierung danach** (jede Phase baut nur noch auf bereits bewährten
Mustern auf, kein neues Infrastruktur-Risiko mehr):

- **Phase 2** (kleiner Zusatzaufwand): PSK31, RTTY (identisches
  Text-Digimode-Muster wie POCSAG), Baseband/fldigi-Bridge (Audio-Pipeline
  bereits vorhanden).
- **Phase 3** (mittlerer Aufwand, optionale Installs/neue Widgets): FreeDV
  2020/2020B, RADE, Waterfall Writer (eigenes Wasserfall-Text-Rendering-
  Widget), File Broadcast (Upload/Download-UI, Fortschrittsanzeige aus
  vorhandenen `filebroadcast_*`-Events).
- **Phase 4** (höchster Aufwand): Meshtastic, MeshCore — LoRa-Zusatz-
  Install, Node-Identität/Schlüsselverwaltung in der UI, bandplan-
  abhängige Warnhinweise, Preset-Verwaltung.

## 5. Technologie-Empfehlung

- **Backend:** Python 3, FastAPI + Uvicorn (native WebSocket-Unterstützung,
  einfache REST-Endpunkte für Scan/Health/Login) — passt zur bestehenden
  Python-Codebasis, kein Sprachbruch beim Import von `pluto_tx`/
  `pluto_advanced_rx`.
- **Frontend:** TypeScript + Svelte(Kit) — schlank, gut geeignet für ein
  reaktives Echtzeit-Dashboard mit vielen kleinen State-Updates (Spektrum,
  Audio-Pegel, Digimode-Log); React wäre ebenso machbar, aber ohne
  zusätzlichen Nutzen für diesen Anwendungsfall.
- **Wasserfall/Spektrum:** eigenes WebGL-Canvas-Widget (Texture-Scroll für
  den Wasserfall, Canvas2D-Linie fürs Spektrum) nach dem Vorbild SDR++/
  OpenWebRX — keine serverseitige Bildkodierung, nur rohe dB-Zeilen über
  den Binärkanal.
- **Audio:** Web Audio API (`AudioWorklet`) für Aufnahme (Mic → TX) und
  Wiedergabe (RX → Lautsprecher); PCM16 zum Start, Opus als Ausbaustufe.
- **Persistenz:** SQLite (TX-Log, Konfiguration) — kein separater DB-Server
  nötig für Single-User-Betrieb.
- **Deployment:** systemd-Service auf dem SDR-Server, Reverse-Proxy für
  TLS/WSS, WireGuard-VPN empfohlen für Fernzugriff.

## 6. Repo-Struktur (Vorschlag)

```
Web-TRX/
├── backend/
│   └── web_trx/
│       ├── server.py          # FastAPI-App, WS-Endpunkt
│       ├── session.py         # globale TX/RX-Session-State-Machine
│       ├── spectrum.py        # FftProbe → WS-Binärstream
│       ├── audio.py           # RX-Audio → WS, WS → TX-Audioquelle
│       ├── control.py         # JSON-Steuerprotokoll (Connect/Scan/Mode/PTT/Tune)
│       ├── modes/             # Parameter-Schemas je Modus (spiegelt pluto-cli-Flags)
│       ├── auth.py
│       └── txlog.py
│   └── tests/
├── frontend/
│   └── src/                   # Svelte-App: Waterfall-Widget, Panels, Audio-Worklets
├── vendor/
│   └── pluto-tx/               # Git-Submodule, read-only, gepinnter Commit
├── deploy/
│   └── systemd/, reverse-proxy Beispielkonfig
└── docs/
    └── PROJECT_PLAN.md         # dieses Dokument
```

## 7. Meilensteine

| # | Meilenstein | Inhalt |
|---|---|---|
| M0 | Grundgerüst | Repo-Struktur, `pluto-tx` als Submodule, Backend-Skeleton (Health-Endpoint), Frontend-Skeleton (Build-Pipeline), CI (Lint/Tests) |
| M1 | Walking Skeleton — POCSAG | Login/Auth, Geräte-Scan/-Connect-UI, POCSAG RX (Log-Tabelle) + TX (RIC/Text-Formular), Session-State-Machine, NOTAUS-Grundgerüst, TX-Log |
| M2 | Wasserfall/Spektrum | `FftProbe`-Bridge, WS-Binärkanal, WebGL-Wasserfall-Widget mit Klick-zum-Tunen, Zoom/Pan, Floor/Ceiling, Fenster-Presets |
| M3 | FM/SSB-Audio | bidirektionale Audio-Pipeline (Mic-Capture → TX, Demod → Wiedergabe), PTT inkl. Latenzmessung, CTCSS/DCS, Power-Ceiling-UI |
| M4 | M17 | Digital-Voice über dieselbe Audio-Pipeline, Rufzeichenfelder, LSF-Metadaten-Anzeige, EOT-Handling |
| M5 | Härtung & Betrieb | Mehrgeräte-Auswahl, Reconnect-Handling, Fehlerdarstellung, Test über echten VPN-Link (Jitter, ggf. Opus-Umstieg), Deployment-Doku |
| M6+ | Phase 2–4 Modi | PSK31, RTTY, Baseband/fldigi → FreeDV, RADE, Waterfall Writer, File Broadcast → Meshtastic, MeshCore, jeweils inkrementell nach Abschnitt 4 |

## 8. Offene Entscheidungen / Risiken

- **Audio-Latenz über VPN/Internet**: PTT-Rückkopplung (Mic → Browser →
  WS → Server → SDR) hat unvermeidbar mehr Latenz als lokales ALSA. Für
  Sprachfunk mit Push-to-Talk unkritisch, sollte aber früh (M3) real
  gemessen werden statt spät anzunehmen.
- **`FftProbe`-Polling-Rate vs. Netzwerkbandbreite**: Zeilenrate/-größe
  müssen an die tatsächliche Client-Bandbreite (LAN vs. VPN/Internet)
  anpassbar sein, nicht fest verdrahtet.
- **Submodule-Pinning-Workflow**: wie/wann wird der `pluto-tx`-Submodule-
  Commit aktualisiert, wenn dort ein Bugfix landet? Sollte ein bewusster,
  dokumentierter Schritt sein, kein automatisches Tracking von `main`.

## 9. Aktueller Stand (gegen SimBackend, ohne Hardware verifiziert)

Umgesetzt und per Tests + echtem Chromium-Browser verifiziert (siehe
`docs/DEBUGGING.md`):

- Projekt-Grundgerüst (M0): Backend-/Frontend-Skeleton, `pluto-tx` als
  gepinntes Submodule, CI.
- Walking-Skeleton POCSAG-Roundtrip (M1-Vorgriff): Connect/Select-Mode/
  Tune/PTT/E-STOP komplett über WebSocket, inkl. Auto-Unkey.
- GUI-Politur (SDR++-Stil): dunkles Theme mit hellem Text in allen Feldern/
  Dropdowns, Slider für Floor/Ceiling/Zoom, PTT-Button mit visuellem
  Keyed-Zustand.
- Wasserfall-Interaktion (M2-Vorgriff): Klick-zum-Tunen, Zoom-Slider
  (aktuell client-seitiger Anzeige-Crop, siehe Kommentar in
  `Waterfall.svelte` -- echtes Zoom-FFT ist RX-Hardware-Arbeit).
- Modus-Formulare für alle vier MVP-Modi (FM inkl. CTCSS-Feld, SSB/LSB,
  M17 inkl. Rufzeichenfelder, POCSAG inkl. RIC/Text), Geräte-Scan-Anbindung.
- Audio-Pipeline (M3-Vorgriff, das ohne Hardware machbare Stück):
  `SimBackend` erzeugt einen Dauerton pro RX-Modus, Web Audio-Wiedergabe im
  Browser (`frontend/src/lib/audio.ts`); TX-Mikrofonaufnahme (Press-and-
  Hold-PTT bei Audio-Modi) wird erfasst und über den Binärkanal gesendet,
  vom Backend entgegengenommen. Bewusst mit `ScriptProcessorNode` (nicht
  `AudioWorklet`) gebaut, um ohne zusätzliche Worklet-Build-Schritte sofort
  verifizierbar zu sein -- Umstieg auf `AudioWorklet` ist Härtungsarbeit
  für M5.

Noch offen, bewusst nicht in diesem Schritt: Auth/Login (einfaches,
geteiltes Passwort reicht laut Setting), persistentes TX-Log,
`GnuRadioBackend` selbst (siehe `docs/DEBUGGING.md` -- blind ohne GNU
Radio geschrieben wäre riskanter als nützlich; wird verifiziert, sobald
eine Session mit echtem GNU Radio/Hardware zur Verfügung steht).
