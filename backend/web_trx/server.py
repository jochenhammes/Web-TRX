"""FastAPI app: one /health endpoint and one /ws endpoint carrying the
whole control/spectrum/audio protocol (see protocol.py). Which
SessionBackend is active is decided once, at process startup, by
WEB_TRX_BACKEND (see backend_for_name()) -- never per-connection: there is
only ever one physical session (see docs/PROJECT_PLAN.md section 3).
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from .session import SessionBackend, SessionManager
from .sim_backend import SimBackend


def backend_for_name(name: str) -> SessionBackend:
    if name == "sim":
        return SimBackend()
    if name == "gnuradio":
        # Deferred import: only touches vendor/pluto-tx (and therefore
        # GNU Radio/libiio) when actually selected -- keeps `sim` usable in
        # environments without those installed (this dev container, CI).
        from .radio_backend import GnuRadioBackend

        return GnuRadioBackend()
    raise ValueError(f"unknown WEB_TRX_BACKEND '{name}' (expected 'sim' or 'gnuradio')")


def create_app(backend: SessionBackend | None = None) -> FastAPI:
    backend = backend or backend_for_name(os.environ.get("WEB_TRX_BACKEND", "sim"))
    manager = SessionManager(backend)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        start = getattr(manager.backend, "start_background_tasks", None)
        if start is not None:
            start()
        yield
        await manager.backend.shutdown()

    app = FastAPI(title="Web-TRX", lifespan=lifespan)
    app.state.manager = manager

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "backend": manager.backend_name}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await manager.handle_connection(websocket)

    return app


app = create_app()
