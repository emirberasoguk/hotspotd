"""The saved profile: what `up --save` writes and the boot service reads."""
import tempfile
from pathlib import Path

from hotspotd import config


def _isolate(tmp: Path) -> None:
    config.CONFIG_DIR = tmp / "hotspotd"
    config.CONFIG_FILE = config.CONFIG_DIR / "hotspotd.conf"


def test_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        config.save({"ssid": "Home", "password": "supersecret", "channel": 6,
                     "subnet": "10.42.0", "hidden": True, "open": False})
        loaded = config.load()
        assert loaded["ssid"] == "Home"
        assert loaded["password"] == "supersecret"
        assert loaded["channel"] == 6
        assert loaded["hidden"] is True
        assert "open" not in loaded          # false flags are not written


def test_profile_holds_a_passphrase_so_it_must_be_root_only():
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        path = config.save({"ssid": "Home", "password": "supersecret"})
        assert path.stat().st_mode & 0o077 == 0
        assert config.CONFIG_DIR.stat().st_mode & 0o077 == 0


def test_absent_profile_is_empty_not_an_error():
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        assert config.load() == {}
        assert config.exists() is False


def test_a_malformed_value_does_not_break_the_rest():
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        config.CONFIG_DIR.mkdir(parents=True)
        config.CONFIG_FILE.write_text("[hotspot]\nssid = Home\nchannel = six\n")
        loaded = config.load()
        assert loaded["ssid"] == "Home"
        assert "channel" not in loaded


def test_file_without_our_section_is_ignored():
    with tempfile.TemporaryDirectory() as d:
        _isolate(Path(d))
        config.CONFIG_DIR.mkdir(parents=True)
        config.CONFIG_FILE.write_text("[something-else]\nssid = Home\n")
        assert config.load() == {}
