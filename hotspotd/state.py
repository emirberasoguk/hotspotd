"""What is actually running, written down.

Every other WiFi AP script on Linux has the same hole: it knows how to start
a hotspot but not what it started.  Stopping one then means guessing - the
default subnet, the default interface, the default everything - and when the
guess is wrong the teardown quietly leaves NAT rules, a firewall zone or a
DHCP server behind.

hotspotd records each step the moment it succeeds, so ``down`` undoes exactly
what ``up`` did and nothing else.  The file also survives the CLI exiting,
which is what lets ``status`` report a hotspot started by an earlier
invocation, or by the systemd unit at boot.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

STATE_DIR = Path("/run/hotspotd")
STATE_FILE = STATE_DIR / "state.json"

# Bumped when the on-disk shape changes incompatibly.  A state file from a
# newer hotspotd is ignored rather than misread.
STATE_VERSION = 1


@dataclass
class State:
    """A running hotspot, and every change made to bring it up.

    The ``did_*`` fields are the undo list.  Anything not recorded there was
    never done, so teardown must not try to reverse it.
    """

    version: int = STATE_VERSION
    started_at: float = field(default_factory=time.time)

    # what the user asked for
    ssid: str = ""
    channel: int = 0
    band: str = ""
    hw_mode: str = "g"
    hidden: bool = False
    encrypted: bool = True
    subnet: str = ""
    ap_iface: str = ""
    wifi_iface: str = ""
    uplink: str = ""
    config_path: str = ""

    # what we changed, and therefore must change back
    did_create_iface: bool = False
    did_write_config: bool = False
    did_nm_unmanage: bool = False   # we wrote the NetworkManager drop-in
    did_ip_forward: str = ""          # previous /proc value, "" if untouched
    dnsmasq_pid: int = 0
    hostapd_unit: str = ""          # transient systemd unit, when there is systemd
    hostapd_pid: int = 0            # plain child process, when there is not
    nft_table: str = ""               # non-empty when we created one
    firewalld_ap_zone: str = ""       # zone we moved the AP interface into
    firewalld_ap_old_zone: str = ""   # where it was before, "" if nowhere
    firewalld_masq_zone: str = ""     # zone we enabled masquerading on

    @property
    def uptime(self) -> float:
        return max(0.0, time.time() - self.started_at)

    def save(self) -> None:
        """Write atomically: a half-written state file is worse than none."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(STATE_DIR, 0o700)
        tmp = STATE_FILE.with_suffix(".tmp")
        old = os.umask(0o077)
        try:
            tmp.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")
            os.replace(tmp, STATE_FILE)
        finally:
            os.umask(old)
            tmp.unlink(missing_ok=True)

    def clear(self) -> None:
        STATE_FILE.unlink(missing_ok=True)


def load() -> State | None:
    """The running hotspot, or None if there is not one recorded."""
    try:
        raw = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
        return None
    known = {f: raw[f] for f in State.__dataclass_fields__ if f in raw}
    try:
        return State(**known)
    except TypeError:
        return None
