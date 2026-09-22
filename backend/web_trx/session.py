"""Session-backend interface + the WebSocket-facing SessionManager.

Exactly one operator, exactly one physical device per direction (tx/rx) at
a time -- see docs/PROJECT_PLAN.md section 3. Two SessionBackend
implementations are planned: SimBackend (sim_backend.py, pure Python/numpy,
no GNU Radio/libiio needed -- what this dev container can actually run) and
a later GnuRadioBackend (radio_backend.py, only runs where vendor/pluto-tx's
GNU Radio/libiio dependencies are installed) that wires up
PlutoTxFlowgraph/AdvancedRxFlowgraph/FftProbe/PlutoSafety following the
exact pattern pluto_cli/runtime.py already proves works. SessionManager
itself never imports GNU Radio and is fully testable against SimBackend.
"""
from __future__ import annotations

import abc
import dataclasses
import logging
from collections.abc import Awaitable, Callable

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from . import protocol

logger = logging.getLogger("web_trx.session")

Direction = str  # "tx" | "rx"


class SessionError(Exception):
    """A refused request (bad mode/frequency/device, wrong state, ...) --
    becomes an 'error' event to the requesting client, never a raw
    traceback. Mirrors pluto-cli's own 'error' event (see
    vendor/pluto-tx/pluto_cli/README.md section 6)."""


@dataclasses.dataclass
class SpectrumFrame:
    row: np.ndarray  # float32 dB, low-to-high frequency
    center_hz: float
    span_hz: float
    generation: int


@dataclasses.dataclass
class AudioFrame:
    pcm16: bytes
    sample_rate_hz: int


EventSink = Callable[[str, dict], Awaitable[None]]
SpectrumSink = Callable[[SpectrumFrame], Awaitable[None]]
AudioSink = Callable[[AudioFrame], Awaitable[None]]


