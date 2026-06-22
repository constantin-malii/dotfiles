# homebrain — Home Assistant OS VM Setup & Architecture Reference

**Host:** `homebrain` (`costea@192.168.1.68`)
**Document created:** 2026-06-21
**Author:** Setup performed via Claude Code, driven by Constantin (constantin@symend.com)
**Scope:** Standing up a modern Home Assistant OS (HAOS) VM under KVM/libvirt while preserving the existing Plex server and legacy Home Assistant Core install. No host OS upgrade, no destructive changes.

---

## 1. Executive summary

A new **Home Assistant OS 18.0** virtual machine (`haos`) now runs under KVM/libvirt on the `homebrain` media server. It boots via UEFI on the host's existing (2016-era) QEMU/libvirt stack, attaches to the LAN via **macvtap** (so it gets a real `192.168.1.x` address), and is set to **autostart** with the host.

Both pre-existing workloads were left **completely untouched and running**:
- **Plex Media Server** (`plexmediaserver`, user `plex`)
- **Legacy Home Assistant Core** (`home-assistant@costea.service`, listening on host `192.168.1.68:8123`)

The new HAOS instance and the old HA Core run **in parallel** with no port/IP conflict, enabling a migrate-at-your-own-pace cutover.

---

## 2. Host inventory (as found)

| Property | Value |
|---|---|
| Hostname | `homebrain` |
| Machine ID | `14c3e5a447bf6b2a80df28ac571bdf08` |
| OS | Ubuntu 16.04.7 LTS (Xenial) — **EOL** |
| Kernel | `4.4.0-210-generic` |
| CPU | Intel Core i7-4770 @ 3.40 GHz — 4 cores / 8 threads |
| Virtualization | **VT-x** present; `kvm_intel` loaded; `/dev/kvm` present |
| RAM | 7.7 GiB total |
| Swap | 7.9 GiB on `/dev/sdb5` |

> **Note:** Ubuntu 16.04 is end-of-life. Per project constraints the host OS was **not** upgraded. apt packages come from `xenial-updates` (mirrors still reachable at time of setup).

### CPU virtualization verification
```
egrep -c '(vmx|svm)' /proc/cpuinfo      # -> 8
lsmod | grep kvm                         # kvm_intel, kvm, irqbypass loaded
ls -l /dev/kvm                           # crw-rw---- root kvm
```

---

## 3. Storage layout

| Device | Model | Size | Partition | FS | Mount | Notes |
|---|---|---|---|---|---|---|
| `sda` | WDC WD2002FAEX (HDD) | 1.8 TB | `sda1` | ext3 | `/media/MediaServerData` | **94 % full** — Plex media. Avoid for VMs. |
| `sdb` | Samsung SSD SM84 | 119 GB | `sdb1` | ext4 | `/` | VM images live here |
| | | | `sdb5` | swap | `[SWAP]` | |

- Root SSD (`/`) free space: **~44 GB at start → ~39 GB after VM provisioning**.
- VM disk image: `/var/lib/libvirt/images/haos.qcow2` (32 GiB virtual, ~1 GiB allocated, grows as used).
- **Capacity watch:** the SSD is the constraint. Monitor with `df -h /`. The HAOS qcow2 can grow toward 32 GiB; keep an eye as add-ons/backups accumulate.

---

## 4. Networking

### Host networking (unchanged)
- Single physical NIC **`eno1`** — **static** config via classic `ifupdown` (no netplan on 16.04).
  - Address `192.168.1.68/24`, gateway `192.168.1.254`, DNS `8.8.8.8`
  - Config: `/etc/network/interfaces` (`iface eno1 inet static`)
- **NetworkManager is installed but does NOT manage `eno1`** (`eno1` shows `unmanaged`). NM only owns `virbr0`. This is why no NM conflict arises from VM networking.
- **libvirt default NAT network** `virbr0` = `192.168.122.0/24` (active, autostart). Used only for the throwaway boot test; the production VM does **not** use it.

