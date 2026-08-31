"""Command-line entry point."""
from __future__ import annotations

import argparse
import os
import sys
import time

from . import __version__, backend, caps, confine, doctor, system

C = {"ok": "\033[32m", "warn": "\033[33m", "fail": "\033[31m",
     "dim": "\033[2m", "b": "\033[1m", "r": "\033[0m"}
MARK = {"ok": "✓", "warn": "!", "fail": "✗"}


def _color(enabled: bool):
    return C if enabled and sys.stdout.isatty() else {k: "" for k in C}


def print_report(report: doctor.Report, c) -> None:
    for f in report.findings:
        print(f"  {c[f.status]}{MARK[f.status]}{c['r']} {f.title}")
        if f.detail:
            print(f"      {c['dim']}{f.detail}{c['r']}")
        if f.fix:
            print(f"      {c['b']}fix:{c['r']} {f.fix}")


def need_root() -> None:
    if os.geteuid() != 0:
        sys.exit("hotspotd: this command needs root (try sudo)")


def cmd_doctor(args) -> int:
    c = _color(not args.no_color)
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
    print(f"{c['b']}hotspotd doctor{c['r']}  {c['dim']}({facts['iface'] or 'no wifi'}){c['r']}")
    print_report(report, c)
    if not facts["has_hostapd"]:
        print(f"  {c['fail']}{MARK['fail']}{c['r']} hostapd not installed")
        return 1
    if not facts["has_dnsmasq"]:
        print(f"  {c['warn']}{MARK['warn']}{c['r']} dnsmasq not installed (no DHCP for clients)")
    print()
    print("blocked - fix the ✗ items above" if report.blocked else "ready to start an AP")
    return 1 if report.blocked else 0


def cmd_up(args) -> int:
    need_root()
    c = _color(not args.no_color)
    facts = system.collect(args.interface)
    phy: caps.Phy = facts["phy"]
    conf = facts["confinement"]

    channel = args.channel or facts["channel"]
    if channel is None:
        sys.exit("hotspotd: not associated and no --channel given")

    ch = phy.channel(channel)
    if ch is None:
        sys.exit(f"hotspotd: channel {channel} unknown to {phy.name}")
    if not ch.ap_capable:
        alt = ", ".join(str(x.number) for x in phy.ap_channels[:12])
        sys.exit(
            f"hotspotd: channel {channel} cannot host an AP - {ch.why_not()}\n"
            f"          radio requires AP on the uplink channel; permitted: {alt}\n"
            f"          run `hotspotd doctor` for the full picture"
        )

    passphrase = args.password or os.environ.get("HOTSPOTD_PASS", "")
    cfg = backend.ApConfig(
        ssid=args.ssid,
        passphrase=passphrase,
        channel=channel,
        hw_mode=ch.hw_mode,
        ap_iface=args.ap_interface,
        wifi_iface=facts["iface"] or "wlan0",
        uplink=args.uplink or facts["iface"] or "",
        subnet=args.subnet,
        hidden=args.hidden,
        config_path=confine.pick_config_path(conf),
    )
    cfg.validate()

    steps = [
        ("virtual AP interface", lambda: backend.create_ap_interface(cfg)),
        ("hostapd config", lambda: backend.write_config(cfg)),
        ("address and NAT", lambda: backend.configure_network(cfg)),
        ("DHCP/DNS", lambda: backend.start_dnsmasq(cfg)),
        ("hostapd", lambda: backend.start_hostapd(cfg)),
    ]
    for i, (label, fn) in enumerate(steps, 1):
        print(f"  {c['dim']}[{i}/{len(steps)}]{c['r']} {label}")
        try:
            fn()
        except backend.BackendError as exc:
            print(f"  {c['fail']}{MARK['fail']}{c['r']} {exc}")
            backend.teardown(cfg)
            return 1

    time.sleep(3)
    if not backend.hostapd_active():
        print(f"  {c['fail']}{MARK['fail']}{c['r']} hostapd did not stay up:")
        print(backend.hostapd_log())
        backend.teardown(cfg)
        return 1

    print(f"\n  {c['ok']}{MARK['ok']}{c['r']} {c['b']}{cfg.ssid}{c['r']} on channel "
          f"{channel} ({ch.band}), network {cfg.subnet}.0/24")
    return 0


def cmd_down(args) -> int:
    need_root()
    facts = system.collect(args.interface)
    cfg = backend.ApConfig(
        ssid="", passphrase="x" * 8, channel=1, hw_mode="g",
        ap_iface=args.ap_interface, wifi_iface=facts["iface"] or "wlan0",
        subnet=args.subnet, config_path=confine.pick_config_path(facts["confinement"]),
    )
    backend.teardown(cfg)
    print("hotspot stopped")
    return 0


def cmd_status(args) -> int:
    c = _color(not args.no_color)
    active = backend.hostapd_active()
    print(f"hostapd: {c['ok'] if active else c['dim']}"
          f"{'running' if active else 'stopped'}{c['r']}")
    if active:
        cfg = backend.ApConfig(ssid="", passphrase="x" * 8, channel=1,
                              hw_mode="g", ap_iface=args.ap_interface)
        found = backend.clients(cfg)
        print("clients:", len(found))
        for line in found:
            print("  ", line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hotspotd",
                                description="WiFi access point manager that explains itself")
    p.add_argument("--version", action="version", version=f"hotspotd {__version__}")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("-i", "--interface", help="wifi interface (default: autodetect)")
    p.add_argument("--ap-interface", default="ap0")
    p.add_argument("--subnet", default="192.168.12")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="diagnose whether an AP can run here").set_defaults(fn=cmd_doctor)

    up = sub.add_parser("up", help="start the access point")
    up.add_argument("-s", "--ssid", required=True)
    up.add_argument("-p", "--password", help="WPA2 passphrase (or $HOTSPOTD_PASS)")
    up.add_argument("-c", "--channel", type=int, help="default: the uplink's channel")
    up.add_argument("--uplink", help="interface to NAT through")
    up.add_argument("--hidden", action="store_true")
    up.set_defaults(fn=cmd_up)

    sub.add_parser("down", help="stop the access point").set_defaults(fn=cmd_down)
    sub.add_parser("status", help="show current state").set_defaults(fn=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)
