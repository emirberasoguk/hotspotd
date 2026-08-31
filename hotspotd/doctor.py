"""Pre-flight diagnosis.

The reason hotspots "just don't work" on Linux is rarely a missing package.
It is a constraint the tooling never surfaces: a radio that cannot beacon on
the channel it is parked on, a regulatory domain that forbids initiating
radiation, a MAC policy that hides the config file from hostapd.  Every one
of those produces a failure message pointing somewhere else entirely.

``hotspotd doctor`` answers, in order, the questions that actually decide
whether an AP can come up here - and when the answer is no, says which knob
to turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import caps, confine

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Finding:
    status: str
    title: str
    detail: str = ""
    fix: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, status: str, title: str, detail: str = "", fix: str = "") -> None:
        self.findings.append(Finding(status, title, detail, fix))

    @property
    def blocked(self) -> bool:
        return any(f.status == FAIL for f in self.findings)


def diagnose(
    phy: caps.Phy,
    *,
    current_channel: int | None,
    regdomain: str | None,
    conf: confine.Confinement,
    config_path: str | None,
    uplink: str | None = None,
    phy_known: bool = True,
) -> Report:
    """Build a report from already-collected system facts.

    Pure function of its inputs so it can be unit-tested against captured
    hardware, which is how hotspotd avoids regressions on radios the author
    does not own.
    """
    r = Report()

    # 0. Did we actually get to look at the radio?
    if not phy_known:
        r.add(
            WARN,
            "Radio capabilities unavailable",
            "`iw list` returned nothing usable, which normally means this ran "
            "without privilege.",
            "Re-run as root: `sudo hotspotd doctor`.",
        )
        return r

    # 1. Can the radio be an AP at all?
    if phy.supports_ap:
        r.add(OK, "AP mode supported", f"{phy.name} advertises AP in its interface modes")
    else:
        r.add(
            FAIL,
            "AP mode not supported",
            f"{phy.name} modes: {', '.join(phy.modes) or 'unknown'}",
            "This radio cannot host an access point. A USB WiFi dongle with AP "
            "support is the only route.",
        )
        return r

    # 2. Regulatory domain - the root of most 5GHz surprises.
    if regdomain in (None, "00"):
        r.add(
            WARN,
            "Regulatory domain is unset (00 / world)",
            "The world domain marks nearly all 5GHz channels no-IR, so an AP "
            "may only run on 2.4GHz.",
            "Set a country: `iw reg set <CC>`. Self-managed radios (most Intel) "
            "ignore this and take the domain from firmware/802.11d instead.",
        )
    else:
        r.add(OK, f"Regulatory domain: {regdomain}")

    # 3. Which channels may legally beacon?
    usable = phy.ap_channels
    if not usable:
        r.add(
            FAIL,
            "No channel permits beaconing",
            "Every channel is disabled, no-IR or radar-gated under the current "
            "regulatory domain.",
            "Set a correct country code, or connect to a network that "
            "advertises 802.11d country information.",
        )
        return r
    by_band: dict[str, list[int]] = {}
    for c in usable:
        by_band.setdefault(c.band, []).append(c.number)
    r.add(
        OK,
        f"{len(usable)} channels permit beaconing",
        "; ".join(f"{b}: {_compact(n)}" for b, n in by_band.items()),
    )

    # 4. Concurrency - can the AP coexist with the uplink client?
    comb = phy.concurrency()
    if comb is None:
        r.add(
            WARN,
            "Radio cannot run client and AP together",
            "No interface combination permits managed + AP simultaneously.",
            "Share a different uplink (ethernet, USB tethering) instead of "
            "the WiFi you are connected to.",
        )
    elif phy.same_channel_only:
        r.add(
            WARN,
            "Client and AP must share one channel",
            f"combination: {comb.raw}",
            "hotspotd pins the AP to the channel the uplink already uses.",
        )
    else:
        r.add(OK, "Client and AP may use different channels",
              f"up to {comb.max_channels} channels")

    # 5. The decisive check: is *this* channel usable right now?
    if current_channel is None:
        r.add(
            WARN,
            "WiFi is not associated",
            "No current channel, so no channel constraint can be derived.",
            "Connect to a network first if you intend to share it.",
        )
    else:
        ch = phy.channel(current_channel)
        if ch is None:
            r.add(WARN, f"Channel {current_channel} not in the PHY channel list")
        elif ch.ap_capable:
            r.add(OK, f"Channel {current_channel} ({ch.band}) can host the AP")
        elif phy.same_channel_only:
            alts = _compact([c.number for c in usable if c.band == "2.4GHz"])
            r.add(
                FAIL,
                f"Channel {current_channel} cannot host an AP",
                f"{ch.why_not()} - and this radio requires the AP to share the "
                "uplink's channel, so the hotspot cannot start while you are "
                "associated here.",
                f"Associate on a channel that permits beaconing (2.4GHz: {alts}) "
                "and retry.",
            )
        else:
            r.add(WARN, f"Channel {current_channel} cannot host an AP",
                  ch.why_not() or "", "hotspotd will pick a permitted channel.")

    # 6. Mandatory access control - the silent killer.
    if conf.system == "none":
        r.add(OK, "hostapd is unconfined")
    elif conf.system == "selinux":
        r.add(WARN, "SELinux is enforcing",
              "hostapd may be denied access to a generated config.",
              "Check `ausearch -m avc -c hostapd` if startup fails.")
    else:
        state = "enforced" if conf.enforced else "loaded (not enforcing)"
        r.add(
            OK if config_path else WARN,
            f"hostapd confined by AppArmor ({state})",
            "config reads allowed from: " + ", ".join(conf.readable_globs or ["-"]),
            "" if config_path else "No permitted config path found.",
        )
        if config_path:
            r.add(OK, "Config path satisfies the policy", config_path)

    if uplink:
        r.add(OK, f"Uplink interface: {uplink}")

    return r


def _compact(numbers: list[int]) -> str:
    """[1,2,3,5,6] -> '1-3, 5-6'"""
    if not numbers:
        return "-"
    nums = sorted(set(numbers))
    runs, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        runs.append((start, prev))
        start = prev = n
    runs.append((start, prev))
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)
