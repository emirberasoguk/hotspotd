"""Command-line interface.

Two rules shape everything here:

*Never show a traceback.*  A Python stack trace tells the user nothing they
can act on.  Every failure path ends in one sentence about what went wrong
and, where there is one, what to do about it.

*Never guess what is running.*  ``down`` and ``status`` read the state file
:mod:`hotspotd.state` wrote, so they act on the hotspot that actually exists
rather than on a default-valued reconstruction of it.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time

from . import __version__, backend, caps, config, confine, doctor, state, system

C = {"ok": "\033[32m", "warn": "\033[33m", "fail": "\033[31m",
     "dim": "\033[2m", "b": "\033[1m", "r": "\033[0m"}
MARK = {"ok": "✓", "warn": "!", "fail": "✗"}

EXIT_OK, EXIT_ERROR, EXIT_BLOCKED = 0, 1, 2


class UserError(Exception):
    """A problem the user can fix, reported as one line without a traceback."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

def colors(enabled: bool) -> dict:
    if not enabled or not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return {k: "" for k in C}
    return C


def print_report(report: doctor.Report, c: dict) -> None:
    for f in report.findings:
        print(f"  {c[f.status]}{MARK[f.status]}{c['r']} {f.title}")
        if f.detail:
            print(f"      {c['dim']}{f.detail}{c['r']}")
        if f.fix:
            print(f"      {c['b']}fix:{c['r']} {f.fix}")


