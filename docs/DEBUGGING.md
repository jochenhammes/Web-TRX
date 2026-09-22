# Debug-/Teststrategie

Zwei `SessionBackend`-Implementierungen (`backend/web_trx/session.py`)
tragen den gesamten Stack, je nachdem, was gerade verfügbar ist:

## 1. `SimBackend` — überall lauffähig, kein GNU Radio/keine Hardware nötig

`backend/web_trx/sim_backend.py`: reines Python/NumPy, erzeugt plausibel
aussehende (aber **nicht physikalisch korrekte**) Spektren und dasselbe
Event-Vokabular, das der echte Flowgraph später auch emittiert (`keyed`,
`pocsag_message`, `estop`, …). Damit lässt sich entwickeln/testen, ohne
je an einen SDR heranzukommen:

- **Unit-Tests** direkt gegen `SimBackend` (`backend/tests/test_sim_backend.py`)
  — Zustandsautomat, Safety/E-STOP, Moduswechsel-Validierung.
- **Protokoll-Tests** über die echte FastAPI-WebSocket-Schicht
  (`backend/tests/test_server_ws.py`), inkl. Binärkanal (Spektrum-Zeilen).
- **Frontend-Tests im echten Browser** gegen einen laufenden
  `uvicorn`-Prozess mit `SimBackend` — Chromium ist in dieser
  Cloud-Umgebung vorinstalliert (`/opt/pw-browsers/chromium`), ansteuerbar
  z. B. über `playwright-core` mit `executablePath` darauf gesetzt.

```bash
cd backend && . .venv/bin/activate && python -m pytest
uvicorn web_trx.server:create_app --factory --port 8321  # Terminal 1
cd frontend && npm run dev                       # Terminal 2, Proxy auf :8321
```

Alles oben Genannte läuft in jeder Umgebung ohne GNU Radio/libiio/SDR —
inklusive dieser Cloud-Session selbst (hier sind beide nicht installiert,
siehe unten).

## 2. `GnuRadioBackend` — nur auf einem System mit GNU Radio + Hardware

Verdrahtet `PlutoTxFlowgraph`/`AdvancedRxFlowgraph`/`FftProbe`/
`PlutoSafety` aus `vendor/pluto-tx`, nach dem Muster von
`vendor/pluto-tx/pluto_cli/runtime.py`. Läuft nur dort, wo
`vendor/pluto-tx/install.sh` bereits gelaufen ist (echter Radio-Server).
Bewusst so dünn wie möglich gehalten — die eigentliche Komplexität
(Protokoll, Zustandsautomat, UI, Audio-Framing) ist bereits gegen
`SimBackend` durchgetestet, bevor sie auf echte Hardware trifft.

**Diese Cloud-Session hat kein GNU Radio, kein libiio und keine
SDR-Hardware** (geprüft: `python3 -c "import gnuradio"` schlägt fehl) —
`GnuRadioBackend` kann und soll hier nicht getestet werden.

## Hardware-in-the-Loop

Für den finalen Test gegen echte Hardware: eigene Claude-Code-Session auf
dem Radio-Server (mit GNU Radio + Hardware-Zugriff), einbindbar per
`SendMessage`, sobald sie eingerichtet ist. Näheres siehe Absprache in der
Projekt-Konversation; wird relevant ab Meilenstein M2/M3
(Wasserfall/Audio, siehe `docs/PROJECT_PLAN.md`).

## Bekannte Stolpersteine (bereits gefunden & gefixt)

**Self-Cancellation-Deadlock.** `SimBackend`s POCSAG-Auto-Unkey-Task rief
am Ende `ptt(False)` auf, was wiederum versuchte, genau diese (sich
selbst gerade ausführende) Task zu canceln — die `unkeyed`-Event-
Auslieferung brach dadurch mitten im `await` ab, das Backend hing
scheinbar (siehe Kommentar in `sim_backend.py`s `_auto_unkey_after()`).
Gefunden über einen `faulthandler`-Traceback-Dump auf einen künstlichen
Timeout, nicht durch Raten — bei ähnlichen "hängt ohne Fehlermeldung"-
Fällen mit Fire-and-forget-`asyncio.create_task`s ist das der schnellste
Weg zur Ursache.

**Seiteneffekte beim reinen Import.** `server.py` hatte lange ein
Modul-Level `app = create_app()` (üblich, damit `uvicorn
web_trx.server:app` die App findet). Das führte dazu, dass jeder Import
des Moduls — auch nur für `from web_trx.server import create_app` in
Tests, auch nur beim Pytest-Collection-Schritt — eine komplette
zusätzliche Default-App baute: TX-Log-SQLite-Datei wurde ins
Arbeitsverzeichnis geschrieben, ein zufälliges Passwort generiert und auf
stderr ausgegeben. Gefunden, weil ein Test unerwartet die
Passwort-Generierungsmeldung in `capsys`-Output zeigte, obwohl der Test
explizit ein eigenes `AuthManager(password=...)` übergab. Fix: kein
Modul-Level `app` mehr, stattdessen `uvicorn web_trx.server:create_app
--factory` (siehe README). Allgemeine Lehre: ein Modul, das auch als
Bibliothek importiert wird (hier: für `create_app`), darf beim bloßen
Import keine Seiteneffekte (Dateien schreiben, Netzwerk, Zufallswerte
ausgeben) auslösen.