### VM networking — macvtap (chosen approach)
- The `haos` VM attaches directly to `eno1` via **macvtap in bridge mode** (`<interface type='direct'>`, `source dev='eno1' mode='bridge'`).
- Result: the VM gets its own LAN IP from the router → **`192.168.1.104`** (MAC `52:54:00:ab:cd:10`). Inside the guest the NIC enumerates as `emp2s1`.
- **Why macvtap and not a host bridge?** The host has a single NIC and is administered **remotely with no console**. Rebuilding `eno1` into a `br0` bridge risks an unrecoverable lockout. macvtap delivers LAN presence (mDNS/discovery work) with **zero changes to host networking** — the safest option here.
- **macvtap caveat (important):** by design, the **host (`192.168.1.68`) cannot directly reach the guest (`192.168.1.104`)** and vice-versa. Every *other* device on the LAN can. So:
  - Manage/onboard HA from another LAN device (e.g. a workstation), **not** by curling from `homebrain` itself.
  - To verify the guest from the host, use the VNC console / `virsh screenshot` (see Runbook).

---

## 5. Service map

| Service | Type | Runs as | Address | Autostart | Touched? |
|---|---|---|---|---|---|
| **Plex Media Server** 1.18.8.2527 | systemd `plexmediaserver` | `plex` | host `192.168.1.68` (Plex ports) | yes | **No** |
| **Legacy HA Core** | systemd `home-assistant@costea` (`/usr/local/bin/hass`, venv/pip) | `costea` | host `192.168.1.68:8123` | enabled | **No** |
| **New HAOS 18.0 VM** | libvirt domain `haos` | libvirt/QEMU | LAN `192.168.1.104:8123` | enabled | new |

- Legacy HA config dir: `/home/costea/.homeassistant`.
- The two HA instances do **not** conflict: old = `192.168.1.68:8123`, new = `192.168.1.104:8123` (different IPs).
- **Docker is NOT installed** on the host — the legacy HA is a Core/venv install, not a container.

---

## 6. Virtualization stack (as found — all pre-installed except OVMF)

| Component | Version | Notes |
|---|---|---|
| QEMU | 2.5.0 (`1:2.5+dfsg-5ubuntu10.51`) | 2016-era; **proven to boot HAOS 18.0** (see §8) |
| libvirt | 1.3.1 (`libvirt-bin`) | `libvirtd` enabled + active |
| virtinst | 1.3.2 | |
| OVMF (UEFI firmware) | `0~20160408.ffea0a2c-2ubuntu0.2` | **Installed during this setup** (was missing) |
| bridge-utils | 1.5 | present (unused — macvtap chosen) |

- **`costea` is a member of the `libvirtd` group** → can run `virsh -c qemu:///system ...` and manage VMs **without sudo** (privileged ops execute inside the root libvirt daemon).
- OVMF files: `/usr/share/OVMF/OVMF_CODE.fd` (firmware, read-only) and `/usr/share/OVMF/OVMF_VARS.fd` (writable NVRAM template). 2 MB build, no Secure Boot — fine for HAOS.

---

## 7. The HAOS VM — canonical configuration

- **Domain name:** `haos`  •  **UUID:** `295a0ee7-0bb0-4e5f-aff2-148a7837c174`
- **Resources:** 2 vCPU (`host-passthrough`), 2048 MiB RAM
- **Firmware:** UEFI pflash — loader `/usr/share/OVMF/OVMF_CODE.fd`, NVRAM `/home/costea/haos_VARS.fd`
- **Machine type:** `pc-q35-2.5`
- **Disk:** `/var/lib/libvirt/images/haos.qcow2` (qcow2, 32 GiB, `bus=virtio`, `cache=none`)
- **Network:** macvtap direct on `eno1` (bridge mode), `model=virtio`, MAC `52:54:00:ab:cd:10`
- **Graphics:** VNC bound to `127.0.0.1:5900` (localhost-only; tunnel over SSH to view)
- **Console:** serial pty
- **Autostart:** enabled  •  **on_reboot/on_crash:** restart

### Definition source files (on host)
| File | Purpose | Keep? |
|---|---|---|
| `/home/costea/haos.xml` | The domain definition used to `virsh define` | Yes (source of truth / re-provision) |
| `/home/costea/haos_VARS.fd` | Live UEFI NVRAM (now owned `libvirt-qemu:kvm`) | **Yes — do not delete** |
| `/var/lib/libvirt/images/haos.qcow2` | VM disk | Yes (the VM) |
| `/home/costea/haos_ova-18.0.qcow2.xz` | Pristine HAOS 18.0 image (compressed) | Optional — kept for re-provisioning |

