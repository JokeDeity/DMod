"""Offline validation of the BlueAway discovery engine.

Stubs `winreg` with a fake hive that mirrors the real Windows Bluetooth
layout, including the hard case: an audio endpoint key whose name contains
no MAC address and no textual relationship to the device at all.
"""
import sys
import types

HKLM = 0x80000002
HKCU = 0x80000001

MAC = "aabbccddeeff"
ADAPTER = "112233445566"
INST = r"7&1a2b3c4d&0&BLUETOOTHDEVICE_AABBCCDDEEFF"
CONTAINER = "{c0ffee11-2222-3333-4444-555566667777}"
ENDPOINT = "{9d90bc11-abcd-4444-8888-0123456789ab}"
IFACE_CLASS = "{0850302a-b344-4fda-9be9-90576b8d46f0}"
SENTINEL = "{00000000-0000-0000-ffff-ffffffffffff}"

# (hive, path) -> {value_name: data}
FAKE = {}


def put(hive, path, values=None):
    FAKE[(hive, path)] = dict(values or {})
    # auto-create ancestors
    parts = path.split("\\")
    for i in range(1, len(parts)):
        p = "\\".join(parts[:i])
        FAKE.setdefault((hive, p), {})


CCS = r"SYSTEM\CurrentControlSet"

# --- the paired device, classic BR/EDR ------------------------------------
put(HKLM, rf"{CCS}\Services\BTHPORT\Parameters\Devices\{MAC}",
    {"Name": b"Soundcore Q30\x00", "LName": b"Soundcore Q30\x00"})
put(HKLM, rf"{CCS}\Services\BTHPORT\Parameters\Keys\{ADAPTER}",
    {MAC: b"\x01" * 16})

# --- the Enum node, which carries the ContainerID --------------------------
put(HKLM, rf"{CCS}\Enum\BTHENUM\Dev_{MAC.upper()}\{INST}",
    {"FriendlyName": "Soundcore Q30",
     "ContainerID": CONTAINER,
     "DeviceDesc": "Bluetooth Device"})
put(HKLM, rf"{CCS}\Enum\BTHENUM\Dev_{MAC.upper()}\{INST}\Properties", {})

# --- a device-interface symbolic link -------------------------------------
IFACE = rf"##?#BTHENUM#Dev_{MAC.upper()}#{INST}#{IFACE_CLASS}"
put(HKLM, rf"{CCS}\Control\DeviceClasses\{IFACE_CLASS}\{IFACE}",
    {"DeviceInstance": rf"BTHENUM\Dev_{MAC.upper()}\{INST}"})

# --- the device container --------------------------------------------------
put(HKLM, rf"{CCS}\Control\DeviceContainers\{CONTAINER}\BaseContainers"
         rf"\{CONTAINER}", {"Whatever": 1})

# --- THE HARD CASE --------------------------------------------------------
# An audio endpoint. Its key name is a GUID unrelated to the MAC. It is only
# reachable by following ContainerID. MAC-based searching NEVER finds this.
put(HKLM, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
         rf"\Render\{ENDPOINT}",
    {"DeviceState": 1})
put(HKLM, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
         rf"\Render\{ENDPOINT}\Properties",
    {"{b3f8fa53-0004-438e-9003-51a46e139bfc},2": "Soundcore Q30 Stereo",
     "{8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c},2": CONTAINER})

# --- a software-device node hanging off the endpoint ----------------------
put(HKLM, rf"{CCS}\Enum\SWD\MMDEVAPI"
         rf"\{{0.0.0.00000000}}.{ENDPOINT}",
    {"FriendlyName": "Soundcore Q30 Stereo", "ContainerID": CONTAINER})

# --- decoys that must NOT be swept ---------------------------------------
# 1. An unrelated device whose container GUID ends in 12 hex chars that
#    would false-positive against a naive MAC regex.
put(HKLM, rf"{CCS}\Control\DeviceContainers"
         rf"\{{12345678-90ab-cdef-1234-567890abcdef}}", {"Unrelated": 1})
# 2. A different Bluetooth device entirely.
put(HKLM, rf"{CCS}\Services\BTHPORT\Parameters\Devices\99887766554433"[:-2],
    {"Name": b"Other Headset\x00"})
put(HKLM, rf"{CCS}\Enum\BTHENUM\Dev_998877665544\7&99&0&X",
    {"ContainerID": "{dddddddd-1111-2222-3333-444444444444}"})
