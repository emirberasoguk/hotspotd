"""The state file is what makes `down` exact instead of a guess."""
import json
import tempfile
from pathlib import Path

from hotspotd import state


def _isolate(tmp: Path) -> None:
    state.STATE_DIR = tmp
    state.STATE_FILE = tmp / "state.json"


def test_roundtrip_preserves_every_field():
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        st = state.State(ssid="Home", channel=6, band="2.4GHz", subnet="10.42.0",
                         ap_iface="ap0", firewalld_masq_zone="public",
                         did_create_iface=True, dnsmasq_pid=1234)
        st.save()
        back = state.load()
        assert back is not None
        assert back.ssid == "Home"
        assert back.subnet == "10.42.0"          # not the default: this is the point
        assert back.firewalld_masq_zone == "public"
        assert back.did_create_iface is True
        assert back.dnsmasq_pid == 1234


def test_missing_file_is_not_an_error():
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        assert state.load() is None


def test_corrupt_file_is_ignored_rather_than_crashing():
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        state.STATE_FILE.write_text("{not json at all")
        assert state.load() is None


def test_state_from_a_newer_version_is_ignored():
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        state.STATE_FILE.write_text(json.dumps({"version": state.STATE_VERSION + 1,
                                                "ssid": "Home"}))
        assert state.load() is None


def test_unknown_keys_do_not_break_loading():
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        state.STATE_FILE.write_text(json.dumps({"version": state.STATE_VERSION,
                                                "ssid": "Home",
                                                "field_from_the_future": 1}))
        loaded = state.load()
        assert loaded is not None and loaded.ssid == "Home"


def test_state_file_is_not_world_readable():
    # it records the network layout of a machine; keep it to root
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        state.State(ssid="Home").save()
        assert state.STATE_FILE.stat().st_mode & 0o077 == 0


def test_clear_removes_the_file():
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        st = state.State(ssid="Home")
        st.save()
        st.clear()
        assert state.load() is None
        st.clear()          # twice must not raise


def test_teardown_leaves_no_run_directory_behind():
    from hotspotd import backend
    with tempfile.TemporaryDirectory() as d:
        run_dir = Path(d) / "hotspotd"
        _isolate(run_dir)
        backend.STATE_DIR = run_dir
        backend.DNSMASQ_LEASES = run_dir / "dnsmasq.leases"
        backend.HOSTAPD_LOG = run_dir / "hostapd.log"
        backend.DNSMASQ_PID = run_dir / "dnsmasq.pid"

        st = state.State(ssid="Home")          # nothing was actually done
        st.save()
        backend.DNSMASQ_LEASES.write_text("1 aa:bb:cc:dd:ee:ff 10.0.0.2 phone *\n")
        backend.HOSTAPD_LOG.write_text("noise\n")

        backend.teardown(st)
        assert not run_dir.exists()
