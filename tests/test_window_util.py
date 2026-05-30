"""Unit tests for the pure geometry helper in window_util.

The Win32 calls (find/resize) need a live window and are validated manually; the
border-delta math is the part worth locking down here.
"""
from window_util import DEFAULT_PRESET, PRESETS_16_9, client_to_window_size


def test_client_to_window_size_preserves_border_delta():
    # A 1189x698 window wrapping a 1174x660 client has 15px/38px of chrome; to get
    # a 1600x900 client we add that same chrome back -> 1615x938.
    assert client_to_window_size(1189, 698, 1174, 660, 1600, 900) == (1615, 938)


def test_client_to_window_size_borderless_is_identity():
    # Borderless (client == window) -> target window equals target client.
    assert client_to_window_size(1600, 900, 1600, 900, 1280, 720) == (1280, 720)


def test_presets_are_all_16_9_and_default_exists():
    for w, h in PRESETS_16_9.values():
        assert abs(w / h - 16 / 9) < 0.01
    assert DEFAULT_PRESET in PRESETS_16_9
