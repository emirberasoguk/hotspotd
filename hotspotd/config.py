"""The saved hotspot, so it can come back without being retyped.

One file, ``/etc/hotspotd/hotspotd.conf``, holds the settings of a hotspot
worth keeping.  ``hotspotd up --save`` writes it, ``hotspotd up`` with no
arguments reads it, and the systemd unit uses exactly the same path - so what
starts at boot is the hotspot you tested by hand, not a second configuration
that can drift away from it.

It contains the passphrase, so it is written 0600 and its directory 0700.
"""

from __future__ import annotations

import configparser
import os
from pathlib import Path

CONFIG_DIR = Path("/etc/hotspotd")
CONFIG_FILE = CONFIG_DIR / "hotspotd.conf"
SECTION = "hotspot"

# option name -> (argparse dest, kind)
FIELDS = {
    "ssid": ("ssid", str),
    "password": ("password", str),
    "channel": ("channel", int),
    "interface": ("interface", str),
    "ap-interface": ("ap_interface", str),
    "subnet": ("subnet", str),
    "uplink": ("uplink", str),
    "hidden": ("hidden", bool),
    "open": ("open", bool),
    "no-nat": ("no_nat", bool),
    "no-dhcp": ("no_dhcp", bool),
}


def exists() -> bool:
    return CONFIG_FILE.is_file()


def load() -> dict:
    """Saved settings as argparse destinations, or {} if there are none."""
    parser = configparser.ConfigParser()
    try:
        parser.read(CONFIG_FILE)
    except (OSError, configparser.Error):
        return {}
    if not parser.has_section(SECTION):
        return {}

    out: dict = {}
    for option, (dest, kind) in FIELDS.items():
        if not parser.has_option(SECTION, option):
            continue
        try:
            if kind is bool:
                out[dest] = parser.getboolean(SECTION, option)
            elif kind is int:
                out[dest] = parser.getint(SECTION, option)
            else:
                value = parser.get(SECTION, option).strip()
                if value:
                    out[dest] = value
        except ValueError:
            continue          # a malformed line must not break `up`
    return out


def save(settings: dict) -> Path:
    """Write the profile, 0600, creating /etc/hotspotd if needed."""
    parser = configparser.ConfigParser()
    parser[SECTION] = {}
    for option, (dest, kind) in FIELDS.items():
        value = settings.get(dest)
        if value in (None, "", False):
            continue
        parser[SECTION][option] = "yes" if kind is bool else str(value)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    old = os.umask(0o077)
    try:
        tmp = CONFIG_FILE.with_suffix(".tmp")
        with open(tmp, "w") as fh:
            fh.write("# hotspotd - written by `hotspotd up --save`\n"
                     "# Contains the WPA2 passphrase; keep it readable by root only.\n")
            parser.write(fh)
        os.replace(tmp, CONFIG_FILE)
    finally:
        os.umask(old)
    return CONFIG_FILE