### Canonical live domain XML (`virsh dumpxml haos`)
```xml
<domain type='kvm'>
  <name>haos</name>
  <uuid>295a0ee7-0bb0-4e5f-aff2-148a7837c174</uuid>
  <memory unit='KiB'>2097152</memory>
  <currentMemory unit='KiB'>2097152</currentMemory>
  <vcpu placement='static'>2</vcpu>
  <os>
    <type arch='x86_64' machine='pc-q35-2.5'>hvm</type>
    <loader readonly='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE.fd</loader>
    <nvram>/home/costea/haos_VARS.fd</nvram>
    <boot dev='hd'/>
  </os>
  <features><acpi/><apic/></features>
  <cpu mode='host-passthrough'/>
  <clock offset='utc'/>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>restart</on_crash>
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' cache='none'/>
      <source file='/var/lib/libvirt/images/haos.qcow2'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <interface type='direct'>
      <mac address='52:54:00:ab:cd:10'/>
      <source dev='eno1' mode='bridge'/>
      <model type='virtio'/>
    </interface>
    <serial type='pty'><target port='0'/></serial>
    <console type='pty'><target type='serial' port='0'/></console>
    <graphics type='vnc' port='5900' autoport='yes' listen='127.0.0.1'/>
    <video><model type='vga' vram='16384' heads='1'/></video>
    <memballoon model='virtio'/>
  </devices>
</domain>
```
*(USB/PCIe/SATA controllers and PCI addresses are auto-generated by libvirt and omitted here for clarity; see `virsh dumpxml haos` for the fully expanded form.)*

### Storage pool (`virsh pool-dumpxml default`)
```xml
<pool type='dir'>
  <name>default</name>
  <uuid>2153fd01-85fe-4380-882e-cea890e11711</uuid>
  <target>
    <path>/var/lib/libvirt/images</path>
    <permissions><mode>0711</mode><owner>0</owner><group>0</group></permissions>
  </target>
</pool>
```
Pool is **active + autostart**.

---

## 8. What was performed (chronological)

1. **Established SSH access.** Resolved a key-auth failure (see §9). Server-side `~/.ssh` perms were corrected to `700`/`600` (StrictModes). Connection works via ssh-agent.
2. **Read-only inventory.** Host, CPU/VT-x, memory, disks, networking, libvirt/KVM state, and running services — all captured (this document).
3. **Phase 0 — prerequisites.**
   - Installed UEFI firmware: `sudo apt-get install -y ovmf` (the only sudo used; reversible).
   - Defined + started + autostarted the `default` dir storage pool on the SSD (`/var/lib/libvirt/images`). No sudo (via libvirtd group).
4. **Phase 1 — disposable boot test (de-risking the old QEMU/OVMF).**
   - Downloaded HAOS 18.0 KVM image `haos_ova-18.0.qcow2.xz`, decompressed (32 GiB virtual / ~1 GiB actual).
   - Built a throwaway q35/UEFI VM on the **NAT** network (so the host could verify it).
   - **Result: PASS.** HAOS booted in ~20 s, pulled a DHCP lease as `homeassistant`, and `:8123` returned HTTP 200. Confirmed via `virsh screenshot` (HA boot console).
   - Tore the test VM down.
5. **Phase 2 — production VM.**
   - Staged a **pristine** disk into the SSD pool with **no sudo** using `virsh vol-create-as` + `virsh vol-upload`.
   - Seeded UEFI NVRAM from the OVMF template into `/home/costea/haos_VARS.fd`.
   - Defined domain `haos` with **macvtap on `eno1`**, enabled autostart, started it.
   - VM came up as **HAOS 18.0** with LAN IP **`192.168.1.104`**.
6. **Cleanup & verification.** Removed redundant staging files (~2 GB reclaimed). Confirmed Plex and legacy HA Core still **active** and untouched.

---

## 9. SSH access — important quirk

The local workstation runs a **bleeding-edge OpenSSH client (10.x; emits a post-quantum KEX warning)** against the host's old OpenSSH 7.2 server. **Direct key auth fails**:

