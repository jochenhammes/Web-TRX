"""Per-mode parameter schemas -- the web counterpart of pluto-cli's per-mode
flags (vendor/pluto-tx/pluto_cli/README.md section 4). SessionManager runs
every select_mode request through normalize_params() once, at the protocol
boundary, so each SessionBackend receives the same checked dict with all
defaults filled in: SimBackend just stores it, GnuRadioBackend will map it
onto pluto-tx's live setters (set_fm_deviation(), set_fm_preemphasis(),
set_subtone("ctcss", ...), set_fm_deemphasis() -- none needs a rebuild).

The value tables mirror vendor/pluto-tx's pluto_tx/config.py;
tests/test_modes.py checks them against the pinned submodule, so a bump
that changes them fails loudly instead of drifting silently. Raises
ValueError (SessionManager turns it into an 'error' event).
"""
from __future__ import annotations

FM_DEVIATION_CHOICES_HZ = (2500.0, 5000.0)
FM_DEVIATION_DEFAULT_HZ = 2500.0
FM_PREEMPHASIS_DEFAULT = True
FM_DEEMPHASIS_DEFAULT = True
CTCSS_TONES_HZ = (
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8, 97.4, 100.0, 103.5, 107.2,
    110.9, 114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2,
    165.5, 167.9, 171.3, 173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5, 203.5,
    206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3, 254.1,
)


def client_options() -> dict:
    """Choice lists the frontend builds its dropdowns from (sent in the
    'hello' event) -- keeps these tables in exactly one place."""
    return {
        "fm": {
            "deviation_choices_hz": list(FM_DEVIATION_CHOICES_HZ),
            "deviation_default_hz": FM_DEVIATION_DEFAULT_HZ,
            "preemphasis_default": FM_PREEMPHASIS_DEFAULT,
            "deemphasis_default": FM_DEEMPHASIS_DEFAULT,
            "ctcss_tones_hz": list(CTCSS_TONES_HZ),
        },
    }


def normalize_params(direction: str, mode: str, params: dict) -> dict:
    if mode == "fm":
        return _fm_tx(params) if direction == "tx" else _fm_rx(params)
    return dict(params)


def _fm_tx(params: dict) -> dict:
    _reject_unknown(params, {"deviation_hz", "preemphasis", "ctcss_hz"})
    deviation = params.get("deviation_hz", FM_DEVIATION_DEFAULT_HZ)
    if not _is_number(deviation) or float(deviation) not in FM_DEVIATION_CHOICES_HZ:
        raise ValueError(f"fm: deviation_hz must be one of {FM_DEVIATION_CHOICES_HZ}, got {deviation!r}")
    ctcss = params.get("ctcss_hz")
    if ctcss is not None:
        if not _is_number(ctcss):
            raise ValueError(f"fm: ctcss_hz must be a number or null, got {ctcss!r}")
        # Match within rounding so 88.5 / 88.50 / 88.4999 from a UI all land on the standard tone.
        match = next((t for t in CTCSS_TONES_HZ if abs(t - float(ctcss)) < 0.05), None)
        if match is None:
            raise ValueError(f"fm: {ctcss} Hz is not a standard CTCSS tone")
        ctcss = match
    return {
        "deviation_hz": float(deviation),
        "preemphasis": _bool(params, "preemphasis", FM_PREEMPHASIS_DEFAULT),
        "ctcss_hz": ctcss,
    }


def _fm_rx(params: dict) -> dict:
    _reject_unknown(params, {"deemphasis"})
    return {"deemphasis": _bool(params, "deemphasis", FM_DEEMPHASIS_DEFAULT)}


def _reject_unknown(params: dict, allowed: set[str]) -> None:
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(f"fm: unknown parameter(s) {sorted(unknown)}")


def _bool(params: dict, key: str, default: bool) -> bool:
    value = params.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"fm: {key} must be true or false, got {value!r}")  # noqa: TRY004 -- one error type for all bad client input
    return value


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