# 3. Hundreds of devices sharing the sentinel container -- harvesting it
#    would be catastrophic, so the engine must refuse it.
for i in range(50):
    put(HKLM, rf"{CCS}\Enum\SWD\Generic\Node{i:03d}",
        {"ContainerID": SENTINEL})
# 4. The local radio.
put(HKLM, rf"{CCS}\Enum\BTH\MS_BTHBRB\7&radio&0&{ADAPTER.upper()}",
    {"FriendlyName": "Bluetooth Radio"})

# 5. A service-class key whose GUID tail happens to be exactly 12 hex
#    digits bounded by '-' and '}' -- this is the bug pattern reported
#    against a real machine: MAC_IN_NAME_RE alone treats this as a MAC.
FAKE_MAC_TAIL = "1234567890ab"
put(HKLM, rf"{CCS}\Enum\BTHENUM"
         rf"\{{00000000-0000-0000-0099-{FAKE_MAC_TAIL}}}_VID&0001004c_PID&201b"
         rf"\7&abc123&0&41428669A9C2_C00000000",
    {"ContainerID": CONTAINER})


# ==========================================================================
# winreg stub
# ==========================================================================
class FakeKey:
    def __init__(self, hive, path):
        self.hive, self.path = hive, path

    def Close(self):
        pass


def _children(hive, path):
    pref = path + "\\"
    out = []
    for (h, p) in FAKE:
        if h == hive and p.startswith(pref):
            rest = p[len(pref):]
            if "\\" not in rest:
                out.append(rest)
    return sorted(set(out))


winreg = types.ModuleType("winreg")
winreg.HKEY_LOCAL_MACHINE = HKLM
winreg.HKEY_CURRENT_USER = HKCU
winreg.KEY_READ = 0x20019
winreg.KEY_WOW64_64KEY = 0x0100
winreg.KEY_ALL_ACCESS = 0xF003F
winreg.KEY_SET_VALUE = 0x0002


def _openkey(hive, path, reserved=0, access=0):
    h = hive.hive if isinstance(hive, FakeKey) else hive
    p = (hive.path + "\\" + path) if isinstance(hive, FakeKey) else path
    if (h, p) not in FAKE:
        raise OSError(2, "not found")
    return FakeKey(h, p)


def _queryinfo(k):
    return len(_children(k.hive, k.path)), len(FAKE[(k.hive, k.path)]), 0


def _enumvalue(k, i):
    items = list(FAKE[(k.hive, k.path)].items())
    if i >= len(items):
        raise OSError(259, "no more")
    n, d = items[i]
    t = 3 if isinstance(d, (bytes, bytearray)) else (4 if isinstance(d, int) else 1)
    return n, d, t


def _enumkey(k, i):
    c = _children(k.hive, k.path)
    if i >= len(c):
        raise OSError(259, "no more")
    return c[i]


winreg.OpenKey = _openkey
winreg.QueryInfoKey = _queryinfo
winreg.EnumValue = _enumvalue
winreg.EnumKey = _enumkey
winreg.DeleteKeyEx = lambda *a, **k: None
winreg.DeleteValue = lambda *a, **k: None
sys.modules["winreg"] = winreg

import blueaway_core as core  # noqa: E402

