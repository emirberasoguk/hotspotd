import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hotspotd import caps, confine, doctor  # noqa: E402

FIX = pathlib.Path(__file__).parent / "fixtures"
AX201 = caps.parse_iw_list((FIX / "iw_list_ax201.txt").read_text())
GLOBS = confine.parse_read_rules((FIX / "apparmor_usr.sbin.hostapd.txt").read_text())
CONF = confine.Confinement("apparmor", "hostapd", True, GLOBS)


def _run(channel):
    return doctor.diagnose(AX201, current_channel=channel, regdomain="00",
                           conf=CONF, config_path="/etc/hostapd.hotspotd.conf")


def test_no_ir_channel_blocks_on_single_channel_radio():
    report = _run(48)
    assert report.blocked
    assert any("Channel 48 cannot host an AP" in f.title for f in report.findings)


def test_permitted_channel_is_not_blocked():
    assert not _run(6).blocked


def test_unprivileged_run_does_not_claim_missing_ap_support():
    report = doctor.diagnose(caps.Phy(), current_channel=None, regdomain=None,
                             conf=CONF, config_path=None, phy_known=False)
    assert not report.blocked
    assert "root" in report.findings[0].fix


def test_compact_ranges():
    assert doctor._compact([1, 2, 3, 5, 6, 11]) == "1-3, 5-6, 11"
