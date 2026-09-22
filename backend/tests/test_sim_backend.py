"""Unit tests against SimBackend directly (no WebSocket, no asyncio server)
-- the fast layer of the debugging strategy from docs/PROJECT_PLAN.md: pure
Python/numpy, no GNU Radio/libiio required, runs anywhere including this
dev container and CI."""
import numpy as np
import pytest

from web_trx.session import SessionError
from web_trx.sim_backend import SimBackend


def make_backend():
    b = SimBackend()
    events = []

    async def emit_event(name, fields):
        events.append((name, fields))

    async def on_spectrum(frame):
        pass

    async def on_audio(frame):
        pass

    b.bind(emit_event, on_spectrum, on_audio)
    return b, events


@pytest.mark.asyncio
async def test_connect_then_select_mode_then_tune():
    b, _events = make_backend()
    await b.connect("rx", "sim", "")
    await b.select_mode("rx", "fm", {})
    await b.tune("rx", 145_500_000.0)
    assert b.rx.mode == "fm"
    assert b.rx.freq_hz == 145_500_000.0


@pytest.mark.asyncio
async def test_select_mode_before_connect_is_refused():
    b, _events = make_backend()
    with pytest.raises(SessionError):
        await b.select_mode("rx", "fm", {})


@pytest.mark.asyncio
async def test_unsupported_mode_is_refused():
    b, _events = make_backend()
    await b.connect("tx", "sim", "")
    with pytest.raises(SessionError):
        await b.select_mode("tx", "not-a-real-mode", {})


@pytest.mark.asyncio
async def test_ptt_without_tx_mode_is_refused():
    b, _events = make_backend()
    with pytest.raises(SessionError):
        await b.ptt(True)


@pytest.mark.asyncio
async def test_fm_ptt_on_off_emits_keyed_unkeyed():
    b, events = make_backend()
    await b.connect("tx", "sim", "")
    await b.select_mode("tx", "fm", {})
    await b.ptt(True)
    assert b.keyed is True
    await b.ptt(False)
    assert b.keyed is False
    assert ("keyed", {"mode": "fm"}) in events
    assert ("unkeyed", {"mode": "fm"}) in events


@pytest.mark.asyncio
async def test_pocsag_ptt_auto_unkeys_and_emits_message(): # walking-skeleton mode, see PROJECT_PLAN.md
    b, events = make_backend()
    await b.connect("tx", "sim", "")
    await b.select_mode("tx", "pocsag", {"ric": 42, "text": "hi"})
    await b.ptt(True)
    assert any(name == "pocsag_message" and fields["ric"] == 42 for name, fields in events)
    assert b.keyed is True
    await b._pocsag_unkey_task  # await the simulated hold instead of sleeping in the test
    assert b.keyed is False


@pytest.mark.asyncio
async def test_estop_forces_unkey_even_mid_pocsag():
    b, events = make_backend()
    await b.connect("tx", "sim", "")
    await b.select_mode("tx", "pocsag", {"ric": 1, "text": "x"})
    await b.ptt(True)
    assert b.keyed is True
    await b.estop()
    assert b.keyed is False
    assert ("estop", {}) in events


@pytest.mark.asyncio
async def test_estop_is_idempotent_when_not_keyed():
    b, _events = make_backend()
    await b.estop()
    await b.estop()  # must not raise


@pytest.mark.asyncio
async def test_spectrum_row_shape_and_dtype():
    b, _events = make_backend()
    await b.connect("rx", "sim", "")
    row = b._synthetic_row()
    assert row.dtype == np.float32
    assert row.shape == (2048,)
    assert np.all(np.isfinite(row))


@pytest.mark.asyncio
async def test_snapshot_reflects_state():
    b, _events = make_backend()
    await b.connect("rx", "sim", "")
    await b.select_mode("rx", "ssb", {})
    snap = b.snapshot()
    assert snap["rx"]["mode"] == "ssb"
    assert snap["tx"]["mode"] is None
