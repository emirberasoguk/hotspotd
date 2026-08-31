# hotspotd

A WiFi access point manager for Linux that tells you **why** it can't start —
instead of failing with a message that points somewhere else.

> Status: **v0.1.0-dev**, early. Verified end to end on one machine
> (Intel AX201 / iwlwifi, openSUSE Tumbleweed, kernel 6.18, AppArmor).
> Parsers are covered by tests against captured hardware output; the
> start/stop path needs testing on more radios and distributions.

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
permits, and writes there.

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
$ sudo hotspotd doctor
hotspotd doctor  (wlo1)
  ✓ AP mode supported
  ! Regulatory domain is unset (00 / world)
  ✓ 18 channels permit beaconing
      2.4GHz: 1-13; 5GHz: 149, 153, 157, 161, 165
  ! Client and AP must share one channel
  ✗ Channel 48 cannot host an AP
      no-IR: may associate but not initiate radiation (no beaconing) - and this
      radio requires the AP to share the uplink's channel...
      fix: Associate on a channel that permits beaconing (2.4GHz: 1-13) and retry.
  ✓ hostapd confined by AppArmor (enforced)
  ✓ Config path satisfies the policy   /etc/hostapd.hotspotd.conf

blocked - fix the ✗ items above
```

```console
$ sudo hotspotd up --ssid MyAP --password 'a good passphrase'
$ sudo hotspotd status
$ sudo hotspotd down
```

`hotspotd up` defaults to the channel the uplink is already using, because on
single-channel radios that is the only one that can work.

## Requirements

`hostapd`, `iw`, `iproute2`, `dnsmasq`, and either firewalld or `nft` for NAT.
Python 3.9+, standard library only — no runtime dependencies, no build step.

## Install

```sh
sudo make install        # /usr/local/lib/hotspotd + /usr/local/bin/hotspotd
sudo make uninstall
make test                # no pytest needed
```

## How it works

```
doctor ── caps.py ──── iw list ......... modes, channels, regulatory flags,
   │                                     interface combinations
   ├──── confine.py ── AppArmor/SELinux . which config paths hostapd may read
   └──── doctor.py ... pure function of the facts above, so it is testable
                       against captured hardware

up ──── backend.py ─── virtual __ap interface (uplink survives)
                       hostapd as a transient systemd unit
                       dnsmasq for DHCP/DNS, firewalld or nft for NAT
```

`doctor.diagnose()` takes facts and returns findings — no I/O. That is what
lets the suite test radios the author does not own, from captured `iw list`
output. Contributions of fixtures from other chipsets are especially welcome.

## Roadmap

- [ ] Offer to switch the uplink to a beacon-capable band when that is the blocker
- [ ] `--json` output for scripting
- [ ] Persistent profiles and a systemd unit
- [ ] IPv6, client isolation, MAC filtering
- [ ] Verify the AppArmor finding on Debian/Ubuntu and Fedora/SELinux
- [ ] Upstream the config-path fix to `linux-wifi-hotspot`

## License

MIT — see [LICENSE](LICENSE).