def human_time(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def need_root(action: str) -> None:
    if os.geteuid() != 0:
        raise UserError(f"{action} needs root privileges", "try: sudo hotspotd ...")


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------

def _build_report(args) -> tuple[doctor.Report, dict, str | None]:
    facts = system.collect(args.interface)
    conf = facts["confinement"]
    try:
        config_path = confine.pick_config_path(conf)
    except RuntimeError:
        config_path = None
    report = doctor.diagnose(
        facts["phy"],
        current_channel=facts["channel"],
        regdomain=facts["regdomain"],
        conf=conf,
        config_path=config_path,
        uplink=facts["iface"],
        phy_known=facts["phy_known"],
    )
    return report, facts, config_path


def cmd_doctor(args) -> int:
    report, facts, config_path = _build_report(args)

    if not facts["has_hostapd"]:
        report.add(doctor.FAIL, "hostapd is not installed",
                   fix="Install it with your package manager, then run doctor again.")
    if not facts["has_dnsmasq"]:
        report.add(doctor.WARN, "dnsmasq is not installed",
                   "Clients would associate but never receive an IP address.",
                   "Install dnsmasq, or run with --no-dhcp and hand out addresses yourself.")

    if args.json:
        print(json.dumps({
            "interface": facts["iface"],
            "blocked": report.blocked,
            "config_path": config_path,
            "findings": [f.__dict__ for f in report.findings],
        }, indent=2))
        return EXIT_BLOCKED if report.blocked else EXIT_OK

    c = colors(not args.no_color)
    print(f"{c['b']}hotspotd doctor{c['r']}  {c['dim']}({facts['iface'] or 'no wifi interface'}){c['r']}")
    print_report(report, c)
    print()
    if report.blocked:
        print(f"{c['fail']}blocked{c['r']} - fix the {MARK['fail']} items above")
        return EXIT_BLOCKED
    print(f"{c['ok']}ready{c['r']} - an access point can start here")
    return EXIT_OK


# --------------------------------------------------------------------------
# the saved profile
# --------------------------------------------------------------------------

DEFAULTS = {
    "ap_interface": "ap0",
    "subnet": "192.168.12",
    "hidden": False,
    "open": False,
    "no_nat": False,
    "no_dhcp": False,
}


def apply_profile(args) -> bool:
    """Fill unset options from /etc/hotspotd/hotspotd.conf, then defaults.

    Anything given on the command line wins, which is what makes it possible
    to try a variation of the saved hotspot without editing the file.
    """
    saved = config.load()
    dests = {dest for dest, _ in config.FIELDS.values()} | set(DEFAULTS)
    for dest in sorted(dests):
        if not hasattr(args, dest) or getattr(args, dest) is not None:
            continue
        setattr(args, dest, saved.get(dest, DEFAULTS.get(dest)))
    return bool(saved)


# --------------------------------------------------------------------------
# up
# --------------------------------------------------------------------------

def _passphrase(args) -> str:
    if args.open:
        return ""
    if args.password:
        return args.password
    env = os.environ.get("HOTSPOTD_PASS")
    if env:
        return env
    if not sys.stdin.isatty():
        raise UserError(
            "no passphrase given",
            "pass --password, set HOTSPOTD_PASS, or use --open for an unencrypted network",
        )
    first = getpass.getpass("WPA2 passphrase (8-63 chars): ")
    if first != getpass.getpass("Repeat passphrase: "):
        raise UserError("the two passphrases do not match")
    return first


def _pick_channel(args, facts) -> tuple[int, caps.Channel]:
    phy: caps.Phy = facts["phy"]
    channel = args.channel or facts["channel"]
    if channel is None:
        raise UserError(
            "not associated to any network and no channel given",
            "pass --channel, or connect to WiFi first if you mean to share it",
        )

    ch = phy.channel(channel)
    if ch is None:
        raise UserError(
            f"channel {channel} is not one this radio reports",
            "run `hotspotd doctor` to see the channels it does",
        )
    if ch.ap_capable:
        return channel, ch

    permitted = ", ".join(str(x.number) for x in phy.ap_channels[:12]) or "none"
    raise UserError(
        f"channel {channel} cannot host an access point - {ch.why_not()}",
        f"channels that can: {permitted}. This radio requires the AP to share "
        f"the uplink's channel, so associate on one of those and retry. "
        f"`hotspotd doctor` explains it in full."
        if phy.same_channel_only else
        f"channels that can: {permitted}; pass one with --channel",
    )


def cmd_up(args) -> int:
    need_root("starting a hotspot")
    c = colors(not args.no_color)
    had_profile = apply_profile(args)

    if not args.ssid:
        raise UserError(
            "no network name given",
            "run `hotspotd up <name>`, or save one with `hotspotd up <name> --save`"
            if not had_profile else
            f"the saved profile in {config.CONFIG_FILE} has no ssid",
        )

    running = state.load()
    if running and backend.hostapd_active(running):
        raise UserError(
            f"a hotspot is already running: {running.ssid} on channel {running.channel}",
            "stop it first with `hotspotd down`",
        )
    if running:
        # State left over from a crash: clean it up before starting again.
        backend.teardown(running)

    facts = system.collect(args.interface)
    if not facts["iface"] and not args.interface:
        raise UserError("no WiFi interface found",
                        "name one with --interface, e.g. --interface wlan0")

    channel, ch = _pick_channel(args, facts)
    passphrase = _passphrase(args)
    cfg = backend.ApConfig(
        ssid=args.ssid,
        passphrase=passphrase,
        channel=channel,
        hw_mode=ch.hw_mode,
        band=ch.band,
        ap_iface=args.ap_interface,
        wifi_iface=args.interface or facts["iface"] or "",
        uplink="" if args.no_nat else (args.uplink or facts["iface"] or ""),
        subnet=args.subnet,
        hidden=args.hidden,
    )
    cfg.validate()

    if args.save:
        # Save the passphrase we actually resolved, not the flag: one typed at
        # the prompt must still be there for the boot service to use.
        to_save = dict(vars(args), password=passphrase)
        saved_to = config.save(to_save)
        print(f"  {c['dim']}settings saved to {saved_to}{c['r']}")

    try:
        config_path = confine.pick_config_path(facts["confinement"])
    except RuntimeError as exc:
        raise UserError(str(exc), "run `hotspotd doctor` for the policy details") from exc

    st = state.State(
        ssid=cfg.ssid, channel=cfg.channel, band=cfg.band, hw_mode=cfg.hw_mode,
        hidden=cfg.hidden, encrypted=cfg.encrypted, subnet=cfg.subnet,
        ap_iface=cfg.ap_iface, wifi_iface=cfg.wifi_iface, uplink=cfg.uplink,
        config_path=config_path,
    )

    steps: list[tuple[str, object]] = [
        ("virtual AP interface", lambda: backend.create_ap_interface(cfg, st)),
        ("hostapd configuration", lambda: backend.write_config(cfg, config_path, st)),
        ("address and NAT", lambda: backend.configure_network(cfg, st)),
    ]
    if not args.no_dhcp:
        steps.append(("DHCP and DNS", lambda: backend.start_dnsmasq(cfg, st)))
    steps.append(("hostapd", lambda: backend.start_hostapd(cfg, config_path, st)))

    for i, (label, fn) in enumerate(steps, 1):
        print(f"  {c['dim']}[{i}/{len(steps)}]{c['r']} {label}")
        try:
            fn()
        except backend.BackendError as exc:
            print(f"  {c['fail']}{MARK['fail']}{c['r']} {exc}", file=sys.stderr)
            backend.teardown(st)
            return EXIT_ERROR
        st.save()

    if not _wait_for_hostapd(st):
        print(f"  {c['fail']}{MARK['fail']}{c['r']} hostapd started but did not stay up:",
              file=sys.stderr)
        log = backend.hostapd_log(st)
        if log.strip():
            print("\n".join("      " + line for line in log.strip().splitlines()[-12:]),
                  file=sys.stderr)
        backend.teardown(st)
        return EXIT_ERROR

    security = "WPA2" if cfg.encrypted else f"{c['warn']}open{c['r']}"
    print()
    print(f"  {c['ok']}{MARK['ok']}{c['r']} {c['b']}{cfg.ssid}{c['r']} is up "
          f"on channel {channel} ({ch.band}), {security}")
    print(f"      network {cfg.subnet}.0/24, gateway {cfg.gateway}"
          + (f", NAT through {cfg.uplink}" if cfg.uplink else ", no internet sharing"))
    print(f"      {c['dim']}hotspotd status   see who connects{c['r']}")
    print(f"      {c['dim']}hotspotd down     stop it{c['r']}")
    return EXIT_OK


def _wait_for_hostapd(st: state.State, seconds: float = 4.0) -> bool:
    """hostapd exits within a second or two when it cannot start at all."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not backend.hostapd_active(st):
            return False
        time.sleep(0.25)
    return backend.hostapd_active(st)


# --------------------------------------------------------------------------
# down
# --------------------------------------------------------------------------

def cmd_down(args) -> int:
    need_root("stopping a hotspot")
    c = colors(not args.no_color)

    st = state.load()
    if st is None:
        print("no hotspot is running")
        return EXIT_OK

    problems = backend.teardown(st)
    print(f"{c['ok']}{MARK['ok']}{c['r']} {st.ssid or 'hotspot'} stopped "
          f"{c['dim']}(ran for {human_time(st.uptime)}){c['r']}")
    for problem in problems:
        print(f"  {c['warn']}{MARK['warn']}{c['r']} {problem}", file=sys.stderr)
    return EXIT_ERROR if problems else EXIT_OK


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------

def cmd_status(args) -> int:
    c = colors(not args.no_color)
    st = state.load()
    active = st is not None and backend.hostapd_active(st)
    clients = backend.stations(st) if active else []

    if args.json:
        print(json.dumps({
            "running": active,
            "hotspot": None if st is None else {
                "ssid": st.ssid, "channel": st.channel, "band": st.band,
                "encrypted": st.encrypted, "hidden": st.hidden,
                "subnet": st.subnet, "ap_interface": st.ap_iface,
                "uplink": st.uplink, "uptime_seconds": round(st.uptime),
            },
            "clients": [vars(s) for s in clients],
        }, indent=2))
        return EXIT_OK

    if st is None:
        print(f"{c['dim']}no hotspot is running{c['r']}")
        return EXIT_OK
    if not active:
        print(f"{c['warn']}{MARK['warn']}{c['r']} {st.ssid}: recorded as running but "
              f"hostapd is not up")
        print(f"      {c['dim']}run `hotspotd down` to clean up{c['r']}")
        return EXIT_ERROR

    security = "WPA2" if st.encrypted else "open"
    print(f"{c['ok']}{MARK['ok']}{c['r']} {c['b']}{st.ssid}{c['r']} "
          f"{c['dim']}up for {human_time(st.uptime)}{c['r']}")
    print(f"    channel {st.channel} ({st.band}), {security}"
          + (", hidden" if st.hidden else ""))
    print(f"    {st.ap_iface} {st.subnet}.1/24"
          + (f", NAT through {st.uplink}" if st.uplink else ", no internet sharing"))

    if not clients:
        print(f"    {c['dim']}no clients connected{c['r']}")
        return EXIT_OK
    print(f"    {len(clients)} client{'s' if len(clients) != 1 else ''}:")
    for s in clients:
        name = s.hostname or "-"
        print(f"      {s.mac}  {s.ip or '-':<15} {name:<20} {c['dim']}{s.signal}{c['r']}")
    return EXIT_OK


# --------------------------------------------------------------------------
# starting at boot
# --------------------------------------------------------------------------

SERVICE = "hotspotd.service"


def _service_installed() -> bool:
    return backend.run("systemctl", "cat", SERVICE, check=False).returncode == 0


def cmd_enable(args) -> int:
    need_root("enabling the boot service")
    c = colors(not args.no_color)
    if not config.exists():
        raise UserError(
            "there is no saved hotspot to start at boot",
            "save one first: `hotspotd up <name> --save`",
        )
    if not _service_installed():
        raise UserError(
            f"{SERVICE} is not installed on this system",
            "install hotspotd with `sudo make install`, which puts the unit in place",
        )
    backend.run("systemctl", "enable", SERVICE)
    print(f"{c['ok']}{MARK['ok']}{c['r']} {config.load().get('ssid', 'the saved hotspot')} "
          f"will start at boot")
    print(f"    {c['dim']}hotspotd disable   turn that off{c['r']}")
    return EXIT_OK


def cmd_disable(args) -> int:
    need_root("disabling the boot service")
    c = colors(not args.no_color)
    if not _service_installed():
        print("nothing to disable: the boot service is not installed")
        return EXIT_OK
    backend.run("systemctl", "disable", SERVICE)
    print(f"{c['ok']}{MARK['ok']}{c['r']} the hotspot will no longer start at boot")
    return EXIT_OK


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # Options are accepted both before and after the command, so
    # `hotspotd --no-color up Home` and `hotspotd up Home --no-color` both
    # work. The shared copies default to SUPPRESS: when the option is not
    # repeated after the command, whatever was given before it survives.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS,
                        help="disable coloured output")

    radio = argparse.ArgumentParser(add_help=False)
    radio.add_argument("-i", "--interface", metavar="IFACE", default=argparse.SUPPRESS,
                       help="WiFi interface to use (default: the first one found)")

    p = argparse.ArgumentParser(
        prog="hotspotd",
        description="A WiFi access point manager that tells you why it cannot start.",
        epilog="Run `hotspotd doctor` first: it says whether an AP can run here at all.",
    )
    p.add_argument("--version", action="version", version=f"hotspotd {__version__}")
    p.add_argument("--no-color", action="store_true", help="disable coloured output")
    p.add_argument("-i", "--interface", metavar="IFACE",
                   help="WiFi interface to use (default: the first one found)")
    p.add_argument("--ap-interface", metavar="IFACE",
                   help="name for the virtual AP interface (default: ap0)")
    p.add_argument("--subnet", metavar="A.B.C",
                   help="first three octets of the hotspot network (default: 192.168.12)")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    d = sub.add_parser("doctor", parents=[common, radio],
                       help="check whether an access point can run here")
    d.add_argument("--json", action="store_true", help="machine-readable output")
    d.set_defaults(fn=cmd_doctor)

    up = sub.add_parser("up", parents=[common, radio], help="start the access point")
    up.add_argument("ssid", nargs="?",
                    help="network name to broadcast (default: the saved profile's)")
    up.add_argument("-p", "--password", metavar="PASS",
                    help="WPA2 passphrase; prompted for if omitted. Avoid on shared "
                         "machines - arguments are visible in `ps`. $HOTSPOTD_PASS works too")
    up.add_argument("--open", action="store_true", default=None,
                    help="no encryption (anyone nearby can join and read the traffic)")
    up.add_argument("-c", "--channel", type=int, metavar="N",
                    help="channel to use (default: the one the uplink is on)")
    up.add_argument("--ap-interface", metavar="IFACE", default=argparse.SUPPRESS,
                    help="name for the virtual AP interface (default: ap0)")
    up.add_argument("--subnet", metavar="A.B.C", default=argparse.SUPPRESS,
                    help="first three octets of the hotspot network (default: 192.168.12)")
    up.add_argument("--uplink", metavar="IFACE",
                    help="interface to share the internet from (default: the WiFi uplink)")
    up.add_argument("--no-nat", action="store_true", default=None,
                    help="do not share any internet connection")
    up.add_argument("--no-dhcp", action="store_true", default=None,
                    help="do not run dnsmasq; clients must configure addresses themselves")
    up.add_argument("--hidden", action="store_true", default=None,
                    help="do not broadcast the SSID")
    up.add_argument("--save", action="store_true",
                    help=f"remember these settings in {config.CONFIG_FILE}")
    up.set_defaults(fn=cmd_up)

    sub.add_parser("down", parents=[common],
                   help="stop the running access point").set_defaults(fn=cmd_down)

    stat = sub.add_parser("status", parents=[common],
                          help="show the running access point and its clients")
    stat.add_argument("--json", action="store_true", help="machine-readable output")
    stat.set_defaults(fn=cmd_status)

    sub.add_parser("enable", parents=[common],
                   help="start the saved hotspot at boot").set_defaults(fn=cmd_enable)
    sub.add_parser("disable", parents=[common],
                   help="stop starting it at boot").set_defaults(fn=cmd_disable)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for attr, default in (("json", False), ("save", False)):
        if not hasattr(args, attr):
            setattr(args, attr, default)
    try:
        return args.fn(args)
    except UserError as exc:
        print(f"hotspotd: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"          {exc.hint}", file=sys.stderr)
        return EXIT_ERROR
    except backend.BackendError as exc:
        print(f"hotspotd: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return EXIT_OK
