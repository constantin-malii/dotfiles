# HAOS VM — Deployment Documentation

**Host:** `homebrain` (`costea@192.168.1.68`, Ubuntu 16.04.7, QEMU 2.5 / libvirt 1.3.1)
**VM:** `haos` — Home Assistant OS 18.0
**Last updated:** 2026-06-21
**Companion doc:** `homebrain-architecture.md` (host inventory, networking, SSH access quirk, full setup chronology)

> **Access note:** SSH to this host needs the key loaded in ssh-agent (a client quirk — see the architecture doc).
> Prefix any session with: `ssh-add ~/.ssh/id_homebrain`  then `ssh costea@192.168.1.68 '<cmd>'`.
> All `virsh` commands use `qemu:///system` and need **no sudo** (`costea` is in the `libvirtd` group).

---

## 1. VM configuration (summary)

| Attribute | Value |
|---|---|
| Domain name | `haos` |
| UUID | `295a0ee7-0bb0-4e5f-aff2-148a7837c174` |
| Guest OS | Home Assistant OS 18.0 (x86-64 OVA qcow2) |
| Machine type | `pc-q35-2.5` (q35) |
| Firmware | UEFI (OVMF pflash) |
| vCPU | 2 (`host-passthrough`) |
| RAM | 2048 MiB (2 GiB) |
| Disk | `/var/lib/libvirt/images/haos.qcow2` — qcow2, 32 GiB virtual |
| NIC | macvtap (direct/bridge) on `eno1`, virtio, MAC `52:54:00:ab:cd:10` |
| LAN IP (DHCP) | `192.168.1.104` (guest iface `emp2s1`) |
| Graphics | VNC on `127.0.0.1:5900` (localhost-only) |
| Console | serial pty |
| Autostart | **enabled** |

---

## 2. CPU and memory allocation

- **vCPU:** 2, `placement='static'`, `<cpu mode='host-passthrough'/>` (exposes the i7-4770 features directly to the guest — best performance under KVM).
- **RAM:** 2048 MiB fixed (`<memory>` = `<currentMemory>` = 2097152 KiB). A virtio memballoon is present.
- Host has 7.7 GiB total with ample headroom; RAM can be raised (e.g. 3–4 GiB) via `virsh edit haos` → update `<memory>`/`<currentMemory>` → restart the VM.

```bash
# Change memory to 4 GiB at next boot (example):
ssh costea@192.168.1.68 'virsh -c qemu:///system setmaxmem haos 4194304 --config && virsh -c qemu:///system setmem haos 4194304 --config'
# then: shutdown + start  (or edit XML directly with: virsh edit haos)
```

---

## 3. Storage / disk location and size

- **Path:** `/var/lib/libvirt/images/haos.qcow2`
- **Format:** qcow2, **32 GiB virtual** capacity, ~1 GiB allocated at provisioning (thin — grows with use).
- **Backing storage:** the host **SSD** (`/dev/sdb1`, ext4, mounted `/`). At provisioning the SSD had ~39 GiB free — the **capacity constraint** for this VM. The 1.8 TB media HDD is 94% full and intentionally **not** used for VMs.
- **Storage pool:** libvirt dir pool `default` → target `/var/lib/libvirt/images` (active, autostart).

```bash
# Pool + volume status:
ssh costea@192.168.1.68 'virsh -c qemu:///system pool-list --all'
ssh costea@192.168.1.68 'virsh -c qemu:///system vol-list --pool default --details'
# Host SSD free space (watch this):
ssh costea@192.168.1.68 'df -h /'
```

---

## 4. Network configuration

- **Mode:** macvtap, `<interface type='direct'>` with `<source dev='eno1' mode='bridge'/>`, `model=virtio`.
- The VM bonds directly onto the host's only NIC `eno1` and pulls its own DHCP lease from the LAN router → **`192.168.1.104`** (MAC `52:54:00:ab:cd:10`).
- **Host networking is untouched** — `eno1` keeps its static `192.168.1.68/24` (classic `ifupdown`). NetworkManager does not manage `eno1`.
- **macvtap isolation (critical operational fact):** the **host `192.168.1.68` cannot directly reach the guest `192.168.1.104`** (and vice versa). All *other* LAN devices can. → Access/onboard Home Assistant from another LAN device; inspect the guest from the host only via VNC/screenshot.
- **Access HA UI** (from a LAN device, not the host): `http://192.168.1.104:8123` or `http://homeassistant.local:8123`.
- **Recommended:** add a **DHCP reservation** on the router for MAC `52:54:00:ab:cd:10` to pin `192.168.1.104`.

---