- `ssh -i ~/.ssh/id_homebrain costea@192.168.1.68` → the client receives the server's `PK_OK` ("Server accepts key"), then logs `we did not send a packet, disable method` and never transmits the signature. Server logs only `Connection closed [preauth]` (no `Failed publickey`).
- The key itself is valid (matches `authorized_keys`; `ssh-keygen -Y sign` works). The failure is in the client's direct-file signing path.

**Working method — route signing through ssh-agent:**
```bash
ssh-add ~/.ssh/id_homebrain          # once per login session
ssh costea@192.168.1.68 '<command>'  # no -i flag
```
The agent socket (`SSH_AUTH_SOCK`) is provided by the shell profile and persists; the loaded identity persists in the agent process.

**Key:** `~/.ssh/id_homebrain` (ed25519). Server-side `authorized_keys` perms must remain `~/.ssh`=700, `authorized_keys`=600, home not group/world-writable (StrictModes).

---

## 10. Operations runbook

> All `virsh` commands use the system connection. Prefix every session with `ssh-add ~/.ssh/id_homebrain`.

### Lifecycle
```bash
ssh costea@192.168.1.68 'virsh -c qemu:///system list --all'              # status
ssh costea@192.168.1.68 'virsh -c qemu:///system start haos'              # start
ssh costea@192.168.1.68 'virsh -c qemu:///system shutdown haos'           # graceful stop (ACPI)
ssh costea@192.168.1.68 'virsh -c qemu:///system destroy haos'            # force stop (pull plug)
ssh costea@192.168.1.68 'virsh -c qemu:///system dominfo haos'            # details
ssh costea@192.168.1.68 'virsh -c qemu:///system autostart haos'          # (already enabled)
```

### See the console (host can't reach the macvtap guest over IP)
```bash
# Screenshot the graphical console:
ssh costea@192.168.1.68 'virsh -c qemu:///system screenshot haos /home/costea/s.ppm && convert /home/costea/s.ppm /home/costea/s.png'
scp costea@192.168.1.68:/home/costea/s.png .        # then view locally

# Or view VNC (bound to 127.0.0.1:5900 on the host) via an SSH tunnel:
ssh -L 5901:127.0.0.1:5900 costea@192.168.1.68
#   then point a VNC client at localhost:5901
```

### Access Home Assistant (from any LAN device that is NOT the host)
- `http://192.168.1.104:8123`  or  `http://homeassistant.local:8123`

### Editing the VM definition
```bash
ssh costea@192.168.1.68 'virsh -c qemu:///system edit haos'   # then restart the VM
```

### Backups
- **HA-level (recommended):** use Home Assistant's built-in **Settings → System → Backups** (and/or a backup add-on to push off-box). This is the portable, supported path.
- **VM disk snapshot (host-level, VM stopped):**
  ```bash
  ssh costea@192.168.1.68 'virsh -c qemu:///system shutdown haos'   # wait until off
  ssh costea@192.168.1.68 'cp --reflink=auto /var/lib/libvirt/images/haos.qcow2 /home/costea/haos-backup-$(date +%F).qcow2'  # needs space; may require sudo to read pool file
  ```
  (Disk lives in a `0711` root-owned pool dir; reading it directly may need sudo. Prefer HA-level backups.)

### Updating HAOS
- Update **in-place from the HA UI** (Settings → System → Updates) — the supported path; survives reboots and keeps your config.
- Do **not** replace the qcow2 to "update" — that would wipe config.

---

## 11. Disaster recovery — re-provision the VM from scratch

If the domain definition is lost (disk intact), redefine from the kept XML:
```bash
ssh costea@192.168.1.68 'virsh -c qemu:///system define /home/costea/haos.xml && virsh -c qemu:///system autostart haos && virsh -c qemu:///system start haos'
```