class SessionBackend(abc.ABC):
    """One radio session. `bind()` is called exactly once, before any other
    method, wiring the three sinks the backend uses to push events/data
    up to connected clients -- the backend never talks to a WebSocket
    directly, so it stays testable (and, for SimBackend, importable) with
    zero web/asyncio-server dependencies beyond these plain callables."""

    def bind(self, emit_event: EventSink, on_spectrum: SpectrumSink, on_audio: AudioSink) -> None:
        self._emit_event = emit_event
        self._on_spectrum = on_spectrum
        self._on_audio = on_audio

    @abc.abstractmethod
    async def scan(self, direction: Direction, device_type: str) -> dict[str, str]:
        """Returns {connection_string: human_label}."""

    @abc.abstractmethod
    async def connect(self, direction: Direction, device_type: str, connection: str) -> None:
        ...

    @abc.abstractmethod
    async def disconnect(self, direction: Direction) -> None:
        ...

    @abc.abstractmethod
    async def select_mode(self, direction: Direction, mode: str, params: dict) -> None:
        ...

    @abc.abstractmethod
    async def tune(self, direction: Direction, freq_hz: float) -> None:
        ...

    @abc.abstractmethod
    async def set_gain(self, direction: Direction, name: str, value: float) -> None:
        ...

    @abc.abstractmethod
    async def ptt(self, on: bool) -> None:
        ...

    @abc.abstractmethod
    async def estop(self) -> None:
        """Immediate, idempotent, must never raise -- mirrors PlutoSafety's
        force_safe_state() (vendor/pluto-tx/pluto_tx/safety.py)."""

    @abc.abstractmethod
    async def submit_tx_audio(self, frame: AudioFrame) -> None:
        """Microphone audio from the browser, consumed while PTT is on and
        the active TX mode is audio-based. Silently dropped otherwise."""

    @abc.abstractmethod
    def snapshot(self) -> dict:
        """Current session state for a newly-connected client's 'hello'
        event (device/mode/frequency/keyed per direction)."""

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Safe teardown, idempotent -- called on server shutdown."""


class SessionManager:
    """Owns the single SessionBackend instance and every connected
    WebSocket. Multiple browser tabs from the same operator MAY connect
    concurrently (all receive the same broadcast events/spectrum/audio,
    and any of them can issue requests) -- 'never more than one user' is a
    deployment assumption (single shared login, see docs/PROJECT_PLAN.md),
    not a second lock enforced here."""

    REQUESTS = (
        "scan", "connect", "disconnect", "select_mode", "tune", "set_gain",
        "ptt_on", "ptt_off", "estop",
    )

    def __init__(self, backend: SessionBackend):
        self.backend = backend
        self.backend.bind(self._emit_event, self._on_spectrum, self._on_audio)
        self._clients: set[WebSocket] = set()

    @property
    def backend_name(self) -> str:
        return type(self.backend).__name__

    async def handle_connection(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        try:
            await ws.send_json({"event": "hello", "backend": self.backend_name, **self.backend.snapshot()})
            while True:
                message = await ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                text = message.get("text")
                data = message.get("bytes")
                if text is not None:
                    await self._handle_text(text)
                elif data is not None:
                    await self._handle_binary(data)
        except WebSocketDisconnect:
            pass
        finally:
            self._clients.discard(ws)

    async def _handle_text(self, text: str) -> None:
        import json

        try:
            payload = json.loads(text)
        except ValueError:
            await self._emit_event("error", {"message": "malformed JSON request"})
            return
        request = payload.get("request")
        if request not in self.REQUESTS:
            await self._emit_event("error", {"message": f"unknown request '{request}'"})
            return
        params = {k: v for k, v in payload.items() if k != "request"}
        try:
            await self._dispatch(request, params)
        except SessionError as e:
            await self._emit_event("error", {"message": str(e), "request": request})
        except Exception as e:
            logger.exception("unhandled error handling request %r", request)
            await self._emit_event("error", {"message": f"internal error: {e}", "request": request})

    async def _dispatch(self, request: str, params: dict) -> None:
        b = self.backend
        if request == "scan":
            devices = await b.scan(params["direction"], params["device_type"])
            await self._emit_event("scanned", {"direction": params["direction"], "devices": devices})
        elif request == "connect":
            await b.connect(params["direction"], params["device_type"], params.get("connection") or "")
            await self._emit_event("connected", {"direction": params["direction"]})
        elif request == "disconnect":
            await b.disconnect(params["direction"])
            await self._emit_event("disconnected", {"direction": params["direction"]})
        elif request == "select_mode":
            await b.select_mode(params["direction"], params["mode"], params.get("params") or {})
            await self._emit_event("mode", {"direction": params["direction"], "mode": params["mode"]})
        elif request == "tune":
            await b.tune(params["direction"], float(params["freq_hz"]))
            await self._emit_event("tuned", {"direction": params["direction"], "freq_hz": params["freq_hz"]})
        elif request == "set_gain":
            await b.set_gain(params["direction"], params["name"], float(params["value"]))
        elif request == "ptt_on":
            await b.ptt(True)
        elif request == "ptt_off":
            await b.ptt(False)
        elif request == "estop":
            await b.estop()

    async def _handle_binary(self, data: bytes) -> None:
        if not data or protocol.peek_frame_type(data) != protocol.BinaryFrameType.TX_AUDIO:
            return
        sample_rate_hz, pcm16 = protocol.decode_tx_audio(data)
        await self.backend.submit_tx_audio(AudioFrame(pcm16=pcm16, sample_rate_hz=sample_rate_hz))

    async def _emit_event(self, name: str, fields: dict) -> None:
        await self._broadcast_json({"event": name, **fields})

    async def _on_spectrum(self, frame: SpectrumFrame) -> None:
        payload = protocol.encode_spectrum_row(frame.row, frame.center_hz, frame.span_hz, frame.generation)
        await self._broadcast_bytes(payload)

    async def _on_audio(self, frame: AudioFrame) -> None:
        payload = protocol.encode_rx_audio(frame.pcm16, frame.sample_rate_hz)
        await self._broadcast_bytes(payload)

    async def _broadcast_json(self, payload: dict) -> None:
        for ws in list(self._clients):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001 -- a dead client must not break the others
                self._clients.discard(ws)

    async def _broadcast_bytes(self, payload: bytes) -> None:
        for ws in list(self._clients):
            try:
                await ws.send_bytes(payload)
            except Exception:  # noqa: BLE001
                self._clients.discard(ws)
