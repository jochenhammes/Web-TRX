"""Pure-Python/numpy session backend -- no GNU Radio, no libiio, no
hardware. Exists so the entire session-manager/WebSocket/frontend stack is
developable and testable in environments that don't have GNU Radio
installed (this dev container, CI) and so the WS wire protocol gets
exercised end-to-end before the real GnuRadioBackend exists. Generates
plausible-looking but NOT physically meaningful spectra -- it proves the
pipes carry data correctly, it does not model real RF propagation.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import numpy as np

from .session import AudioFrame, SessionBackend, SessionError, SpectrumFrame

FFT_SIZE = 2048
SPECTRUM_RATE_HZ = 20.0
DEFAULT_SPAN_HZ = 2_500_000.0

# Mirrors the MVP mode set from docs/PROJECT_PLAN.md section 4 (lsb kept
# alongside ssb the same way vendor/pluto-tx exposes both as separate
# sideband-fixed modes rather than one mode with a sideband flag).
TX_MODES = ("fm", "ssb", "lsb", "m17", "pocsag")
RX_MODES = ("fm", "ssb", "lsb", "m17", "pocsag")
DEVICE_TYPES = ("sim",)


@dataclass
class _DirectionState:
    device_type: str | None = None
    connection: str | None = None
    mode: str | None = None
    mode_params: dict = field(default_factory=dict)
    freq_hz: float = 432_500_000.0
    gains: dict = field(default_factory=dict)


class SimBackend(SessionBackend):
    def __init__(self):
        self.tx = _DirectionState()
        self.rx = _DirectionState()
        self.keyed = False
        self._generation = 0
        self._rng = np.random.default_rng(1)
        self._spectrum_task: asyncio.Task | None = None
        self._pocsag_unkey_task: asyncio.Task | None = None

    def _state(self, direction: str) -> _DirectionState:
        if direction == "tx":
            return self.tx
        if direction == "rx":
            return self.rx
        raise SessionError(f"unknown direction '{direction}'")

    async def scan(self, direction: str, device_type: str) -> dict[str, str]:
        if device_type not in DEVICE_TYPES:
            raise SessionError(f"unknown device type '{device_type}'")
        return {"sim:0": "Simulated SDR (no hardware)"}

    async def connect(self, direction: str, device_type: str, connection: str) -> None:
        if device_type not in DEVICE_TYPES:
            raise SessionError(f"unknown device type '{device_type}'")
        st = self._state(direction)
        st.device_type = device_type
        st.connection = connection or "sim:0"

    async def disconnect(self, direction: str) -> None:
        if direction == "tx" and self.keyed:
            await self.ptt(False)
        st = self._state(direction)
        st.device_type = None
        st.connection = None
        st.mode = None

    async def select_mode(self, direction: str, mode: str, params: dict) -> None:
        st = self._state(direction)
        if st.connection is None:
            raise SessionError(f"{direction}: not connected")
        allowed = TX_MODES if direction == "tx" else RX_MODES
        if mode not in allowed:
            raise SessionError(f"unsupported {direction} mode '{mode}'")
        st.mode = mode
        st.mode_params = params

    async def tune(self, direction: str, freq_hz: float) -> None:
        st = self._state(direction)
        if st.connection is None:
            raise SessionError(f"{direction}: not connected")
        st.freq_hz = freq_hz

    async def set_gain(self, direction: str, name: str, value: float) -> None:
        self._state(direction).gains[name] = value

    async def ptt(self, on: bool) -> None:
        if on:
            if self.tx.connection is None or self.tx.mode is None:
                raise SessionError("tx: not connected or no mode selected")
            if self.keyed:
                return
            self.keyed = True
            await self._emit_event("keyed", {"mode": self.tx.mode})
            if self.tx.mode == "pocsag":
                await self._emit_event("pocsag_message", {
                    "ric": self.tx.mode_params.get("ric", 1234567),
                    "text": self.tx.mode_params.get("text", ""),
                })
                # POCSAG is one-shot in the real flowgraph too (see
                # vendor/pluto-tx pluto_cli/README.md section 4) -- a fixed
                # short hold stands in for computing real airtime here.
                self._pocsag_unkey_task = asyncio.create_task(self._auto_unkey_after(1.5))
        else:
            if self._pocsag_unkey_task is not None:
                self._pocsag_unkey_task.cancel()
                self._pocsag_unkey_task = None
            if not self.keyed:
                return
            self.keyed = False
            await self._emit_event("unkeyed", {"mode": self.tx.mode})

    async def _auto_unkey_after(self, seconds: float) -> None:
        """Runs as self._pocsag_unkey_task. Must clear that reference
        *before* calling ptt(False) below -- otherwise ptt(False) finds
        self._pocsag_unkey_task still pointing at the task currently
        executing this very coroutine and cancels itself, which raises
        CancelledError out of the await self._emit_event("unkeyed", ...)
        inside ptt(False) and silently drops the event (caught by the
        except clause here). An externally-triggered cancel (ptt_off /
        estop while still sleeping) still works exactly as before: this
        coroutine is torn down at the `await asyncio.sleep()` line, never
        reaching the ptt(False) call at all."""
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        self._pocsag_unkey_task = None
        await self.ptt(False)

    async def estop(self) -> None:
        if self._pocsag_unkey_task is not None:
            self._pocsag_unkey_task.cancel()
            self._pocsag_unkey_task = None
        was_keyed = self.keyed
        self.keyed = False
        await self._emit_event("estop", {})
        if was_keyed:
            await self._emit_event("unkeyed", {"mode": self.tx.mode})

    async def submit_tx_audio(self, frame: AudioFrame) -> None:
        pass  # SimBackend never transmits real audio -- channel only needs to be exercised, see tests.

    def snapshot(self) -> dict:
        return {
            "tx": _snapshot_direction(self.tx, self.keyed),
            "rx": _snapshot_direction(self.rx, False),
        }

    async def shutdown(self) -> None:
        if self._spectrum_task is not None:
            self._spectrum_task.cancel()
        if self._pocsag_unkey_task is not None:
            self._pocsag_unkey_task.cancel()
        self.keyed = False

    # -- Background spectrum generator. Not part of SessionBackend's ABC
    # (no control request triggers it) -- exercises the binary WS channel
    # continuously once RX is connected, exactly like a real FftProbe feeds
    # a waterfall independent of control-plane activity (see
    # vendor/pluto-tx pluto_advanced_rx/fft_probe.py). --

    def start_background_tasks(self) -> None:
        if self._spectrum_task is None:
            self._spectrum_task = asyncio.create_task(self._spectrum_loop())

    async def _spectrum_loop(self) -> None:
        period_s = 1.0 / SPECTRUM_RATE_HZ
        while True:
            await asyncio.sleep(period_s)
            if self.rx.connection is None:
                continue
            self._generation += 1
            await self._on_spectrum(SpectrumFrame(
                row=self._synthetic_row(), center_hz=self.rx.freq_hz, span_hz=DEFAULT_SPAN_HZ,
                generation=self._generation,
            ))

    def _synthetic_row(self) -> np.ndarray:
        """NOT a physical simulation -- a fixed noise floor plus a few fake
        carrier bumps at relative bin offsets, and (while keyed) a bump at
        TX's offset from RX center if it falls inside the displayed span.
        Only meant to give the waterfall widget something plausible-looking
        to render while developing against SimBackend."""
        row = -95.0 + self._rng.normal(0.0, 2.5, FFT_SIZE).astype(np.float32)
        for rel_bin, height in ((-600, 18.0), (-150, 10.0), (300, 14.0), (700, 8.0)):
            idx = FFT_SIZE // 2 + rel_bin
            if 0 <= idx < FFT_SIZE:
                row[max(0, idx - 3):idx + 4] += height
        if self.keyed and self.tx.connection is not None:
            offset_hz = self.tx.freq_hz - self.rx.freq_hz
            bin_width_hz = DEFAULT_SPAN_HZ / FFT_SIZE
            idx = int(FFT_SIZE // 2 + offset_hz / bin_width_hz)
            if 0 <= idx < FFT_SIZE:
                row[max(0, idx - 4):idx + 5] += 45.0
        return row


def _snapshot_direction(st: _DirectionState, keyed: bool) -> dict:
    return {
        "device_type": st.device_type,
        "connection": st.connection,
        "mode": st.mode,
        "freq_hz": st.freq_hz,
        "gains": dict(st.gains),
        "keyed": keyed,
    }
