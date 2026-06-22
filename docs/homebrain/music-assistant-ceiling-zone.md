# Music Assistant — Ceiling-Speaker Zone

**Host:** `homebrain` (`costea@192.168.1.68`, Ubuntu 16.04) · **VM:** `haos` (HAOS 18.0 / HA Core 2026.6.4, `192.168.1.104`)
**Built:** 2026-06-22 · **Status:** ✅ working (verified with internet radio through the ceiling speakers)
**Related:** `haos-vm-deployment.md`, `homebrain-architecture.md`. SSH access = ssh-agent method (see architecture doc §9).

---

## 1. What this is

Music Assistant (running as a HAOS add-on inside the VM) plays audio to the **ceiling speakers**, which are driven by the **Ubuntu host's analog output**. Because the host has no audio-capable player of its own and MA lives in the VM, a lightweight **Squeezelite** player runs on the host and registers with MA over the network.

**Audio path:**
```
Music Assistant (VM)
   │  SlimProto control (TCP 3483) + audio stream (HTTP 8097)  ── over NAT 192.168.122.10
   ▼
Squeezelite (Ubuntu host, systemd service)
   │  ALSA hw:1,0  (onboard PCH analog out)
   ▼
amplifier ──▶ ceiling speakers
```

MA player entity in HA: **`media_player.ceiling_speakers`**.

---

## 2. The core obstacle and the solution

The VM's primary NIC uses **macvtap** (LAN `192.168.1.104`), which by design **blocks all host↔VM traffic** (the host can reach every *other* LAN device, just not its own guest). A host-side player therefore couldn't reach MA.

**Solution (reversible, VM-only — never touches `eno1`/host LAN/SSH):** add a **second VM NIC on libvirt's `default` NAT network**, with a static lease. The host (gateway `192.168.122.1` for `virbr0`) can reach VMs on that network.

| VM NIC | Network | MAC | Address | Purpose |
|---|---|---|---|---|
| `macvtap0` | direct on `eno1` | `52:54:00:ab:cd:10` | `192.168.1.104` (LAN) | LAN presence, device discovery, user access |
| `vnet0` | libvirt `default` (NAT) | `52:54:00:ab:cd:20` | **`192.168.122.10`** (static) | host↔VM (control + audio stream) |

Host→VM reachability over NAT (confirmed): `8123` (HA), `8095` (MA API/UI), `8097` (MA stream server), `3483` (SlimProto) — all OPEN.

---

## 3. Critical setting: MA stream-server publish IP

MA's stream server defaults to publishing on the VM's primary IP (`192.168.1.104`, macvtap) — **unreachable from the host**, so Squeezelite could connect (control) but never fetch audio (silent, position stuck at 0).

**Fix:** MA UI → **Settings → System → Streams → publish IP = `192.168.122.10`**.

- ✅ Host Squeezelite fetches `192.168.122.10:8097`.
- ✅ AirPlay devices (e.g. the Samsung soundbar) are unaffected — AirPlay is push-based and doesn't use this fetch URL.
- ⚠️ A LAN-side *fetch* player (Chromecast/DLNA) would then need the LAN IP instead — revisit only if you add one (clean long-term answer: a host macvlan shim).

---

## 4. Host audio

- Ceiling speakers → host **analog out**, ALSA device **`hw:1,0`** (card 1 `[PCH]`, `HDA Intel PCH`). (Card 0 `[HDMI]` is for displays.)
- No PulseAudio / desktop session runs on the host, so Squeezelite owns the ALSA device exclusively — no contention.
- Hardware verified with: `sudo aplay -D hw:1,0 /usr/share/sounds/alsa/Front_Center.wav` (sound came out).
- Note: `costea` is **not** in the `audio` group; the player runs as **root** to access `hw:1,0` directly (fine for a headless appliance).

---

## 5. Squeezelite service (on the host)

Installed: `sudo apt-get install -y squeezelite` (v1.8). The packaged default service is disabled in favor of a custom unit.

**`/etc/systemd/system/squeezelite-ceiling.service`:**
```ini
[Unit]
Description=Squeezelite - Music Assistant ceiling zone
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/squeezelite -o hw:1,0 -n "Ceiling Speakers" -s 192.168.122.10 -C 5
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```
- `-o hw:1,0` output device · `-n "Ceiling Speakers"` player name in MA · `-s 192.168.122.10` MA SlimProto server (NAT) · `-C 5` release the ALSA device after 5 s idle.
- Enabled on boot: `sudo systemctl enable --now squeezelite-ceiling`.

---

## 6. Music Assistant configuration

- Add-on: **Music Assistant** `d5369777_music_assistant` v2.9.3 (installed via `ha apps install`; the Supervisor panel is missing so the add-on store/CLI was used directly).
- **SlimProto / "Squeezelite players" provider enabled** (MA UI → Settings → Providers) → MA listens on `3483`, registers the host's squeezelite as a player.
- The ceiling player is a MA **Universal player** (`upf8b156c25101`) wrapping the Squeezelite protocol player (host MAC `f8:b1:56:c2:51:01`).
- Stream publish IP set to `192.168.122.10` (see §3).