## 5. UEFI firmware configuration

- HAOS x86-64 is a **UEFI-only** image; the VM boots via OVMF pflash (not legacy BIOS).
- **Firmware (read-only):** `/usr/share/OVMF/OVMF_CODE.fd` (package `ovmf 0~20160408`, installed during setup).
- **NVRAM (writable, per-VM):** `/home/costea/haos_VARS.fd` — seeded from `/usr/share/OVMF/OVMF_VARS.fd`. Now owned `libvirt-qemu:kvm`.
  - **Do not delete `haos_VARS.fd`** — it holds the VM's UEFI variables/boot entries.
  - It lives in `/home/costea` (not the standard root-only `/var/lib/libvirt/qemu/nvram/`) because **libvirt 1.3.1 does not auto-create NVRAM from a `<nvram template=...>` attribute** and that dir is root-only. The workaround: a pre-seeded NVRAM file in a `costea`-writable path, referenced directly.

```xml
<os>
  <type arch='x86_64' machine='pc-q35-2.5'>hvm</type>
  <loader readonly='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE.fd</loader>
  <nvram>/home/costea/haos_VARS.fd</nvram>
  <boot dev='hd'/>
</os>
```

---

## 6. Startup behavior

- **Autostart: ENABLED** — the VM starts automatically when `libvirtd` starts at host boot.
- `on_poweroff=destroy`, `on_reboot=restart`, `on_crash=restart` (guest reboots/crashes restart the VM; a guest poweroff stops it).
- Boot time observed: HAOS reaches the LAN (DHCP) within ~20 s; the HA web UI (`:8123`) comes up shortly after Supervisor finishes.

```bash
# Verify/confirm autostart:
ssh costea@192.168.1.68 'virsh -c qemu:///system dominfo haos | grep Autostart'   # -> enable
# Toggle:
ssh costea@192.168.1.68 'virsh -c qemu:///system autostart haos'              # enable
ssh costea@192.168.1.68 'virsh -c qemu:///system autostart --disable haos'    # disable
```

---

## 7. Full VM XML configuration

Source definition kept at **`/home/costea/haos.xml`**. Canonical live form (`virsh dumpxml haos`) — auto-generated PCI/USB/SATA controller addresses included by libvirt are trimmed for readability:

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

---

## 8. Management commands

> Every line assumes `ssh-add ~/.ssh/id_homebrain` was run once this session.

### Start / stop / status
```bash
# Status of all domains:
ssh costea@192.168.1.68 'virsh -c qemu:///system list --all'

# Start:
ssh costea@192.168.1.68 'virsh -c qemu:///system start haos'

# Graceful shutdown (ACPI — preferred):
ssh costea@192.168.1.68 'virsh -c qemu:///system shutdown haos'

# Force off (only if it won't shut down — like pulling the plug):
ssh costea@192.168.1.68 'virsh -c qemu:///system destroy haos'

# Reboot (graceful) / reset (hard):
ssh costea@192.168.1.68 'virsh -c qemu:///system reboot haos'
ssh costea@192.168.1.68 'virsh -c qemu:///system reset haos'

# Detailed info:
ssh costea@192.168.1.68 'virsh -c qemu:///system dominfo haos'
```

### Inspect the console (host can't reach the macvtap guest over IP)
```bash
# Screenshot the graphical console -> view locally:
ssh costea@192.168.1.68 'virsh -c qemu:///system screenshot haos /home/costea/s.ppm && convert /home/costea/s.ppm /home/costea/s.png'
scp costea@192.168.1.68:/home/costea/s.png .

# VNC over an SSH tunnel (VNC is bound to 127.0.0.1:5900 on the host):
ssh -L 5901:127.0.0.1:5900 costea@192.168.1.68
#   then connect a VNC viewer to localhost:5901

# Serial console (interactive; Ctrl+] to exit):
ssh -t costea@192.168.1.68 'virsh -c qemu:///system console haos'
```

### Edit the definition
```bash
ssh -t costea@192.168.1.68 'virsh -c qemu:///system edit haos'   # validates XML; restart VM to apply
```

---

## 9. Backup strategy

Two complementary layers — **prefer HA-level backups** for portability/restore-into-anything:

### A. Home Assistant-level (recommended, primary)
- In the HA UI: **Settings → System → Backups → Create backup** (full or partial).
- Automate + push off-box with a backup add-on (e.g. Google Drive / Samba / NFS backup add-ons).
- These backups are restorable into any HAOS instance — independent of this host's old QEMU.

