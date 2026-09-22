"""End-to-end test of the whole control/spectrum protocol through the real
FastAPI WebSocket layer, against SimBackend -- the second layer of the
debugging strategy from docs/PROJECT_PLAN.md (no browser, no asyncio
subtleties left to chance, still no GNU Radio/hardware required)."""
from fastapi.testclient import TestClient

from web_trx import protocol
from web_trx.server import create_app
from web_trx.sim_backend import SimBackend


def make_client() -> TestClient:
    """Returns an un-entered TestClient -- every test uses `with
    make_client() as client:` so the ASGI lifespan (startup/shutdown, see
    server.py) actually runs on the same event loop that serves the
    WebSocket, which is what makes SimBackend's background spectrum task
    (asyncio.create_task in start_background_tasks()) work at all."""
    app = create_app(SimBackend())
    return TestClient(app)


def test_health():
    with make_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "backend": "SimBackend"}


def test_hello_on_connect():
    with make_client() as client, client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["event"] == "hello"
        assert hello["backend"] == "SimBackend"
        assert hello["tx"]["mode"] is None


def test_full_pocsag_round_trip_over_ws():
    with make_client() as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()  # hello

        ws.send_json({"request": "connect", "direction": "tx", "device_type": "sim"})
        assert ws.receive_json()["event"] == "connected"

        ws.send_json({"request": "select_mode", "direction": "tx", "mode": "pocsag",
                      "params": {"ric": 99, "text": "DE DA2JH"}})
        assert ws.receive_json()["event"] == "mode"

        ws.send_json({"request": "ptt_on"})
        assert ws.receive_json()["event"] == "keyed"
        pocsag_event = ws.receive_json()
        assert pocsag_event["event"] == "pocsag_message"
        assert pocsag_event["ric"] == 99
        assert pocsag_event["text"] == "DE DA2JH"
        assert ws.receive_json()["event"] == "unkeyed"  # simulated auto-hold, see SimBackend.ptt()


def test_unknown_request_becomes_error_event_not_a_crash():
    with make_client() as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()  # hello
        ws.send_json({"request": "nonsense"})
        err = ws.receive_json()
        assert err["event"] == "error"


def test_refused_request_becomes_error_event():
    with make_client() as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()  # hello
        ws.send_json({"request": "ptt_on"})  # tx never connected
        err = ws.receive_json()
        assert err["event"] == "error"
        assert "not connected" in err["message"] or "no mode" in err["message"]


def test_spectrum_binary_frame_after_rx_connect():
    with make_client() as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()  # hello
        ws.send_json({"request": "connect", "direction": "rx", "device_type": "sim"})
        assert ws.receive_json()["event"] == "connected"

        raw = ws.receive_bytes()
        assert protocol.peek_frame_type(raw) == protocol.BinaryFrameType.SPECTRUM_ROW
        decoded = protocol.decode_spectrum_row(raw)
        assert decoded["row"].shape == (2048,)
