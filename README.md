# Web-TRX

Einheitliche Weboberfläche für [`pluto-tx`/`pluto-advanced-rx`](https://github.com/jochenhammes/pluto-tx)
(Sende-/Empfangs-Software für ADALM-PLUTO, HackRF One und RTL-SDR). Ein
lizenzierter Funkamateur bedient die am Server angeschlossenen SDRs
vollständig über den Browser — Senden und Empfangen, inklusive Wasserfall/
Spektrum, Audio und Digimodes.

Projektplan (Architektur, Betriebsarten-Analyse, Meilensteine):
[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md).
Debug-/Teststrategie: [`docs/DEBUGGING.md`](docs/DEBUGGING.md).

## Aktueller Stand

Die komplette Web-Seite läuft — **aber noch ohne echte Hardware**: das
einzige Backend ist bisher `SimBackend`, ein Simulator ohne GNU Radio
(synthetisches Spektrum, Testton statt Demodulation). Alles unten ist per
Tests (56 im Backend) und im echten Browser gegen den Simulator geprüft.

**Fertig**
- WebSocket-Protokoll (JSON-Steuerung + Binärkanal für Spektrum und Audio),
  Session-Zustandsautomat mit PTT, Auto-Unkey bei POCSAG und NOTAUS
- Login mit geteiltem Passwort (Session-Cookie), WebSocket ohne Login gesperrt
- Persistentes TX-Log (SQLite) jeder Aussendung, TX-Verlauf im Frontend
- Oberfläche im SDR++-Stil: Wasserfall + Spektrum mit Klick-zum-Tunen,
  Zoom-, Floor- und Ceiling-Slider, Geräte-Scan, Verbinden/Trennen
- Modi FM, SSB (USB/LSB), M17, POCSAG mit ihren Parametern: FM mit Hub
  2,5/5 kHz, Pre-/De-Emphasis und CTCSS-Standardtönen, M17 mit Rufzeichen,
  POCSAG mit RIC/Text — zentral geprüft in `backend/web_trx/modes.py`
- Audio-Pipeline im Browser: RX-Wiedergabe, TX-Mikrofon bei gedrückter PTT

**Offen**
- `GnuRadioBackend`: die Anbindung an die echten pluto-tx-Flowgraphs und
  damit an Pluto/HackRF/RTL-SDR. Braucht einen Rechner mit GNU Radio und
  angeschlossener Hardware (siehe `docs/DEBUGGING.md`)
- Echtes Zoom-FFT (derzeit nur Ausschnitt der Anzeige), `AudioWorklet`
  statt `ScriptProcessorNode`, Opus über langsame Links
- Härtung (Reconnect, Mehrgeräte, Fehleranzeige), Deployment (systemd,
  TLS-Reverse-Proxy, VPN)
- Weitere Modi (PSK31, RTTY, FreeDV, RADE, Meshtastic, …)

Details und Begründungen: [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md),
Abschnitt 9. Gepinnte pluto-tx-Version: `c45531d`.

## Struktur

```
backend/    FastAPI-Server (Python) -- SessionManager, SimBackend, Auth, TX-Log, Modus-Parameter
frontend/   Svelte/TypeScript-SPA -- Login, Wasserfall, Steuerpanels, TX-Verlauf, Event-Log
vendor/     Git-Submodule: pluto-tx (read-only, gepinnter Commit)
docs/       Projektplan, Debugging-Strategie
```

## Backend (Entwicklung)

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m pytest              # läuft komplett ohne GNU Radio/Hardware, siehe docs/DEBUGGING.md
uvicorn web_trx.server:create_app --factory --reload --port 8321
```

`WEB_TRX_BACKEND` steuert, welche `SessionBackend`-Implementierung der
Server verwendet: `sim` (Default, keine Hardware nötig). `gnuradio` ist
vorgesehen, aber **noch nicht implementiert** — der Server startet damit
derzeit nicht (siehe „Aktueller Stand“).

**Login:** ein geteiltes Passwort reicht (immer nur ein Betreiber, siehe
`docs/PROJECT_PLAN.md` Abschnitt 1). `WEB_TRX_PASSWORD` setzen, sonst
generiert der Server beim Start eines und gibt es auf stderr aus (wie bei
Jupyter). Hinter TLS zusätzlich `WEB_TRX_COOKIE_SECURE=true` setzen.
`WEB_TRX_TX_LOG_PATH` (Default `web_trx_tx_log.sqlite3` im Arbeits-
verzeichnis) bestimmt, wo das persistente TX-Aktivitätslog liegt.

## Frontend (Entwicklung)

```bash
cd frontend
npm install
npm run dev      # erwartet das Backend auf 127.0.0.1:8321, siehe vite.config.ts
npm run check    # Typecheck
npm run build
```

## Submodule

`vendor/pluto-tx` ist ein Git-Submodule auf einem fest gepinnten Commit —
**read-only**, nie von hier aus verändert. Ein Versions-Bump ist ein
bewusster Einzelschritt:

```bash
git -C vendor/pluto-tx fetch
git -C vendor/pluto-tx checkout <neuer-commit>
git add vendor/pluto-tx
git commit -m "vendor/pluto-tx: bump to <neuer-commit>"
```

Beim Klonen: `git clone --recurse-submodules ...` bzw. nachträglich
`git submodule update --init`. Nach jedem `git pull` zusätzlich
`git submodule update`, sonst bleibt `vendor/pluto-tx` auf dem alten Stand.

## Lizenz

[GPLv3](LICENSE) — wie `pluto-tx`, dessen Code das Backend importieren wird.
