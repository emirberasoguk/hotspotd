# hotspotd

A WiFi access point manager for Linux that tells you **why** it can't start —
instead of failing with a message that points somewhere else.

[![test](https://github.com/emirberasoguk/hotspotd/actions/workflows/test.yml/badge.svg)](https://github.com/emirberasoguk/hotspotd/actions/workflows/test.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![no dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](#requirements)

```console
$ sudo hotspotd doctor
hotspotd doctor  (wlo1)
  ✓ AP mode supported
  ! Regulatory domain is unset (00 / world)
  ✓ 18 channels permit beaconing
      2.4GHz: 1-13; 5GHz: 149, 153, 157, 161, 165
  ! Client and AP must share one channel
  ✗ Channel 48 cannot host an AP
      no-IR: may associate but not initiate radiation (no beaconing) - and this
      radio requires the AP to share the uplink's channel, so the hotspot cannot
      start while you are associated here.
      fix: Associate on a channel that permits beaconing (2.4GHz: 1-13) and retry.
  ✓ hostapd confined by AppArmor (enforced)
  ✓ Config path satisfies the policy   /etc/hostapd.hotspotd.conf

blocked - fix the ✗ items above
```

Every other tool, in that situation, says `Your adapter can not transmit to
channel 48`, or nothing at all.

> **Status:** 0.1.0. Verified end to end on Intel AX201 / iwlwifi, openSUSE
> Tumbleweed, kernel 6.18, AppArmor enforcing, firewalld. Parsers and
> diagnosis are covered by tests against captured hardware output; the
> start/stop path needs testing on more radios and distributions.
> [Reports of radios it gets wrong](CONTRIBUTING.md) are the most useful
> thing you can send.

## Why another one

`create_ap`, `linux-wifi-hotspot` and `nmcli device wifi hotspot` each solve
part of the problem. hotspotd takes what each does well and adds the part all
of them skip: **finding out whether an AP can run here at all, before trying.**

| | good idea we keep | gap we close |
|---|---|---|
| `create_ap` | virtual AP interface, so you can share the WiFi you are *connected to* | unmaintained; writes its config to `/tmp`, which AppArmor denies to hostapd |
| `nmcli hotspot` | NetworkManager integration, persistent profiles | takes over the physical device, dropping the uplink you wanted to share |
| `linux-wifi-hotspot` | friendly options | inherits create_ap's config-path problem |
| **all of them** | — | no capability, regulatory or MAC-policy diagnosis; failures surface as unrelated errors |

## The two failures that motivated this

Both were found by debugging a hotspot that had never once worked.

### 1. AppArmor silently hides the config from hostapd

The openSUSE profile for hostapd grants config reads through exactly one rule:

```
/etc/hostapd.* r,
```

In AppArmor a single `*` **does not cross `/`**. So that rule allows
`/etc/hostapd.conf` but denies `/etc/hostapd/anything.conf` — and denies
`/tmp` entirely, which is where create_ap and its forks generate their config.

What the user sees:

```
Could not open configuration file '/tmp/create_ap.wlo1.conf.2or5y8UB/hostapd.conf'
```

The file is there, root owns it, permissions are fine. The real cause appears
only in the audit log:

```
apparmor="DENIED" operation="open" profile="hostapd" \
  name="/tmp/create_ap.wlo1.conf.2or5y8UB/hostapd.conf" \
  requested_mask="r" denied_mask="r"
```

hotspotd parses the active profile, works out which paths the policy actually
permits, and writes there. The same finding was reported upstream as
[linux-wifi-hotspot#524](https://github.com/lakinduakash/linux-wifi-hotspot/issues/524)
and fixed there in
[#532](https://github.com/lakinduakash/linux-wifi-hotspot/pull/532).

### 2. Channel constraints that no tool explains

Intel's AX2xx radios report:

```
valid interface combinations:
  * #{ managed } <= 1, #{ AP, P2P-client, P2P-GO } <= 1, ... #channels <= 1
```

`#channels <= 1` means a client connection and an AP may coexist **only on the
same channel**. Meanwhile, under the world regulatory domain (`country 00`)
most 5GHz channels are flagged `no IR` — the radio may associate but must
never initiate radiation, which is precisely what beaconing is.

Put together: while associated on 5GHz channel 48, an AP *cannot* start —
not on 48 (no-IR) and not on any other channel (single-channel limit). The
tools respond with `Your adapter can not transmit to channel 48` or nothing at
all. Neither says the fix is to associate on 2.4GHz first.

`hotspotd doctor` says exactly that.

## Usage

```console
$ sudo hotspotd doctor                 # can an AP run here at all?
$ sudo hotspotd up Home                # passphrase is prompted for, not typed into ps
$ sudo hotspotd status
$ sudo hotspotd down
```

```console
$ sudo hotspotd status
✓ Home up for 12m 4s
    channel 6 (2.4GHz), WPA2
    ap0 192.168.12.1/24, NAT through wlo1
    2 clients:
      16:91:1b:04:e8:e9  192.168.12.2    phone                -63 dBm
      aa:bb:cc:dd:ee:ff  192.168.12.3    laptop               -48 dBm
```

Keep a hotspot and bring it back after a reboot:

```console
$ sudo hotspotd up Home --save         # remembers it in /etc/hotspotd/hotspotd.conf
$ sudo hotspotd enable                 # and starts it at boot
$ sudo hotspotd up                     # from now on, no arguments needed
```

Useful flags: `--open` (no encryption), `--channel N`, `--hidden`,
`--subnet 10.42.0`, `--uplink eth0`, `--no-nat`, `--no-dhcp`,
`--interface wlan1`, `--ap-interface ap1`. Options work before or after the
command. `doctor` and `status` take `--json`. Full details in
`man hotspotd`.

`hotspotd up` defaults to the channel the uplink is already using, because on
single-channel radios that is the only one that can work.

## Requirements

`hostapd`, `iw`, `iproute2`, `dnsmasq`, and either firewalld or `nft` for NAT.
Python 3.9+, **standard library only** — no runtime dependencies, no build
step. That is deliberate: hotspotd has to work on a machine whose network is
down, which is exactly when a package manager cannot fetch anything.

## Install

```sh
sudo make install       # binary, man page, systemd unit, shell completion
sudo make uninstall
make test               # 53 tests, no pytest needed
```

`PREFIX`, `DESTDIR` and `SYSTEMDDIR` are honoured, so distribution packaging
needs no patches. `pip install .` also works if you only want the command.

## How it works

```
doctor ── caps.py ──── iw list ......... modes, channels, regulatory flags,
   │                                     interface combinations
   ├──── confine.py ── AppArmor/SELinux . which config paths hostapd may read
   └──── doctor.py ... pure function of the facts above, so it is testable
                       against captured hardware

up ──── backend.py ─── virtual AP interface (the uplink survives)
   │                   hostapd as a transient systemd unit
   │                   dnsmasq for DHCP/DNS, firewalld or nftables for NAT
   └──── state.py ──── every change recorded as it is made

down ─── state.py ──── undo exactly those changes, and nothing else
```

Two design decisions carry most of the weight:

**`doctor.diagnose()` does no I/O.** It takes facts and returns findings. That
is what lets the suite test radios the author does not own, from captured
`iw list` output. Contributions of fixtures from other chipsets are
especially welcome.

**Nothing is undone on the basis of a default value.** Every change `up` makes
is written to `/run/hotspotd/state.json` the moment it succeeds, so `down`
reverses precisely those. Masquerading is enabled only if it was off, and
turned back off only if hotspotd was the one that turned it on — a machine
already sharing another connection through that firewall zone must not lose
it when the hotspot stops.

## Roadmap

- [x] `--json` output for scripting
- [x] Persistent profile and a systemd unit
- [x] Offer the beacon-capable channels when the current one is the blocker
- [ ] Switch the uplink band automatically when that is the only blocker
- [ ] IPv6, client isolation, MAC filtering
- [ ] Verify the AppArmor finding on Debian/Ubuntu and Fedora/SELinux
- [ ] Distribution packages (AUR, openSUSE, Debian, Fedora, Nix)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: if hotspotd gets
your radio wrong, send `hotspotd doctor --json` and `iw list` — that becomes
a test case.

## License

MIT — see [LICENSE](LICENSE).