---

## 7. VM resources

Raised from 2 GiB/2 vCPU → **4 GiB RAM / 3 vCPU** (MA recommends ≥4 GB for HA + the add-on; host has headroom). This resolved repeated **30-second playback-lock timeouts** / sluggishness.

```bash
# applied via virsh (VM off), reversible:
virsh -c qemu:///system setmaxmem haos 4194304 --config
virsh -c qemu:///system setmem    haos 4194304 --config
virsh -c qemu:///system setvcpus  haos 3 --maximum --config
virsh -c qemu:///system setvcpus  haos 3 --config
```

---

## 8. Management

> Prefix with `ssh-add ~/.ssh/id_homebrain`; `virsh` needs no sudo (libvirtd group).

```bash
# Squeezelite service (host):
ssh -t costea@192.168.1.68 'sudo systemctl status squeezelite-ceiling'
ssh -t costea@192.168.1.68 'sudo systemctl restart squeezelite-ceiling'
ssh costea@192.168.1.68 'journalctl -u squeezelite-ceiling -n 30 --no-pager'   # costea is in adm → no sudo

# Play to the ceiling zone (best done from the MA UI: select "Ceiling Speakers", play a track/station)
#   MA UI:  http://192.168.1.104:8095   (from a LAN device, not the host)

# Verify host↔VM NAT path:
ssh costea@192.168.1.68 'curl -s -m5 http://192.168.122.10:8095/info'
```

Day-to-day playback is via the **MA UI** or the **HA Music Assistant integration** (`media_player.*` services). The MA add-on web UI is reached directly at `http://192.168.1.104:8095` (the Supervisor "Open Web UI" panel is unavailable — see follow-ups).

---

## 9. Rollback

```bash
# Squeezelite (host):
sudo systemctl disable --now squeezelite-ceiling
sudo rm /etc/systemd/system/squeezelite-ceiling.service && sudo systemctl daemon-reload
sudo apt-get remove -y squeezelite        # optional

# NAT NIC (VM):
virsh -c qemu:///system detach-interface haos network --mac 52:54:00:ab:cd:20 --live --config
virsh -c qemu:///system net-update default delete ip-dhcp-host \
  "<host mac='52:54:00:ab:cd:20' name='haos-nat' ip='192.168.122.10'/>" --live --config

# VM resources back to 2 GiB / 2 vCPU:
virsh -c qemu:///system setmaxmem haos 2097152 --config
virsh -c qemu:///system setmem    haos 2097152 --config
virsh -c qemu:///system setvcpus  haos 2 --config
# (then a VM reboot for memory/vcpu changes)

# MA: remove the SlimProto provider and reset stream publish IP in the MA UI.
```

---

## 10. Known follow-ups (not blocking the ceiling zone)

1. **YouTube Music**: the *"not available"* errors were all for **one malformed/stale track ref** (`ytmusic--7MLPoF6b` — double dash, 8-char; real IDs are 11) coming from **empty restored library playlists** (`my-relax`, `500 Random tracks (from library)`, etc.), **not** a provider fault. Confirmed healthy: cookie auth (browses), and the `bgutil` PO-token generator mints valid tokens for real video IDs in <0.5 s. **Action:** play YTMusic via **Search** (real tracks resolve), not the stale restored playlists (delete those). Still pending: *hearing* a YTMusic search-track through a speaker (clean confirmation).
2. **HA ↔ MA integration** drops its connection (`ws://d5369777-music-assistant:8094`, internal-DNS hiccup) after any MA add-on or VM restart. Recovery: reload the Music Assistant config entry. Worth a permanent fix.
3. **Samsung soundbar** AirPlay fails via MA's legacy `CLIRaop` (it's an AirPlay-2 device) — try the AirPlay-2/Sendspin protocol/player.
4. **Supervisor `/hassio` panel missing** — `hassio` backend loads but the frontend panel doesn't register (see prior diagnostics). Manage add-ons via the `ha` CLI / direct URLs meanwhile.
5. **Single base/publish IP** — because host and LAN reach the VM via different IPs, only one stream-publish IP can be "right" at a time (currently the host/NAT). If a LAN fetch-player is ever needed, consider a host **macvlan shim** instead.

---

## 11. Verification record

- ALSA hardware: `aplay -D hw:1,0` → sound from ceiling speakers ✅
- Host→VM NAT: ports 8123/8095/8097/3483 reachable ✅
- End-to-end: **internet-radio station played through the ceiling speakers** ✅ (Squeezelite fetched `192.168.122.10:8097` and decoded to `hw:1,0`)
- No credentials are stored in this document. (The YTMusic login cookie lives only in MA; the diagnostic long-lived token used during setup was revoked afterward.)
