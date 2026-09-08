# Changelog

All notable changes to hotspotd are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-09

First release.

### Added
- `hotspotd doctor` - decides whether an access point can run on this machine
  *before* anything is touched, and names the constraint when it cannot: AP
  mode support, regulatory `no-IR` channels, single-channel interface
  combinations, and the AppArmor policy that hides a generated config from
  hostapd.
- `hotspotd up` - starts an access point on its own virtual interface, so the
  uplink being shared is not taken away. Passphrase is prompted for rather
  than passed on a command line visible in `ps`.
- `hotspotd down` - reverses exactly the changes that starting it made, read
  from `/run/hotspotd/state.json`, and nothing else.
- `hotspotd status` - the running hotspot, its uptime, and the associated
  clients with their addresses and host names.
- `hotspotd up --save`, `hotspotd enable`/`disable` and `hotspotd.service` -
  a saved profile in `/etc/hotspotd/hotspotd.conf` that the boot service
  reuses, so what starts at boot is what was tested by hand.
- `--json` output for `doctor` and `status`.
- The AP interface is declared unmanaged to NetworkManager *before* it is
  created, through a drop-in under `/etc/NetworkManager/conf.d` that is
  removed again when the hotspot stops. Asking afterwards is too late:
  NetworkManager claims a new wireless device the moment it appears, and while
  it holds it the kernel answers `ip link set up` with `EBUSY` - "Device or
  resource busy", which names neither NetworkManager nor the interface.
- NAT through firewalld when it is running, nftables otherwise. Masquerading
  is enabled only when it was off, and switched back off only if this run
  turned it on.
- man page, bash and zsh completion, systemd unit, `make install`, and a
  `pyproject.toml` for `pip install .`.

[0.1.0]: https://github.com/emirberasoguk/hotspotd/releases/tag/v0.1.0
