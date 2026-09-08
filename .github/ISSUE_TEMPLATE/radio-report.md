---
name: hotspotd got my radio wrong
about: doctor said the wrong thing, or the hotspot failed for a reason it did not name
labels: radio-report
---

**What happened**

<!-- What you ran, and what you expected instead. -->

**Attach these three**

```sh
sudo hotspotd doctor --json > doctor.json
sudo iw list > iw-list.txt
sudo iw reg get > iw-reg.txt
```

**System**

- Distribution and version:
- Kernel (`uname -r`):
- WiFi chipset and driver (`lspci -k | grep -A3 -i network` or `lsusb`):
- hostapd version:
- AppArmor / SELinux enforcing?