### B. Host/VM-disk-level (secondary, full-image)
Take a cold copy of the qcow2 while the VM is **off** (consistent image):
```bash
# 1. Stop the VM gracefully:
ssh costea@192.168.1.68 'virsh -c qemu:///system shutdown haos'
#    (wait until 'list --all' shows it shut off)

# 2. Copy the disk + NVRAM somewhere with space (qcow2 reads may need sudo: pool dir is 0711 root):
ssh -t costea@192.168.1.68 'sudo cp -a /var/lib/libvirt/images/haos.qcow2 /home/costea/backups/haos-$(date +%F).qcow2'
ssh costea@192.168.1.68    'cp -a /home/costea/haos_VARS.fd /home/costea/backups/haos_VARS-$(date +%F).fd'

# 3. Also keep the domain definition:
ssh costea@192.168.1.68 'virsh -c qemu:///system dumpxml haos > /home/costea/backups/haos-$(date +%F).xml'

# 4. Restart:
ssh costea@192.168.1.68 'virsh -c qemu:///system start haos'

# 5. (Optional) pull backups off the box:
scp costea@192.168.1.68:/home/costea/backups/* /d/backups/homebrain/
```
> Notes: the SSD is space-constrained — store image backups off-box or on the media HDD if room. Live snapshots are avoided here due to the old QEMU/qcow2 + UEFI combo; cold copies are the safe path. Keep a copy of `/home/costea/haos_ova-18.0.qcow2.xz` (pristine image) for clean rebuilds.

---

## 10. Recovery procedures

### A. VM won't start / definition lost (disk intact)
Re-register the domain from the kept XML and start it:
```bash
ssh costea@192.168.1.68 'virsh -c qemu:///system define /home/costea/haos.xml'
ssh costea@192.168.1.68 'virsh -c qemu:///system autostart haos'
ssh costea@192.168.1.68 'virsh -c qemu:///system start haos'
```
If NVRAM is missing, re-seed it before defining:
```bash
ssh costea@192.168.1.68 'cp /usr/share/OVMF/OVMF_VARS.fd /home/costea/haos_VARS.fd'
```

### B. Restore from a disk-image backup
```bash
ssh costea@192.168.1.68 'virsh -c qemu:///system destroy haos 2>/dev/null; true'
ssh -t costea@192.168.1.68 'sudo cp -a /home/costea/backups/haos-YYYY-MM-DD.qcow2 /var/lib/libvirt/images/haos.qcow2'
ssh costea@192.168.1.68 'cp -a /home/costea/backups/haos_VARS-YYYY-MM-DD.fd /home/costea/haos_VARS.fd'
ssh costea@192.168.1.68 'virsh -c qemu:///system start haos'
```

### C. Restore HA data only (into a running/blank HAOS)
- HA UI: **Settings → System → Backups → Upload backup → Restore** (or during onboarding, "restore from backup").

### D. Full rebuild from scratch (new blank HAOS)
```bash
# prereq once: sudo apt-get install -y ovmf
cd /home/costea
LATEST=$(curl -sL https://api.github.com/repos/home-assistant/operating-system/releases/latest | grep tag_name | grep -oE '[0-9]+\.[0-9]+')
wget -O haos.qcow2.xz "https://github.com/home-assistant/operating-system/releases/download/$LATEST/haos_ova-$LATEST.qcow2.xz"
unxz -kc haos.qcow2.xz > haos-src.qcow2
# stage into the SSD pool WITHOUT sudo:
virsh -c qemu:///system vol-create-as default haos.qcow2 34359738368 --format qcow2
virsh -c qemu:///system vol-upload --pool default haos.qcow2 /home/costea/haos-src.qcow2
# seed NVRAM, define, autostart, start:
cp /usr/share/OVMF/OVMF_VARS.fd /home/costea/haos_VARS.fd
virsh -c qemu:///system define /home/costea/haos.xml
virsh -c qemu:///system autostart haos
virsh -c qemu:///system start haos
```

### E. Updating HAOS
- Update **in place from the HA UI** (Settings → System → Updates). Do **not** swap the qcow2 to "update" — that wipes config. After a major HAOS jump on this old host, sanity-check it still boots (screenshot/VNC).

---

## 11. Coexistence note (do not break these)

The following run on the **same host**, untouched, in parallel with this VM:
- **Plex** (`plexmediaserver`, user `plex`) — host `192.168.1.68`.
- **Legacy HA Core** (`home-assistant@costea.service`) — host `192.168.1.68:8123` (different IP from the VM's `192.168.1.104:8123`, so no conflict).

Decommission the legacy Core only after migrating, when ready:
```bash
ssh -t costea@192.168.1.68 'sudo systemctl disable --now home-assistant@costea'
```
