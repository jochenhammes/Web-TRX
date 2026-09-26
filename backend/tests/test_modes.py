import importlib.util
from pathlib import Path

import pytest

from web_trx import modes

PLUTO_TX_CONFIG = Path(__file__).resolve().parents[2] / "vendor" / "pluto-tx" / "pluto_tx" / "config.py"


def test_fm_tx_defaults():
    assert modes.normalize_params("tx", "fm", {}) == {
        "deviation_hz": 2500.0, "preemphasis": True, "ctcss_hz": None,
    }


def test_fm_rx_defaults():
    assert modes.normalize_params("rx", "fm", {}) == {"deemphasis": True}


def test_fm_tx_wide_deviation_no_preemphasis():
    out = modes.normalize_params("tx", "fm", {"deviation_hz": 5000, "preemphasis": False})
    assert out["deviation_hz"] == 5000.0
    assert out["preemphasis"] is False


@pytest.mark.parametrize("bad", [3000, "5000", True, None])
def test_fm_tx_rejects_invalid_deviation(bad):
    with pytest.raises(ValueError):
        modes.normalize_params("tx", "fm", {"deviation_hz": bad})


def test_fm_tx_ctcss_snaps_to_standard_tone():
    assert modes.normalize_params("tx", "fm", {"ctcss_hz": 88.5})["ctcss_hz"] == 88.5
    assert modes.normalize_params("tx", "fm", {"ctcss_hz": 88.4999})["ctcss_hz"] == 88.5


@pytest.mark.parametrize("bad", [88.0, 1000, "88.5"])
def test_fm_tx_rejects_non_standard_ctcss(bad):
    with pytest.raises(ValueError):
        modes.normalize_params("tx", "fm", {"ctcss_hz": bad})


def test_fm_rejects_non_bool_switches():
    with pytest.raises(ValueError):
        modes.normalize_params("tx", "fm", {"preemphasis": "yes"})
    with pytest.raises(ValueError):
        modes.normalize_params("rx", "fm", {"deemphasis": 1})


def test_fm_rejects_unknown_keys():
    # A frontend typo must fail loudly instead of being silently ignored.
    with pytest.raises(ValueError):
        modes.normalize_params("tx", "fm", {"deviaton_hz": 5000})
    with pytest.raises(ValueError):
        modes.normalize_params("rx", "fm", {"deviation_hz": 5000})  # a TX-only option on RX


def test_other_modes_pass_through_unchanged():
    params = {"ric": 42, "text": "hi"}
    assert modes.normalize_params("tx", "pocsag", params) == params


@pytest.mark.skipif(not PLUTO_TX_CONFIG.exists(), reason="vendor/pluto-tx submodule not checked out")
def test_tables_match_pinned_pluto_tx():
    """Loaded by file path so the test needs no sys.path changes;
    pluto_tx/config.py is pure Python, no GNU Radio needed."""
    spec = importlib.util.spec_from_file_location("pluto_tx_config", PLUTO_TX_CONFIG)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    assert modes.FM_DEVIATION_CHOICES_HZ == tuple(cfg.FM_DEVIATION_CHOICES_HZ)
    assert modes.FM_DEVIATION_DEFAULT_HZ == cfg.FM_DEVIATION_HZ
    assert modes.FM_PREEMPHASIS_DEFAULT == cfg.FM_PREEMPH_DEFAULT
    assert modes.CTCSS_TONES_HZ == tuple(cfg.CTCSS_TONES_HZ)
