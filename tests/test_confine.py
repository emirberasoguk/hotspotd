"""AppArmor reasoning tests.

These encode the discovery that motivated hotspotd: a single `*` in an
AppArmor rule does not cross `/`, so `/etc/hostapd.* r,` permits
`/etc/hostapd.foo` but denies both `/etc/hostapd/foo` and anything in /tmp -
which is where create_ap and its forks write their generated config.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hotspotd import confine  # noqa: E402

FIX = pathlib.Path(__file__).parent / "fixtures"
PROFILE = (FIX / "apparmor_usr.sbin.hostapd.txt").read_text()
GLOBS = confine.parse_read_rules(PROFILE)


def test_read_rules_extracted():
    assert "/etc/hostapd.*" in GLOBS
    assert "/run/hostapd/*" in GLOBS


def test_single_star_does_not_cross_slash():
    assert confine._aa_match("/etc/hostapd.*", "/etc/hostapd.conf")
    assert not confine._aa_match("/etc/hostapd.*", "/etc/hostapd/sub.conf")


def test_double_star_crosses_slash():
    assert confine._aa_match("/etc/**", "/etc/a/b/c.conf")


def test_create_ap_config_location_is_denied():
    """The exact path from the audit log that breaks create_ap."""
    denied = "/tmp/create_ap.wlo1.conf.2or5y8UB/hostapd.conf"
    conf = confine.Confinement(system="apparmor", profile="hostapd",
                               enforced=True, readable_globs=GLOBS)
    assert not conf.permits_read(denied)


def test_hotspotd_config_location_is_allowed():
    conf = confine.Confinement(system="apparmor", profile="hostapd",
                               enforced=True, readable_globs=GLOBS)
    assert conf.permits_read("/etc/hostapd.hotspotd.conf")
    assert confine.pick_config_path(conf) == "/etc/hostapd.hotspotd.conf"


def test_unconfined_permits_everything():
    assert confine.Confinement().permits_read("/tmp/anything.conf")
