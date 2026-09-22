# Web-TRX

Einheitliche Weboberfläche für [`pluto-tx`/`pluto-advanced-rx`](https://github.com/jochenhammes/pluto-tx)
(Sende-/Empfangs-Software für ADALM-PLUTO, HackRF One und RTL-SDR). Ein
lizenzierter Funkamateur bedient die am Server angeschlossenen SDRs
vollständig über den Browser — Senden und Empfangen, inklusive Wasserfall/
Spektrum, Audio und Digimodes.

Projektplan (Architektur, Betriebsarten-Analyse, Meilensteine):
[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md).
Debug-/Teststrategie: [`docs/DEBUGGING.md`](docs/DEBUGGING.md).

## Struktur

```
backend/    FastAPI-Server (Python) -- SessionManager + SimBackend/GnuRadioBackend
frontend/   Svelte/TypeScript-SPA -- Wasserfall, Steuerpanels, Event-Log
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
Server verwendet: `sim` (Default, keine Hardware nötig) oder `gnuradio`
(nur auf einem System mit GNU Radio/libiio und angeschlossener SDR-
Hardware lauffähig, siehe `vendor/pluto-tx`).

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
`git submodule update --init`.

## Lizenz

[GPLv3](LICENSE) — wie `pluto-tx`, dessen Code das Backend importiert.
