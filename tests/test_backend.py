"""Config rendering, validation and lease parsing - the parts with no side effects."""
import tempfile
from pathlib import Path

from hotspotd import backend, state


def cfg(**kw):
    base = dict(ssid="Home", passphrase="supersecret", channel=6, hw_mode="g")
    base.update(kw)
    return backend.ApConfig(**base)


def test_wpa2_config_has_the_passphrase_and_nothing_stale():
    text = backend.render_hostapd(cfg())
    assert "wpa=2" in text
    assert "wpa_passphrase=supersecret" in text
    assert "rsn_pairwise=CCMP" in text
    assert text.endswith("\n")


def test_open_network_carries_no_wpa_settings():
    text = backend.render_hostapd(cfg(passphrase=""))
    assert "wpa" not in text
    assert "ssid=Home" in text


def test_hidden_sets_ignore_broadcast():
    assert "ignore_broadcast_ssid=1" in backend.render_hostapd(cfg(hidden=True))
    assert "ignore_broadcast_ssid=0" in backend.render_hostapd(cfg())


def test_short_passphrase_is_rejected_before_anything_is_touched():
    try:
        cfg(passphrase="short").validate()
    except backend.BackendError as exc:
        assert "8-63" in str(exc)
    else:
        raise AssertionError("a 5-character passphrase must not be accepted")


def test_empty_passphrase_is_valid_because_that_is_an_open_network():
    cfg(passphrase="").validate()


def test_ssid_length_is_checked():
    for bad in ("", "x" * 33):
        try:
            cfg(ssid=bad).validate()
        except backend.BackendError:
            pass
        else:
            raise AssertionError(f"SSID {bad!r} must not be accepted")


def test_a_malformed_subnet_is_caught_not_turned_into_broken_rules():
    for bad in ("bad", "192.168", "192.168.1.1", "192.168.999"):
        try:
            cfg(subnet=bad).validate()
        except backend.BackendError:
            pass
        else:
            raise AssertionError(f"subnet {bad!r} must not be accepted")


def test_gateway_and_network_follow_the_subnet():
    c = cfg(subnet="10.42.0")
    assert c.gateway == "10.42.0.1"
    assert c.network == "10.42.0.0/24"


def test_leases_are_parsed_into_ip_and_hostname():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "leases"
        path.write_text(
            "1788988273 16:91:1b:04:e8:e9 192.168.12.2 phone 01:16:91:1b:04:e8:e9\n"
            "1788988300 aa:bb:cc:dd:ee:ff 192.168.12.3 * 01:aa:bb:cc:dd:ee:ff\n"
        )
        backend.DNSMASQ_LEASES = path
        leases = backend._leases()
        assert leases["16:91:1b:04:e8:e9"] == ("192.168.12.2", "phone")
        assert leases["aa:bb:cc:dd:ee:ff"] == ("192.168.12.3", "")


def test_missing_lease_file_is_empty_not_an_error():
    backend.DNSMASQ_LEASES = Path("/nonexistent/leases")
    assert backend._leases() == {}


def test_hostapd_is_not_reported_running_when_nothing_was_started():
    assert backend.hostapd_active(state.State()) is False


def test_a_clone_sharing_the_radios_mac_gets_a_new_one():
    # Two interfaces on one phy may not share an address: the second refuses
    # to come up with EBUSY, which is what `hotspotd up` hit on real hardware.
    real_all, real_of = backend._all_macs, backend.mac_of
    try:
        backend._all_macs = lambda: {"wlo1": "e4:0d:36:01:9f:cd",
                                     "ap0": "e4:0d:36:01:9f:cd"}
        backend.mac_of = lambda iface: "e4:0d:36:01:9f:cd"
        assert backend.distinct_mac("ap0") == "e4:0d:36:01:9f:ce"
    finally:
        backend._all_macs, backend.mac_of = real_all, real_of


def test_the_next_address_is_skipped_when_something_else_holds_it():
    real_all, real_of = backend._all_macs, backend.mac_of
    try:
        backend._all_macs = lambda: {"wlo1": "e4:0d:36:01:9f:cd",
                                     "ap0": "e4:0d:36:01:9f:cd",
                                     "wlan1": "e4:0d:36:01:9f:ce"}
        backend.mac_of = lambda iface: "e4:0d:36:01:9f:cd"
        assert backend.distinct_mac("ap0") == "e4:0d:36:01:9f:cf"
    finally:
        backend._all_macs, backend.mac_of = real_all, real_of


def test_a_unique_address_is_left_alone():
    real_all, real_of = backend._all_macs, backend.mac_of
    try:
        backend._all_macs = lambda: {"wlo1": "e4:0d:36:01:9f:cd",
                                     "ap0": "e4:0d:36:01:9f:ff"}
        backend.mac_of = lambda iface: "e4:0d:36:01:9f:ff"
        assert backend.distinct_mac("ap0") is None
    finally:
        backend._all_macs, backend.mac_of = real_all, real_of


def test_last_byte_wraps_instead_of_overflowing():
    real_all, real_of = backend._all_macs, backend.mac_of
    try:
        backend._all_macs = lambda: {"wlo1": "e4:0d:36:01:9f:ff",
                                     "ap0": "e4:0d:36:01:9f:ff"}
        backend.mac_of = lambda iface: "e4:0d:36:01:9f:ff"
        assert backend.distinct_mac("ap0") == "e4:0d:36:01:9f:00"
    finally:
        backend._all_macs, backend.mac_of = real_all, real_of
