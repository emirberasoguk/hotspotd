"""Collecting live system facts, kept apart from the logic that judges them."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import caps, confine


SBIN = ("/usr/sbin", "/sbin", "/usr/local/sbin")


def which(name: str) -> str | None:
    """shutil.which plus the sbin directories absent from a user PATH.

    Without this, an unprivileged run reports hostapd and dnsmasq as
    missing purely because they live in /usr/sbin.
    """
    found = shutil.which(name)
    if found:
        return found
    for d in SBIN:
        candidate = Path(d) / name
        if candidate.is_file() and candidate.stat().st_mode & 0o111:
            return str(candidate)
    return None


def _out(*cmd: str) -> str:
    exe = which(cmd[0])
    if not exe:
        return ""
    try:
        return subprocess.run((exe,) + cmd[1:], capture_output=True, text=True).stdout
    except OSError:
        return ""


def wifi_interface() -> str | None:
    for path in sorted(Path("/sys/class/net").glob("*")):
        if (path / "wireless").exists() or (path / "phy80211").exists():
            return path.name
    return None


def collect(iface: str | None = None) -> dict:
    iface = iface or wifi_interface()
    iw_list = _out("iw", "list")
    phy = caps.parse_iw_list(iw_list)
    # `iw list` yields nothing useful unprivileged on many kernels; say so
    # rather than reporting a radio with no capabilities.
    phy_known = bool(phy.modes or phy.channels)
    return {
        "iface": iface,
        "phy": phy,
        "phy_known": phy_known,
        "channel": caps.parse_iw_dev_channel(_out("iw", "dev", iface, "info")) if iface else None,
        "regdomain": caps.parse_regdomain(_out("iw", "reg", "get")),
        "confinement": confine.detect(),
        "has_dnsmasq": bool(which("dnsmasq")),
        "has_hostapd": bool(which("hostapd")),
    }