# Restrict scan roots to what our fake hive actually contains.
core.SCAN_ROOTS = [
    (HKLM, rf"{CCS}\Services\BTHPORT\Parameters"),
    (HKLM, rf"{CCS}\Enum\BTHENUM"),
    (HKLM, rf"{CCS}\Enum\BTH"),
    (HKLM, rf"{CCS}\Enum\SWD"),
    (HKLM, rf"{CCS}\Control\DeviceClasses"),
    (HKLM, rf"{CCS}\Control\DeviceContainers"),
    (HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"),
]
core.PROTECTED_EXACT.clear()
core._seed_protected()


def main():
    print("=" * 74)
    print("Indexing fake registry...")
    idx = core.RegistryIndex()
    idx.build()
    print(f"  indexed {len(idx.records)} keys in {idx.elapsed:.3f}s")

    adapters = core.get_adapter_macs()
    print(f"  adapters detected: {sorted(adapters)}")
    assert ADAPTER in adapters, "adapter MAC not detected"

    devices = core.discover_devices(idx)
    print(f"\nDiscovered {len(devices)} device(s):")
    for d in devices:
        print(f"  - {d.display:<28} {core.pretty_mac(d.mac)}  "
              f"[{d.kind_label}] container={sorted(d.container_ids)}")

    target = next(d for d in devices if d.mac == MAC)
    assert target.name == "Soundcore Q30", f"bad name: {target.name!r}"
    assert ADAPTER not in [d.mac for d in devices], "adapter leaked into list"
    assert FAKE_MAC_TAIL not in [d.mac for d in devices], (
        "PHANTOM DEVICE BUG: a service-class GUID's tail was treated as a "
        "real device MAC")

    print(f"\nBuilding plan for {target.display}...")
    plan = core.build_plan(target, idx, adapters, log=print)

    print(f"\nIdentity set ({len(plan.identity)} identifiers):")
    for t in sorted(plan.identity.tokens(), key=lambda x: (x.kind, x.text)):
        print(f"  [{t.confidence:<6}] {t.kind:<10} {t.text[:60]:<60} <- {t.origin}")
    if plan.identity.rejected:
        print("\nRejected identifiers:")
        for text, why in plan.identity.rejected:
            print(f"  x {str(text)[:50]:<50} ({why})")

    print(f"\nPlanned actions ({len(plan.references)}):")
    for r in plan.references:
        extra = (" :: " + ", ".join(r.value_names)) if r.value_names else ""
        print(f"  [{r.confidence:<6}][{r.action:<13}] {r.record.full}{extra}")
        print(f"          reason: {r.reason}")

    # ---- assertions ------------------------------------------------------
    hits = {r.record.full.lower(): r for r in plan.references}
    fails = []

    must_find = [
        (rf"HKLM\{CCS}\Services\BTHPORT\Parameters\Devices\{MAC}",
         "paired device key"),
        (rf"HKLM\{CCS}\Enum\BTHENUM\Dev_{MAC.upper()}\{INST}",
         "Enum instance"),
        (rf"HKLM\{CCS}\Control\DeviceClasses\{IFACE_CLASS}\{IFACE}",
         "device interface link"),
        (rf"HKLM\{CCS}\Control\DeviceContainers\{CONTAINER}",
         "device container"),
        (rf"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
         rf"\Render\{ENDPOINT}",
         "AUDIO ENDPOINT (no MAC anywhere in its name)"),
        (rf"HKLM\{CCS}\Enum\SWD\MMDEVAPI\{{0.0.0.00000000}}.{ENDPOINT}",
         "SWD MMDEVAPI node"),
    ]
    kill = [r.record.full.lower() for r in plan.references
            if r.action == "DELETE_KEY"]

    def covered(path):
        lp = path.lower()
        if lp in hits:
            return "directly"
        for k in kill:
            if lp.startswith(k + "\\"):
                return "via ancestor " + k.rsplit("\\", 1)[-1][:40]
        return None

    print("\n" + "-" * 74)
    for path, label in must_find:
        how = covered(path)
        mark = "PASS" if how else "FAIL"
        if not how:
            fails.append(label)
        print(f"  [{mark}] found {label}"
              f"{'' if how == 'directly' or not how else f'  ({how})'}")

    must_not = [
        (rf"HKLM\{CCS}\Control\DeviceContainers"
         rf"\{{12345678-90ab-cdef-1234-567890abcdef}}",
         "GUID false-positive container"),
        (rf"HKLM\{CCS}\Enum\BTHENUM\Dev_998877665544\7&99&0&X",
         "unrelated Bluetooth device"),
        (rf"HKLM\{CCS}\Enum\SWD\Generic\Node000",
         "sentinel-container node"),
        (rf"HKLM\{CCS}\Enum\BTH\MS_BTHBRB\7&radio&0&{ADAPTER.upper()}",
         "local radio"),
    ]
    for path, label in must_not:
        got = hits.get(path.lower())
        mark = "PASS" if not got else "FAIL"
        if got:
            fails.append("swept " + label)
        print(f"  [{mark}] did not touch {label}")

    protected_ok = all(
        r.record.full.lower() not in core.PROTECTED_EXACT
        for r in plan.references if r.action == "DELETE_KEY")
    print(f"  [{'PASS' if protected_ok else 'FAIL'}] no protected root queued "
          f"for deletion")
    if not protected_ok:
        fails.append("protected root queued")

    print("-" * 74)
    if fails:
        print("FAILURES: " + "; ".join(fails))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