Full rebuild (new blank HAOS) — summary of the proven procedure:
```bash
# 0. prereq (once): sudo apt-get install -y ovmf
# 1. fetch latest HAOS KVM image (run on host; writes to home):
cd /home/costea
LATEST=$(curl -sL https://api.github.com/repos/home-assistant/operating-system/releases/latest | grep tag_name | grep -oE '[0-9]+\.[0-9]+')
wget -O haos.qcow2.xz "https://github.com/home-assistant/operating-system/releases/download/$LATEST/haos_ova-$LATEST.qcow2.xz"
unxz -kc haos.qcow2.xz > haos-src.qcow2
# 2. stage disk into the SSD pool WITHOUT sudo:
virsh -c qemu:///system vol-create-as default haos.qcow2 34359738368 --format qcow2
virsh -c qemu:///system vol-upload --pool default haos.qcow2 /home/costea/haos-src.qcow2
# 3. seed UEFI NVRAM (writable copy in a costea-owned path):
cp /usr/share/OVMF/OVMF_VARS.fd /home/costea/haos_VARS.fd
# 4. define from /home/costea/haos.xml (see §7), then:
virsh -c qemu:///system define /home/costea/haos.xml
virsh -c qemu:///system autostart haos
virsh -c qemu:///system start haos
```

---

## 12. Constraints, risks & gotchas (lessons learned)

- **EOL host / old hypervisor.** Ubuntu 16.04, QEMU 2.5, libvirt 1.3.1, OVMF 2016. HAOS 18.0 boots fine **today**, but future HAOS releases could eventually require newer firmware/QEMU. The boot test is the canary — re-run a disposable boot test before any major HAOS jump if concerned.
- **libvirt 1.3.1 does NOT auto-create UEFI NVRAM** from a `<nvram template=...>` attribute, and `/var/lib/libvirt/qemu/nvram/` is root-only. Workaround used: pre-seed an NVRAM copy into a `costea`-writable path (`/home/costea/haos_VARS.fd`) and reference it directly (no `template` attribute).
- **`virsh undefine` of a UEFI domain requires `--nvram`** (this version has no `--keep-nvram`).
- **macvtap host↔guest isolation** (see §4) — manage HA from another LAN device; use VNC/screenshot from the host.
- **SSD is the space constraint** — `df -h /`. The media HDD (`sda`) is 94 % full and intentionally not used for VMs.
- **No sudo for VM lifecycle** thanks to `libvirtd` group membership; the only sudo used in setup was the one-time `apt install ovmf`. `costea` sudo requires a password + TTY (not NOPASSWD).
- **Constraints honored:** no host OS upgrade, Plex untouched, legacy HA untouched, nothing deleted.

---

## 13. Outstanding / recommended follow-ups

1. **Pin the VM's IP** — add a DHCP reservation on the router for MAC `52:54:00:ab:cd:10` so it stays at `192.168.1.104` (macvtap relies on the router's DHCP).
2. **Onboard** the new HA at `http://192.168.1.104:8123` from a LAN device.
3. **Migrate** automations/integrations/config from the legacy Core (`/home/costea/.homeassistant`) to HAOS, then **decommission** `home-assistant@costea` when satisfied:
   `sudo systemctl disable --now home-assistant@costea` *(left running until you decide).*
4. **Consider raising VM RAM** (e.g. 3–4 GiB) if you add many add-ons — host has headroom; edit with `virsh edit haos` and restart.
5. **Set up off-box HA backups** (HA UI backups + a sync add-on, or copy snapshots off the SSD).

---

## 14. Quick-reference card

| Item | Value |
|---|---|
| Host SSH | `ssh-add ~/.ssh/id_homebrain` → `ssh costea@192.168.1.68` |
| VM name / UUID | `haos` / `295a0ee7-0bb0-4e5f-aff2-148a7837c174` |
| VM IP / MAC | `192.168.1.104` / `52:54:00:ab:cd:10` |
| HA URL | `http://192.168.1.104:8123` (or `homeassistant.local:8123`) |
| VM disk | `/var/lib/libvirt/images/haos.qcow2` (32 GiB qcow2) |
| VM NVRAM | `/home/costea/haos_VARS.fd` (do not delete) |
| VM definition | `/home/costea/haos.xml` |
| Pristine image | `/home/costea/haos_ova-18.0.qcow2.xz` |
| Legacy HA | `home-assistant@costea` → `192.168.1.68:8123`, config `/home/costea/.homeassistant` |
| Plex | `plexmediaserver` (user `plex`), host `192.168.1.68` |
| virt mgmt | `virsh -c qemu:///system <cmd> haos` (no sudo; `libvirtd` group) |
