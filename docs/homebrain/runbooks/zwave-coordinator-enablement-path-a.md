# HomeBrain Runbook — Z-Wave Coordinator Enablement (Path A: USB passthrough)

> **Procedure reference, not an authorization.** Enabling the coordinator is a **live** change to the
> `haos` VM definition → it **claims the single live-system gate** (BACKLOG §10) and requires **explicit
> user approval** per the root `CLAUDE.md`. Nothing here runs unprompted. Read `../ONBOARDING.md` §1 and
> `../haos-vm-deployment.md` first. Path B (host-side Z-Wave JS) is the fallback — see §6.

**Device:** Home Assistant Connect ZWA-2 (decided in RQ-06 §8/§12). Presents as a **USB-C serial**
device on the host. **Enablement chosen:** Path A (USB passthrough into the VM) preferred; Path B fallback.

**Host/VM (from `haos-vm-deployment.md`):** Ubuntu 16.04.7 host `costea@192.168.1.68`, **QEMU 2.5 /
libvirt 1.3.1**; VM `haos`, machine type **`pc-q35-2.5` (q35)**, UEFI/OVMF, **3 vCPU / 4 GiB**, autostart
on. `virsh` uses `qemu:///system`, **no sudo** (`costea` in `libvirtd`). SSH needs the key in ssh-agent
(`ssh-add ~/.ssh/id_homebrain`; the key is **passphrase-protected** → load it interactively).

---

## 0. Two host facts to confirm first (read-only peek)

These two device-specific values are not knowable until the ZWA-2 is plugged into the host. Run this
**read-only** check (via ssh-agent; nothing is changed) and record the results into §2:

```bash
ssh-add ~/.ssh/id_homebrain
ssh costea@192.168.1.68 '
  echo "== usb controllers in the VM (model matters on q35/old QEMU) ==";
  virsh -c qemu:///system dumpxml haos | grep -iE "controller type=.usb|model=.(piix|ich9|qemu-xhci|nec-xhci)|<hostdev|redirdev";
  echo "== ZWA-2 vendor:product (plug it in first) =="; lsusb;
  echo "== stable serial symlink (use this inside HAOS) =="; ls -l /dev/serial/by-id/'
```

- **[CONFIRM-1] USB controller model** the guest exposes on q35 (typically ICH9 EHCI/UHCI on QEMU 2.5).
  A CDC-ACM serial device works at full/high speed on it; note the model so the `<hostdev>` attaches to a
  compatible controller.
- **[CONFIRM-2] ZWA-2 `idVendor:idProduct`** from `lsusb`, and its **`/dev/serial/by-id/…`** symlink.

## 1. ⚠️ Critical trap — never re-define from the stale XML

`haos-vm-deployment.md` §7 shows `/home/costea/haos.xml` as the **original** 2-vCPU / 2-GiB /
single-NIC definition. The **live** domain has since been upgraded (3 vCPU / 4 GiB / second NAT NIC
`192.168.122.10`). **Editing the live definition is mandatory; re-defining from `haos.xml` would revert
the CPU/RAM/second-NIC changes and break Music Assistant's ceiling-speaker path.** Use `virsh edit haos`
(live definition) or `virsh attach-device`, **not** `virsh define /home/costea/haos.xml`.

## 2. Add the USB passthrough (persistent, pinned by vendor:product)

Pin by **vendor:product** (from [CONFIRM-2]) so re-enumeration/reboot can't move the device. Prepare a
hostdev snippet (substitute the confirmed IDs):

```xml
<hostdev mode='subsystem' type='usb' managed='yes'>
  <source>
    <vendor id='0xVVVV'/>   <!-- [CONFIRM-2] ZWA-2 idVendor -->
    <product id='0xPPPP'/>  <!-- [CONFIRM-2] ZWA-2 idProduct -->
  </source>
</hostdev>
```

**Preferred apply path (cold, safest on old QEMU):**
```bash
ssh costea@192.168.1.68 'virsh -c qemu:///system shutdown haos'   # graceful; wait until "shut off"
ssh -t costea@192.168.1.68 'virsh -c qemu:///system edit haos'    # add the <hostdev> inside <devices>; validates on save
ssh costea@192.168.1.68 'virsh -c qemu:///system start haos'
```
*(A live hot-attach — `virsh attach-device haos zwa2-usb.xml --live --config` — exists, but hot-plug
reliability on QEMU 2.5 / libvirt 1.3.1 is not assumed; prefer the cold edit + reboot.)*

**Post-apply verification (read-only):**
```bash
ssh costea@192.168.1.68 'virsh -c qemu:///system dumpxml haos | grep -A3 hostdev'   # hostdev present
# In HAOS (via VNC/console — host can't reach the macvtap guest over IP; see haos-vm-deployment.md §8):
#   confirm the controller appears under /dev/serial/by-id/ inside the VM.
```

## 3. Point Z-Wave JS at the controller

- In HAOS, install/point the **Z-Wave JS** add-on at the controller via its **`/dev/serial/by-id/…`**
  symlink ([CONFIRM-2]) — **not** `/dev/ttyUSB*` (which can move across reboots).
- The ZWA-2 auto-sets the **Z-Wave region from the HA location** (Edmonton ⇒ 908.42 MHz; RQ-06 §12) —
  no region variant to select.

## 4. Placement (RF)

The ZWA-2 has an **external upright antenna on a 1.5 m USB-C cable** — site it **off the metal host
chassis** for range to the wall-mounted smoke bridge (RQ-06 §6). Z-Wave is sub-GHz (908.42 MHz), so
USB-3 / 2.4 GHz interference is far less of a concern than for Zigbee, but antenna placement still helps.

## 5. Rollback

- **Remove passthrough:** `virsh edit haos` → delete the `<hostdev>` block → reboot the VM (or
  `virsh detach-device haos zwa2-usb.xml --live --config`). The host keeps the physical device.
- **Release the live gate** (BACKLOG §10) on completion or abandonment.
- No changes to CPU/RAM/NICs, Plex, legacy HA Core, or host networking at any point.

## 6. Path B — host-side Z-Wave JS + NAT network (fallback only)

If USB passthrough proves unstable on this old stack ([CONFIRM-1] issues, hot-plug flakiness, device
re-addressing): run a **standalone Z-Wave JS on the host** with the ZWA-2 plugged in locally, and point
HA's Z-Wave JS integration at it over the existing **host↔VM NAT** (`192.168.122.x`). The ZWA-2 documents
this remote pattern as first-class (RQ-06 §6). Trade-off: adds a host-side service to maintain (against
ONBOARDING's "keep the host minimal") and a small network-latency hop; **leaves the VM XML untouched**.

## 7. Safety

- **No VM/host change, no service restart, no gate claim without explicit approval** (root `CLAUDE.md`;
  BACKLOG §8/§10). §0 and the verification greps are read-only; §2/§5 mutate the VM definition (gated).
- **At most one live gate active** — coordinate with any other live track (BACKLOG §10).
- **Never print/commit secrets.** This procedure touches VM hardware config only (no tokens/keys).

> Authoritative context: `../ONBOARDING.md` · `../haos-vm-deployment.md` · RQ-06 decision (`§6`, `§12`) ·
> SA-03 plan (`../plans/2026-07-06-sa-03-smoke-co-alerting-plan.md`). Rollback for this doc: `git revert`
> on its branch, or delete the file.
