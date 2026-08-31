"""Parser tests against output captured from real hardware.

The fixture is a verbatim `iw list` from an Intel AX201 (iwlwifi) under a
world regulatory domain - the configuration that makes every existing
hotspot tool fail silently.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hotspotd import caps  # noqa: E402

FIX = pathlib.Path(__file__).parent / "fixtures"
AX201 = caps.parse_iw_list((FIX / "iw_list_ax201.txt").read_text())


def test_ap_mode_detected():
    assert AX201.supports_ap
    assert "managed" in AX201.modes


def test_no_ir_channels_are_not_ap_capable():
    """5GHz UNII-1 is no-IR under the world domain: association only."""
    for n in (36, 40, 44, 48):
        ch = AX201.channel(n)
        assert ch is not None and not ch.ap_capable
        assert "no-IR" in ch.why_not()


def test_ap_capable_channels():
    numbers = [c.number for c in AX201.ap_channels]
    assert numbers[:13] == list(range(1, 14))       # 2.4GHz is open
    assert {149, 153, 157, 161, 165} <= set(numbers)  # UNII-3 is too
    assert not {36, 40, 44, 48} & set(numbers)


def test_single_channel_concurrency_constraint():
    """AX201 permits client+AP only while both share one channel."""
    comb = AX201.concurrency()
    assert comb is not None
    assert comb.allows("managed", "AP")
    assert comb.max_channels == 1
    assert AX201.same_channel_only


def test_hw_mode_per_band():
    assert AX201.channel(6).hw_mode == "g"
    assert AX201.channel(149).hw_mode == "a"


def test_regdomain_parsing():
    assert caps.parse_regdomain((FIX / "iw_reg_country00.txt").read_text()) == "00"


def test_channel_from_iw_dev_info():
    assert caps.parse_iw_dev_channel("\tchannel 6 (2437 MHz), width: 20 MHz") == 6
    assert caps.parse_iw_dev_channel("no channel here") is None
