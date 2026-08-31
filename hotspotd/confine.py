"""Mandatory-access-control awareness.

hostapd is confined by AppArmor on most distributions that ship it.  The
openSUSE profile, for instance, grants config reads only through::

    /etc/hostapd.* r,

In AppArmor a single ``*`` does not cross ``/``.  That one detail makes
``/etc/hostapd/foo.conf`` **and** every ``/tmp/...`` path unreadable - which
is exactly where ``create_ap`` and its forks write their generated config.
hostapd then reports::

    Could not open configuration file '/tmp/create_ap.../hostapd.conf'

The file is there and root owns it, so the message sends everyone hunting
for a missing file.  The real cause only appears in the audit log::

    apparmor="DENIED" operation="open" profile="hostapd" \
        name="/tmp/create_ap.wlo1.conf.2or5y8UB/hostapd.conf" denied_mask="r"

hotspotd resolves the confinement first and writes its config somewhere the
policy actually permits, instead of failing and blaming the filesystem.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

APPARMOR_PROFILE = Path("/etc/apparmor.d/usr.sbin.hostapd")

# Candidates in order of preference.  The first one the active policy allows
# and we can actually create wins.
CONFIG_CANDIDATES = [
    "/etc/hostapd.hotspotd.conf",   # matches the common `/etc/hostapd.* r,`
    "/etc/hostapd/hotspotd.conf",   # profiles that grant the directory
    "/run/hostapd/hotspotd.conf",   # profiles granting /run/hostapd/*
    "/tmp/hotspotd.conf",           # unconfined systems
]


@dataclass
class Confinement:
    system: str = "none"          # "apparmor" | "selinux" | "none"
    profile: str | None = None
    enforced: bool = False
    readable_globs: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.readable_globs is None:
            self.readable_globs = []

    def permits_read(self, path: str) -> bool:
        if not self.enforced or not self.readable_globs:
            return True
        return any(_aa_match(g, path) for g in self.readable_globs)


def _aa_match(glob: str, path: str) -> bool:
    """AppArmor glob matching.

    ``**`` crosses directory separators, a single ``*`` does not, ``?``
    matches one non-separator character.  Everything else is literal.
    """
    out, i = [], 0
    while i < len(glob):
        ch = glob[i]
        if ch == "*":
            if glob[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        elif ch == "{":
            end = glob.find("}", i)
            if end != -1:
                alts = glob[i + 1 : end].split(",")
                out.append("(?:" + "|".join(re.escape(a) for a in alts) + ")")
                i = end + 1
                continue
            out.append(re.escape(ch))
        else:
            out.append(re.escape(ch))
        i += 1
    return re.fullmatch("".join(out), path) is not None


def detect(profile_path: Path | None = None, aa_status: str | None = None) -> Confinement:
    """Describe how hostapd is confined on this system."""
    if _selinux_enforcing():
        return Confinement(system="selinux", profile="targeted", enforced=True)

    path = profile_path or APPARMOR_PROFILE
    if not path.exists():
        return Confinement()

    try:
        text = path.read_text()
    except OSError:
        return Confinement(system="apparmor", profile="hostapd", enforced=False)

    enforced = _apparmor_loaded("hostapd", aa_status)
    return Confinement(
        system="apparmor",
        profile="hostapd",
        enforced=enforced,
        readable_globs=parse_read_rules(text),
    )


def parse_read_rules(profile_text: str) -> list[str]:
    """File paths a profile grants read access to."""
    globs: list[str] = []
    for line in profile_text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line.endswith(",") or not line.startswith("/"):
            continue
        body = line[:-1].strip()
        parts = body.rsplit(None, 1)
        if len(parts) != 2:
            continue
        target, perms = parts
        if "r" in perms and set(perms) <= set("rwmixlkaCUPD"):
            globs.append(target)
    return globs


def _apparmor_loaded(profile: str, aa_status: str | None) -> bool:
    if aa_status is None:
        try:
            aa_status = Path("/sys/kernel/security/apparmor/profiles").read_text()
        except OSError:
            # Unreadable without privilege.  A profile file exists, so assume
            # it is enforced: guessing "unconfined" here would send us back to
            # the /tmp path that fails with a misleading error.
            return True
    return any(
        line.split()[0] == profile and "(enforce)" in line
        for line in aa_status.splitlines()
        if line.strip()
    )


def _selinux_enforcing() -> bool:
    try:
        return Path("/sys/fs/selinux/enforce").read_text().strip() == "1"
    except OSError:
        return False


def pick_config_path(conf: Confinement, candidates: list[str] | None = None) -> str:
    """First config location the policy allows and we can write."""
    for cand in candidates or CONFIG_CANDIDATES:
        if not conf.permits_read(cand):
            continue
        parent = os.path.dirname(cand)
        if os.path.isdir(parent) or _creatable(parent):
            return cand
    raise RuntimeError(
        "no config path is both writable and permitted by the "
        f"{conf.system} policy for hostapd; tried: {', '.join(candidates or CONFIG_CANDIDATES)}"
    )


def _creatable(directory: str) -> bool:
    parent = os.path.dirname(directory.rstrip("/"))
    return os.path.isdir(parent) and os.access(parent, os.W_OK)
