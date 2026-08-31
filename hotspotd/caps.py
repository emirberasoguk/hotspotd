"""Wireless PHY capability discovery.

Parses ``iw list`` / ``iw dev`` / ``iw reg get`` into structured data so the
rest of hotspotd can answer, *before* touching anything:

  * Can this radio act as an AP at all?
  * On which channels is starting an AP actually *legal* here?
  * May an AP coexist with the client connection that provides the uplink,
    and if so, under what constraint?

That last question is the one existing tools skip.  Many chipsets - Intel's
AX2xx series among them - allow ``managed`` and ``AP`` simultaneously only
while both stay on a single channel.  Ignoring it produces a hostapd that
starts and then silently never beacons.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# "  * 5180.0 MHz [36] (22.0 dBm) (no IR)"      -> freq, channel, flags
# "  * 2484.0 MHz [14] (disabled)"
_FREQ = re.compile(
    r"^\s*\*\s*(?P<mhz>\d+(?:\.\d+)?)\s*MHz\s*\[(?P<chan>\d+)\](?P<rest>.*)$"
)
# "  * #{ managed } <= 1, #{ AP, P2P-client } <= 1, total <= 3, #channels <= 1"
_COMB_CHANNELS = re.compile(r"#channels\s*<=\s*(\d+)")
_COMB_GROUP = re.compile(r"#\{([^}]*)\}\s*<=\s*(\d+)")


@dataclass(frozen=True)
class Channel:
    number: int
    mhz: float
    disabled: bool = False
    no_ir: bool = False
    radar: bool = False

    @property
    def band(self) -> str:
        if self.mhz < 3000:
            return "2.4GHz"
        if self.mhz < 5900:
            return "5GHz"
        return "6GHz"

    @property
    def hw_mode(self) -> str:
        """hostapd ``hw_mode`` value for this channel."""
        return "g" if self.mhz < 3000 else "a"

    @property
    def ap_capable(self) -> bool:
        """True when regulatory rules permit *initiating* radiation here.

        ``no IR`` means the radio may associate but must never transmit
        first, which is precisely what beaconing does.  DFS/radar channels
        are excluded too: they need radar detection hostapd cannot do
        unattended.
        """
        return not (self.disabled or self.no_ir or self.radar)

    def why_not(self) -> str | None:
        if self.disabled:
            return "disabled by regulatory domain"
        if self.no_ir:
            return "no-IR: may associate but not initiate radiation (no beaconing)"
        if self.radar:
            return "DFS/radar channel: requires radar detection"
        return None


@dataclass
class Combination:
    """One entry from ``valid interface combinations``."""

    groups: list[tuple[list[str], int]] = field(default_factory=list)
    max_channels: int = 1
    raw: str = ""

    def allows(self, *modes: str) -> bool:
        """Whether every requested mode fits, each in a distinct group."""
        remaining = list(self.groups)
        for mode in modes:
            for i, (names, limit) in enumerate(remaining):
                if limit >= 1 and mode in names:
                    del remaining[i]
                    break
            else:
                return False
        return True


@dataclass
class Phy:
    name: str = ""
    modes: list[str] = field(default_factory=list)
    channels: list[Channel] = field(default_factory=list)
    combinations: list[Combination] = field(default_factory=list)

    @property
    def supports_ap(self) -> bool:
        return "AP" in self.modes

    @property
    def ap_channels(self) -> list[Channel]:
        return [c for c in self.channels if c.ap_capable]

    def channel(self, number: int) -> Channel | None:
        return next((c for c in self.channels if c.number == number), None)

    def concurrency(self) -> Combination | None:
        """Best combination permitting a client and an AP at once."""
        usable = [c for c in self.combinations if c.allows("managed", "AP")]
        if not usable:
            return None
        return max(usable, key=lambda c: c.max_channels)

    @property
    def same_channel_only(self) -> bool:
        """True when client+AP must share one channel (``#channels <= 1``)."""
        comb = self.concurrency()
        return comb is not None and comb.max_channels < 2


def parse_iw_list(text: str) -> Phy:
    """Parse ``iw list`` output for the first wiphy it describes."""
    phy = Phy()
    section: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("Wiphy "):
            if phy.name:  # second wiphy - stop, we only model the first
                break
            phy.name = stripped.split(None, 1)[1]
            continue

        # Section headers reset the parsing mode.
        low = stripped.lower()
        if low.startswith("supported interface modes"):
            section = "modes"
            continue
        if low.startswith("valid interface combinations"):
            section = "combinations"
            continue
        if low.startswith("frequencies:"):
            section = "freq"
            continue
        if low.startswith(("band ", "supported commands", "ciphers", "ht capability",
                           "software interface modes", "available antennas")):
            section = "freq" if low.startswith("band ") else None
            continue

        if section == "modes" and stripped.startswith("*"):
            phy.modes.append(stripped.lstrip("* ").strip())
            continue

        if section == "combinations" and stripped.startswith("*"):
            phy.combinations.append(_parse_combination(stripped))
            continue
        if section == "combinations" and phy.combinations and "<=" in stripped:
            # Combinations wrap across lines; fold the continuation in.
            phy.combinations[-1] = _parse_combination(
                phy.combinations[-1].raw + " " + stripped
            )
            continue

        if section == "freq":
            m = _FREQ.match(line)
            if m:
                rest = m.group("rest").lower()
                phy.channels.append(
                    Channel(
                        number=int(m.group("chan")),
                        mhz=float(m.group("mhz")),
                        disabled="disabled" in rest,
                        no_ir="no ir" in rest,
                        radar="radar detection" in rest,
                    )
                )

    return phy


def _parse_combination(raw: str) -> Combination:
    body = raw.lstrip("* ").strip()
    groups = [
        ([n.strip() for n in names.split(",") if n.strip()], int(limit))
        for names, limit in _COMB_GROUP.findall(body)
    ]
    m = _COMB_CHANNELS.search(body)
    return Combination(
        groups=groups,
        max_channels=int(m.group(1)) if m else 1,
        raw=body,
    )


def parse_iw_dev_channel(text: str) -> int | None:
    """Current operating channel from ``iw dev <iface> info``."""
    m = re.search(r"channel\s+(\d+)", text)
    return int(m.group(1)) if m else None


def parse_regdomain(text: str) -> str | None:
    """Country code from ``iw reg get`` (``00`` means world//unset)."""
    m = re.search(r"^country\s+([A-Z0-9]{2}):", text, re.MULTILINE)
    return m.group(1) if m else None
