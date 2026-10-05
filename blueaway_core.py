"""
blueaway_core.py -- Deep Bluetooth device trace removal for Windows.

This module contains no UI. It is safe to import from a GUI, from DMod, or
from a CLI.

Design
------
The hard problem is that Windows and device vendors do not agree on where a
Bluetooth device is recorded. Searching for the MAC address only finds a
fraction of the references, because several of the most important keys
(audio endpoints, device containers, software-device nodes) identify the
device by a *derived* GUID that contains no trace of the MAC.

So instead of searching for a MAC, BlueAway builds an **identity set** and
grows it to a fixed point:

    MAC
      -> BTHENUM / BTHLE / BTHLEDevice instance IDs
      -> ContainerID GUID
      -> Control\\DeviceContainers child, Control\\DeviceClasses interface links
      -> Enum\\SWD software-device nodes
      -> MMDevices audio endpoint GUIDs
      -> further SWD\\MMDEVAPI nodes

Every time a token matches a key, that key is harvested for new tokens under
strict rules. The loop repeats until no new tokens appear. The registry is
walked exactly once into an in-memory index; the fixed-point loop then runs
against that index, so extra iterations are nearly free.

Safety
------
* Scanning is restricted to an explicit allowlist of roots.
* An explicit protected-path set can never be deleted (service roots,
  class roots, the local radio's own keys, the adapter link-key containers).
* Sentinel GUIDs such as {00000000-0000-0000-FFFF-FFFFFFFFFFFF} are refused
  as tokens -- that value means "not in a container" and is shared by
  hundreds of unrelated devices.
* Any token that matches more than TOKEN_BREADTH_LIMIT keys is discarded as
  too broad, which stops one bad harvest from cascading.
* Every planned action is classified HIGH / MEDIUM / LOW confidence and is
  presented for review before anything is touched.
* Backups are written as a real, appended .reg file (one export per key,
  concatenated correctly) -- not overwritten each time.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import winreg
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

HKLM = winreg.HKEY_LOCAL_MACHINE
HKCU = winreg.HKEY_CURRENT_USER

HIVE_NAMES = {
    HKLM: "HKLM",
    HKCU: "HKCU",
}

# 64-bit view always, even if running under 32-bit Python.
KEY_READ_64 = winreg.KEY_READ | winreg.KEY_WOW64_64KEY

BTHPORT_PARAMS = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters"
BTHPORT_DEVICES = BTHPORT_PARAMS + r"\Devices"
BTHPORT_KEYS = BTHPORT_PARAMS + r"\Keys"

# Roots that are walked and indexed. Deliberately does NOT include
# Enum\USB (the radio itself lives there) or Enum\HID roots wholesale.
SCAN_ROOTS: List[Tuple[int, str]] = [
    (HKLM, BTHPORT_PARAMS),
    (HKLM, r"SYSTEM\CurrentControlSet\Services\BTAGService"),
    (HKLM, r"SYSTEM\CurrentControlSet\Services\BthA2dp"),
    (HKLM, r"SYSTEM\CurrentControlSet\Services\BthAvrcpTg"),
    (HKLM, r"SYSTEM\CurrentControlSet\Services\BthEnum"),
    (HKLM, r"SYSTEM\CurrentControlSet\Services\BthHFEnum"),
    (HKLM, r"SYSTEM\CurrentControlSet\Services\BthLEEnum"),
    (HKLM, r"SYSTEM\CurrentControlSet\Services\BthMini"),
    (HKLM, r"SYSTEM\CurrentControlSet\Services\BthPan"),
    (HKLM, r"SYSTEM\CurrentControlSet\Services\HidBth"),
    (HKLM, r"SYSTEM\CurrentControlSet\Services\RFCOMM"),
    (HKLM, r"SYSTEM\CurrentControlSet\Services\DeviceAssociationService\State"),
    (HKLM, r"SYSTEM\CurrentControlSet\Enum\BTHENUM"),
    (HKLM, r"SYSTEM\CurrentControlSet\Enum\BTHLE"),
    (HKLM, r"SYSTEM\CurrentControlSet\Enum\BTHLEDevice"),
    (HKLM, r"SYSTEM\CurrentControlSet\Enum\BTH"),
    (HKLM, r"SYSTEM\CurrentControlSet\Enum\SWD"),
    (HKLM, r"SYSTEM\CurrentControlSet\Control\DeviceClasses"),
    (HKLM, r"SYSTEM\CurrentControlSet\Control\DeviceContainers"),
    (HKLM, r"SYSTEM\CurrentControlSet\Control\Bluetooth"),
    (HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Bluetooth"),
    (HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"),
    (HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Device Metadata"),
    (HKCU, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Bluetooth"),
    (HKCU, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Device Metadata"),
]

# Keys that must never be deleted, regardless of what matches inside them.
# Compared case-insensitively as "HIVE\path".
PROTECTED_EXACT: Set[str] = set()


def _seed_protected() -> None:
    fixed = [
        (HKLM, BTHPORT_PARAMS),
        (HKLM, BTHPORT_DEVICES),
        (HKLM, BTHPORT_KEYS),
        (HKLM, r"SYSTEM\CurrentControlSet\Services\BTHPORT"),
        (HKLM, r"SYSTEM\CurrentControlSet\Enum\BTHENUM"),
        (HKLM, r"SYSTEM\CurrentControlSet\Enum\BTHLE"),
        (HKLM, r"SYSTEM\CurrentControlSet\Enum\BTHLEDevice"),
        (HKLM, r"SYSTEM\CurrentControlSet\Enum\BTH"),
        (HKLM, r"SYSTEM\CurrentControlSet\Enum\SWD"),
        (HKLM, r"SYSTEM\CurrentControlSet\Control\DeviceClasses"),
        (HKLM, r"SYSTEM\CurrentControlSet\Control\DeviceContainers"),
        (HKLM, r"SYSTEM\CurrentControlSet\Control\Bluetooth"),
        (HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"),
        (HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"),
        (HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"),
        (HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Bluetooth"),
    ]
    for hive, path in fixed:
        PROTECTED_EXACT.add(f"{HIVE_NAMES[hive]}\\{path}".lower())
    for hive, path in SCAN_ROOTS:
        PROTECTED_EXACT.add(f"{HIVE_NAMES[hive]}\\{path}".lower())


_seed_protected()

# Container GUID meaning "this device is not in a container". Shared by a
# huge number of unrelated devices -- must never become a token.
SENTINEL_GUIDS = {
    "{00000000-0000-0000-0000-000000000000}",
    "{00000000-0000-0000-ffff-ffffffffffff}",
}

# Value names whose contents are trustworthy sources of new identifiers.
HARVEST_VALUE_NAMES = {
    "containerid": "container",
    "deviceinstance": "instance",
    "deviceinstanceid": "instance",
    "symboliclink": "interface",
    "parentidprefix": None,  # read but only used as a weak hint
}

MAX_EXPANSION_ROUNDS = 6
TOKEN_BREADTH_LIMIT = 400
MAX_INDEXED_KEYS = 400_000
MAX_DEPTH = 14

HEXCHARS = frozenset("0123456789abcdef")

MAC_IN_NAME_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{12})(?![0-9a-fA-F])")
GUID_RE = re.compile(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}")

# Structural harvest rules. These match on a path PREFIX, not on the leaf,
# so that matching any descendant of an entity harvests the entity's own id.
# That is what reaches an audio endpoint key whose name contains no MAC:
#   ...\MMDevices\Audio\Render\{endpoint}\Properties matches on a container
#   GUID held in a property value, and we harvest {endpoint} from the path.
_RE_CONTAINER_OWNER = re.compile(
    r"^system\\currentcontrolset\\control\\devicecontainers\\([^\\]+)(?:\\|$)")
_RE_MMDEV_OWNER = re.compile(
    r"^software\\microsoft\\windows\\currentversion\\mmdevices\\audio\\"
    r"(?:render|capture)\\([^\\]+)(?:\\|$)")
_RE_ENUM_OWNER = re.compile(
    r"^SYSTEM\\CurrentControlSet\\Enum\\([^\\]+)\\([^\\]+)\\([^\\]+)(?:\\|$)",
    re.I)
_RE_IFACE_OWNER = re.compile(
    r"^system\\currentcontrolset\\control\\deviceclasses\\\{[0-9a-f-]+\}\\"
    r"([^\\]+)(?:\\|$)")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(extra_args: Optional[Sequence[str]] = None) -> bool:
    """Re-launch the current script elevated. Returns True if launch issued."""
    try:
        args = list(sys.argv[1:]) if extra_args is None else list(extra_args)
        script = os.path.abspath(sys.argv[0])
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, " ".join(f'"{a}"' for a in args)
        else:
            exe = sys.executable
            params = " ".join(['"%s"' % script] + [f'"{a}"' for a in args])
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return int(rc) > 32
    except Exception:
        return False


def norm_mac(raw: str) -> str:
    """Strip separators, lowercase. '' if not a 12-hex MAC."""
    s = re.sub(r"[^0-9a-fA-F]", "", raw or "").lower()
    return s if len(s) == 12 else ""


def pretty_mac(mac12: str) -> str:
    m = mac12.upper()
    return ":".join(m[i:i + 2] for i in range(0, 12, 2))


def mac_variants(mac12: str) -> List[str]:
    """Every textual form a MAC realistically appears in, lowercased."""
    m = mac12.lower()
    pairs = [m[i:i + 2] for i in range(0, 12, 2)]
    out = [
        m,
        ":".join(pairs),
        "-".join(pairs),
        "".join(reversed(pairs)),          # byte-reversed, common in blobs
        "".join(p + "00" for p in pairs),  # UTF-16LE hex of the ASCII form
    ]
    return out


def path_variants(text: str) -> List[str]:
    """Registry paths appear with '\\' and, in interface names, with '#'."""
    t = text.lower()
    out = {t}
    if "\\" in t:
        out.add(t.replace("\\", "#"))
    if "#" in t:
        out.add(t.replace("#", "\\"))
    return sorted(out)


def _bounded_find(hay: str, needle: str) -> bool:
    """Substring search that refuses a match flanked by more hex digits.

    Stops '{...-567890abcdef}' inside a GUID from reading as a MAC.
    """
    start = 0
    n = len(needle)
    while True:
        i = hay.find(needle, start)
        if i < 0:
            return False
        before_ok = i == 0 or hay[i - 1] not in HEXCHARS
        j = i + n
        after_ok = j >= len(hay) or hay[j] not in HEXCHARS
        if before_ok and after_ok:
            return True
        start = i + 1


def render_value(data) -> List[str]:
    """Turn any registry value into searchable lowercase strings."""
    out: List[str] = []
    if data is None:
        return out
    if isinstance(data, str):
        out.append(data.lower())
    elif isinstance(data, (list, tuple)):
        for item in data:
            out.append(str(item).lower())
    elif isinstance(data, int):
        out.append(str(data))
        out.append("%08x" % (data & 0xFFFFFFFF))
    elif isinstance(data, (bytes, bytearray)):
        b = bytes(data)
        out.append(b.hex())
        try:
            out.append(b.decode("utf-16-le", "ignore").lower())
        except Exception:
            pass
        try:
            out.append(b.decode("utf-8", "ignore").lower())
        except Exception:
            pass
    else:
        out.append(str(data).lower())
    return [s for s in out if s]


def decode_name_value(data) -> str:
    """BTHPORT stores friendly names as raw bytes; decode sanely."""
    if isinstance(data, str):
        return data.strip("\x00").strip()
    if isinstance(data, (bytes, bytearray)):
        b = bytes(data)
        for enc in ("utf-8", "utf-16-le", "latin-1"):
            try:
                s = b.decode(enc).strip("\x00").strip()
            except Exception:
                continue
            if s and all(ch.isprintable() or ch.isspace() for ch in s):
                return s
    return ""


# --------------------------------------------------------------------------
# Registry index
# --------------------------------------------------------------------------

@dataclass
class KeyRecord:
    hive: int
    path: str                       # without hive, e.g. SYSTEM\...\Dev_x
    values: List[Tuple[str, object, int]] = field(default_factory=list)

    @property
    def full(self) -> str:
        return f"{HIVE_NAMES[self.hive]}\\{self.path}"

    @property
    def leaf(self) -> str:
        return self.path.rsplit("\\", 1)[-1]

    @property
    def depth(self) -> int:
        return self.path.count("\\")


class RegistryIndex:
    """One pass over the scan roots; everything after that is in memory."""

    def __init__(self, roots: Optional[Sequence[Tuple[int, str]]] = None):
        self.roots = list(roots or SCAN_ROOTS)
        self.records: List[KeyRecord] = []
        self.by_full: Dict[str, KeyRecord] = {}
        self._hay_name: List[str] = []
        self._hay_all: List[str] = []
        self.truncated = False
        self.elapsed = 0.0

    # -- building ---------------------------------------------------------

    def build(self, progress: Optional[Callable[[str, int], None]] = None) -> None:
        t0 = time.time()
        self.records.clear()
        self.by_full.clear()
        for hive, root in self.roots:
            if progress:
                progress(f"{HIVE_NAMES[hive]}\\{root}", len(self.records))
            self._walk(hive, root, 0, progress)
            if self.truncated:
                break
        self._index_haystacks()
        self.elapsed = time.time() - t0

    def _walk(self, hive: int, path: str, depth: int,
              progress: Optional[Callable[[str, int], None]]) -> None:
        if depth > MAX_DEPTH or len(self.records) >= MAX_INDEXED_KEYS:
            if len(self.records) >= MAX_INDEXED_KEYS:
                self.truncated = True
            return
        try:
            key = winreg.OpenKey(hive, path, 0, KEY_READ_64)
        except OSError:
            return
        try:
            try:
                nsub, nval, _ = winreg.QueryInfoKey(key)
            except OSError:
                return

            values: List[Tuple[str, object, int]] = []
            for i in range(nval):
                try:
                    vn, vd, vt = winreg.EnumValue(key, i)
                except OSError:
                    break
                values.append((vn, vd, vt))

            rec = KeyRecord(hive, path, values)
            self.records.append(rec)
            self.by_full[rec.full.lower()] = rec

            if progress and len(self.records) % 4000 == 0:
                progress(path, len(self.records))

            subs: List[str] = []
            for i in range(nsub):
                try:
                    subs.append(winreg.EnumKey(key, i))
                except OSError:
                    break
        finally:
            try:
                key.Close()
            except Exception:
                pass

        for name in subs:
            self._walk(hive, path + "\\" + name, depth + 1, progress)

    def _index_haystacks(self) -> None:
        """Precompute one lowercase blob per key: the leaf name, and
        everything (path + value names + value data)."""
        self._hay_name = []
        self._hay_all = []
        for rec in self.records:
            leaf = rec.leaf.lower()
            self._hay_name.append(leaf)
            parts = [rec.path.lower()]
            for vn, vd, _vt in rec.values:
                if vn:
                    parts.append(vn.lower())
                parts.extend(render_value(vd))
            self._hay_all.append("\n".join(parts))

    # -- querying ---------------------------------------------------------

    def match(self, needles: Sequence[Tuple[str, bool]]) -> List[Tuple[int, bool]]:
        """Return (record_index, matched_in_leaf_name) for each hit.

        `needles` is a sequence of (lowercase_text, apply_hex_boundary).
        """
        hits: List[Tuple[int, bool]] = []
        for idx in range(len(self.records)):
            name_hay = self._hay_name[idx]
            all_hay = self._hay_all[idx]
            in_name = False
            in_any = False
            for text, bounded in needles:
                if bounded:
                    if _bounded_find(name_hay, text):
                        in_name = True
                        in_any = True
                        break
                    if not in_any and _bounded_find(all_hay, text):
                        in_any = True
                else:
                    if text in name_hay:
                        in_name = True
                        in_any = True
                        break
                    if not in_any and text in all_hay:
                        in_any = True
            if in_any:
                hits.append((idx, in_name))
        return hits

    def count_matches(self, text: str, bounded: bool) -> int:
        n = 0
        for hay in self._hay_all:
            if (_bounded_find(hay, text) if bounded else (text in hay)):
                n += 1
                if n > TOKEN_BREADTH_LIMIT:
                    break
        return n


# --------------------------------------------------------------------------
# Identity tokens
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Token:
    text: str        # lowercase needle
    kind: str        # mac | instance | container | interface | endpoint | swd
    bounded: bool    # apply hex-boundary guard
    origin: str      # human-readable provenance
    confidence: str  # HIGH | MEDIUM


class IdentitySet:
    def __init__(self) -> None:
        self._tokens: Dict[str, Token] = {}
        self.rejected: List[Tuple[str, str]] = []

    def __len__(self) -> int:
        return len(self._tokens)

    def tokens(self) -> List[Token]:
        return list(self._tokens.values())

    def needles(self) -> List[Tuple[str, bool]]:
        return [(t.text, t.bounded) for t in self._tokens.values()]

    def has(self, text: str) -> bool:
        return text.lower() in self._tokens

    def add(self, text: str, kind: str, origin: str,
            confidence: str = "MEDIUM", bounded: bool = False) -> bool:
        t = (text or "").strip().lower()
        if len(t) < 8:
            self.rejected.append((text, "too short"))
            return False
        if t in SENTINEL_GUIDS:
            self.rejected.append((text, "sentinel GUID"))
            return False
        if t in self._tokens:
            return False
        self._tokens[t] = Token(t, kind, bounded, origin, confidence)
        return True

    def add_mac(self, mac12: str, origin: str, confidence: str = "HIGH") -> None:
        for v in mac_variants(mac12):
            bounded = bool(re.fullmatch(r"[0-9a-f]+", v))
            self.add(v, "mac", origin, confidence, bounded)

    def add_path_token(self, text: str, kind: str, origin: str,
                       confidence: str = "MEDIUM") -> bool:
        added = False
        for v in path_variants(text):
            if self.add(v, kind, origin, confidence, bounded=False):
                added = True
        return added

    def drop(self, text: str, reason: str) -> None:
        t = text.lower()
        if t in self._tokens:
            del self._tokens[t]
            self.rejected.append((text, reason))


# --------------------------------------------------------------------------
# Device discovery (seeds)
# --------------------------------------------------------------------------

@dataclass
class BtDevice:
    mac: str                        # normalized 12 hex lowercase
    name: str = ""
    kinds: Set[str] = field(default_factory=set)   # BR/EDR, BLE, ghost
    adapter_macs: Set[str] = field(default_factory=set)
    instance_ids: Set[str] = field(default_factory=set)
    container_ids: Set[str] = field(default_factory=set)
    paired: bool = False

    @property
    def display(self) -> str:
        return self.name or "(unnamed device)"

    @property
    def kind_label(self) -> str:
        if not self.kinds:
            return "unknown"
        return "+".join(sorted(self.kinds))


def _open(hive: int, path: str):
    try:
        return winreg.OpenKey(hive, path, 0, KEY_READ_64)
    except OSError:
        return None


def _subkeys(hive: int, path: str) -> List[str]:
    k = _open(hive, path)
    if not k:
        return []
    out = []
    try:
        i = 0
        while True:
            try:
                out.append(winreg.EnumKey(k, i))
            except OSError:
                break
            i += 1
    finally:
        k.Close()
    return out


def _values(hive: int, path: str) -> Dict[str, object]:
    k = _open(hive, path)
    if not k:
        return {}
    out: Dict[str, object] = {}
    try:
        i = 0
        while True:
            try:
                vn, vd, _vt = winreg.EnumValue(k, i)
            except OSError:
                break
            out[vn] = vd
            i += 1
    finally:
        k.Close()
    return out


def get_adapter_macs() -> Set[str]:
    """Local radio MACs. These are protected -- never treated as removable."""
    adapters: Set[str] = set()
    for name in _subkeys(HKLM, BTHPORT_KEYS):
        m = norm_mac(name)
        if m:
            adapters.add(m)
    # Radios also appear under Enum\BTH\MS_BTHBRB or as BTHENUM local
    for name in _subkeys(HKLM, r"SYSTEM\CurrentControlSet\Enum\BTH"):
        for inst in _subkeys(HKLM, rf"SYSTEM\CurrentControlSet\Enum\BTH\{name}"):
            m = MAC_IN_NAME_RE.search(inst)
            if m:
                adapters.add(m.group(1).lower())
    return adapters


def discover_devices(index: Optional[RegistryIndex] = None) -> List[BtDevice]:
    """Authoritative device enumeration from the keys Windows actually owns."""
    adapters = get_adapter_macs()
    devices: Dict[str, BtDevice] = {}

    def get(mac: str) -> BtDevice:
        if mac not in devices:
            devices[mac] = BtDevice(mac=mac)
        return devices[mac]

    # 1. Classic BR/EDR paired devices.
    for name in _subkeys(HKLM, BTHPORT_DEVICES):
        mac = norm_mac(name)
        if not mac or mac in adapters:
            continue
        d = get(mac)
        d.kinds.add("BR/EDR")
        d.paired = True
        vals = _values(HKLM, BTHPORT_DEVICES + "\\" + name)
        for key in ("Name", "LName", "FriendlyName"):
            if key in vals:
                nm = decode_name_value(vals[key])
                if nm:
                    d.name = d.name or nm
                    break

    # 2. Link keys: Keys\<adapter> holds device MACs as values or subkeys.
    for adapter in _subkeys(HKLM, BTHPORT_KEYS):
        amac = norm_mac(adapter)
        if not amac:
            continue
        base = BTHPORT_KEYS + "\\" + adapter
        for vn in _values(HKLM, base).keys():
            mac = norm_mac(vn)
            if mac and mac not in adapters:
                d = get(mac)
                d.paired = True
                d.adapter_macs.add(amac)
                d.kinds.add("BR/EDR")
        for sk in _subkeys(HKLM, base):
            mac = norm_mac(sk)
            if mac and mac not in adapters:
                d = get(mac)
                d.paired = True
                d.adapter_macs.add(amac)
                d.kinds.add("BLE")

    # 3. Enum nodes -- these also reveal unpaired leftovers ("ghosts").
    #
    # IMPORTANT: BTHENUM/BTHLE also contain *service-class* subkeys named
    # like "{00000000-0000-0000-0099-AABBCCDDEEFF}_VID&0001004c_PID&201b".
    # The last 12 hex digits of a GUID are bounded by '-' and '}', which
    # satisfies the plain MAC regex's hex-boundary guard even though it is
    # not a device address at all -- it just happens to be the tail of a
    # GUID. Treating it as a device seeds a phantom device and analyses the
    # wrong (nonexistent) target. So a MAC is only trusted here when the
    # subkey name has the real device-folder shape: "Dev_<mac>" for
    # BTHENUM/BTH, or "<svc>_<adapter>-<device>" for BTHLE/BTHLEDevice
    # (both anchored so a GUID fragment can never satisfy them).
    _RE_DEV_FOLDER = re.compile(r"^dev_([0-9a-f]{12})$", re.I)
    _RE_BTHLE_FOLDER = re.compile(
        r"^\{[0-9a-f-]+\}_([0-9a-f]{12})[-_]([0-9a-f]{12})$", re.I)

    enum_specs = [
        (r"SYSTEM\CurrentControlSet\Enum\BTHENUM", "BR/EDR"),
        (r"SYSTEM\CurrentControlSet\Enum\BTHLE", "BLE"),
        (r"SYSTEM\CurrentControlSet\Enum\BTHLEDevice", "BLE"),
    ]
    for root, kind in enum_specs:
        for devname in _subkeys(HKLM, root):
            m1 = _RE_DEV_FOLDER.match(devname)
            m2 = _RE_BTHLE_FOLDER.match(devname)
            if m1:
                macs = [m1.group(1).lower()]
            elif m2:
                macs = [m2.group(1).lower(), m2.group(2).lower()]
            else:
                continue  # not a device folder -- e.g. a service-class key
            target = None
            for m in reversed(macs):
                if m not in adapters:
                    target = m
                    break
            if not target:
                continue
            d = get(target)
            d.kinds.add(kind)
            for m in macs:
                if m in adapters:
                    d.adapter_macs.add(m)
            devpath = f"{root}\\{devname}"
            for inst in _subkeys(HKLM, devpath):
                instance_id = f"{devname}\\{inst}"
                root_leaf = root.rsplit("\\", 1)[-1]
                d.instance_ids.add(f"{root_leaf}\\{instance_id}")
                vals = _values(HKLM, f"{devpath}\\{inst}")
                for vk in ("FriendlyName", "DeviceDesc", "Mfg"):
                    raw = vals.get(vk)
                    if not raw:
                        continue
                    nm = decode_name_value(raw)
                    if nm.startswith("@"):     # indirect string resource
                        continue
                    if nm and not d.name:
                        d.name = nm
                cid = vals.get("ContainerID")
                if isinstance(cid, str) and cid.lower() not in SENTINEL_GUIDS:
                    d.container_ids.add(cid.lower())

    for d in devices.values():
        if not d.paired and "ghost" not in d.kinds and not d.instance_ids:
            d.kinds.add("orphan")
        elif not d.paired:
            d.kinds.add("unpaired")
        if not d.name:
            d.name = f"Unknown device {pretty_mac(d.mac)}"

    return sorted(devices.values(), key=lambda x: (x.name.lower(), x.mac))


# --------------------------------------------------------------------------
# Reference discovery -- the fixed-point expansion
# --------------------------------------------------------------------------

@dataclass
class Reference:
    record: KeyRecord
    in_name: bool
    confidence: str                 # HIGH | MEDIUM | LOW
    reason: str
    value_names: List[str] = field(default_factory=list)

    @property
    def action(self) -> str:
        return "DELETE_KEY" if self.in_name else "DELETE_VALUES"


@dataclass
class Plan:
    device: BtDevice
    references: List[Reference] = field(default_factory=list)
    identity: Optional[IdentitySet] = None
    rounds: int = 0
    notes: List[str] = field(default_factory=list)

    def deletable_keys(self) -> List[Reference]:
        return [r for r in self.references if r.action == "DELETE_KEY"]

    def value_edits(self) -> List[Reference]:
        return [r for r in self.references if r.action == "DELETE_VALUES"]


def _is_protected(rec: KeyRecord, adapters: Set[str]) -> Optional[str]:
    full = rec.full.lower()
    if full in PROTECTED_EXACT:
        return "scan root / service root"
    # Never delete a scan root's direct container level for class GUIDs.
    if re.search(r"\\control\\deviceclasses\\\{[0-9a-f-]+\}$", full):
        return "device interface class root"
    if full.endswith(r"\mmdevices\audio\render") or full.endswith(r"\mmdevices\audio\capture"):
        return "audio endpoint root"
    # Guard the radio's own link-key container.
    m = re.search(r"\\bthport\\parameters\\keys\\([0-9a-f]{12})$", full)
    if m and m.group(1) in adapters:
        return "local radio link-key container"
    if rec.depth < 2:
        return "too shallow"
    return None


def _harvest(rec: KeyRecord, identity: IdentitySet, index: RegistryIndex) -> int:
    """Pull new identifiers out of a key that already matched."""
    added = 0
    lower_path = rec.path.lower()

    # (a) Trusted value names.
    for vn, vd, _vt in rec.values:
        key = (vn or "").lower()
        kind = HARVEST_VALUE_NAMES.get(key)
        if kind is None:
            continue
        if isinstance(vd, (bytes, bytearray)):
            text = decode_name_value(vd)
        elif isinstance(vd, (list, tuple)):
            text = str(vd[0]) if vd else ""
        else:
            text = str(vd or "")
        text = text.strip().strip("\x00")
        if not text:
            continue
        if kind == "container":
            if text.lower() in SENTINEL_GUIDS:
                continue
            if identity.add(text.lower(), "container",
                            f"ContainerID of {rec.leaf}", "HIGH"):
                added += 1
        else:
            if identity.add_path_token(text, kind, f"{vn} of {rec.leaf}", "MEDIUM"):
                added += 1

    # (b) Owning device container. The most valuable link in the whole
    #     chain -- it reaches audio endpoints and software-device nodes
    #     that contain no trace of the MAC anywhere.
    m = _RE_CONTAINER_OWNER.match(lower_path)
    if m:
        guid = m.group(1)
        if GUID_RE.fullmatch(guid) and guid not in SENTINEL_GUIDS:
            if identity.add(guid, "container", "DeviceContainers entry", "HIGH"):
                added += 1

    # (c) Owning audio endpoint.
    m = _RE_MMDEV_OWNER.match(lower_path)
    if m and GUID_RE.fullmatch(m.group(1)):
        if identity.add(m.group(1), "endpoint",
                        "MMDevices audio endpoint", "MEDIUM"):
            added += 1

    # (d) Owning Enum device instance: <enumerator>\<device>\<instance>
    m = _RE_ENUM_OWNER.match(rec.path)
    if m:
        enumerator, devpart, instpart = m.groups()
        inst = f"{enumerator}\\{devpart}\\{instpart}"
        conf = "HIGH" if enumerator.lower().startswith("bth") else "MEDIUM"
        if identity.add_path_token(inst, "instance", "Enum instance", conf):
            added += 1
        # SWD\MMDEVAPI\{0.0.0.00000000}.{endpoint} embeds the endpoint GUID.
        if enumerator.lower() == "swd":
            for g in GUID_RE.findall(instpart) + GUID_RE.findall(devpart):
                if g.lower() in SENTINEL_GUIDS:
                    continue
                if identity.add(g.lower(), "endpoint",
                                "GUID embedded in SWD node", "MEDIUM"):
                    added += 1

    # (e) Owning device-interface symbolic link.
    m = _RE_IFACE_OWNER.match(lower_path)
    if m and m.group(1).startswith("##?#"):
        if identity.add_path_token(m.group(1), "interface",
                                   "Device interface", "HIGH"):
            added += 1

    return added


def build_plan(device: BtDevice, index: RegistryIndex,
               adapters: Optional[Set[str]] = None,
               log: Optional[Callable[[str], None]] = None) -> Plan:
    """Grow an identity set to a fixed point, then classify every hit."""
    adapters = adapters if adapters is not None else get_adapter_macs()
    say = log or (lambda _m: None)

    identity = IdentitySet()
    identity.add_mac(device.mac, "seed MAC", "HIGH")
    for inst in device.instance_ids:
        identity.add_path_token(inst, "instance", "seed instance", "HIGH")
    for cid in device.container_ids:
        identity.add(cid, "container", "seed ContainerID", "HIGH")

    seen_records: Dict[int, Tuple[bool, str]] = {}
    rounds = 0
    notes: List[str] = []

    while rounds < MAX_EXPANSION_ROUNDS:
        rounds += 1
        needles = identity.needles()
        hits = index.match(needles)
        new_tokens = 0
        for rec_idx, in_name in hits:
            prev = seen_records.get(rec_idx)
            if prev is not None and (prev[0] or not in_name):
                continue
            rec = index.records[rec_idx]
            seen_records[rec_idx] = (in_name, "")
            new_tokens += _harvest(rec, identity, index)

        say(f"  round {rounds}: {len(hits)} keys matched, "
            f"{len(identity)} identifiers, +{new_tokens} new")

        if new_tokens == 0:
            break

        # Breadth guard: discard any token that is suspiciously generic.
        for tok in identity.tokens():
            if tok.confidence == "HIGH" or tok.kind == "mac":
                continue
            n = index.count_matches(tok.text, tok.bounded)
            if n > TOKEN_BREADTH_LIMIT:
                identity.drop(tok.text, f"matched {n}+ keys (too broad)")
                notes.append(f"Dropped over-broad identifier {tok.text[:48]} "
                             f"({n}+ matches)")

    # Final classification pass with the settled identity set.
    hits = index.match(identity.needles())
    tok_by_text = {t.text: t for t in identity.tokens()}
    references: List[Reference] = []

    for rec_idx, in_name in hits:
        rec = index.records[rec_idx]

        if in_name:
            blocked = _is_protected(rec, adapters)
            if blocked:
                references.append(Reference(rec, False, "LOW",
                                            f"protected ({blocked}) - review only"))
                continue

        # Which tokens actually hit, and how strong are they?
        best = "LOW"
        reason = "value reference"
        leaf = rec.leaf.lower()
        hay_all = index._hay_all[rec_idx]
        matched_vals: List[str] = []

        for text, tok in tok_by_text.items():
            bounded = tok.bounded
            hit_name = _bounded_find(leaf, text) if bounded else (text in leaf)
            if hit_name:
                if tok.confidence == "HIGH":
                    best = "HIGH"
                    reason = f"key name contains {tok.kind} ({tok.origin})"
                    break
                if best != "HIGH":
                    best = "MEDIUM"
                    reason = f"key name contains {tok.kind} ({tok.origin})"
            elif best == "LOW":
                if (_bounded_find(hay_all, text) if bounded else (text in hay_all)):
                    reason = f"value references {tok.kind} ({tok.origin})"

        if not in_name:
            exact_name_hit = False
            for vn, vd, _vt in rec.values:
                vname = (vn or "").lower()
                blob = "\n".join([vname] + render_value(vd))
                for text, tok in tok_by_text.items():
                    if (_bounded_find(blob, text) if tok.bounded else (text in blob)):
                        matched_vals.append(vn or "(Default)")
                        # A value whose NAME is exactly a strong identifier --
                        # e.g. the link key under Parameters\Keys\<adapter>
                        # named after the device MAC -- is not a weak hint.
                        if tok.confidence == "HIGH" and \
                                norm_mac(vname) and norm_mac(vname) == \
                                norm_mac(text):
                            exact_name_hit = True
                            reason = (f"value name is the device "
                                      f"{tok.kind} ({tok.origin})")
                        break
            if not matched_vals:
                continue
            best = "HIGH" if exact_name_hit else "LOW"

        references.append(Reference(rec, in_name, best, reason, matched_vals))

    # Collapse: if an ancestor is already a full key delete, drop descendants.
    kill_prefixes = sorted(
        (r.record.full.lower() + "\\" for r in references
         if r.action == "DELETE_KEY" and r.confidence in ("HIGH", "MEDIUM")),
        key=len)
    pruned: List[Reference] = []
    for r in references:
        full = r.record.full.lower()
        covered = any(full.startswith(p) for p in kill_prefixes)
        if covered and r.action != "DELETE_KEY":
            continue
        if covered and r.action == "DELETE_KEY":
            if any(full.startswith(p) and full != p.rstrip("\\") for p in kill_prefixes):
                continue
        pruned.append(r)

    pruned.sort(key=lambda r: (
        {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[r.confidence],
        r.record.full.lower()))

    return Plan(device=device, references=pruned, identity=identity,
                rounds=rounds, notes=notes)


# --------------------------------------------------------------------------
# Ownership (takeown.exe does NOT work on registry keys -- do it properly)
# --------------------------------------------------------------------------

_PYWIN32 = True
try:
    import win32api
    import win32con
    import win32security
except Exception:                                   # pragma: no cover
    _PYWIN32 = False


def _enable_privileges() -> None:
    if not _PYWIN32:
        return
    try:
        tok = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY)
        for priv in ("SeTakeOwnershipPrivilege", "SeRestorePrivilege",
                     "SeBackupPrivilege", "SeSecurityPrivilege"):
            try:
                luid = win32security.LookupPrivilegeValue(None, priv)
                win32security.AdjustTokenPrivileges(
                    tok, False, [(luid, win32security.SE_PRIVILEGE_ENABLED)])
            except Exception:
                pass
    except Exception:
        pass


def take_key_ownership(hive: int, path: str) -> bool:
    """Set owner to BUILTIN\\Administrators and grant full control."""
    if not _PYWIN32:
        return False
    _enable_privileges()
    try:
        admins = win32security.CreateWellKnownSid(
            win32security.WinBuiltinAdministratorsSid)
    except Exception:
        try:
            admins, _, _ = win32security.LookupAccountName("", "Administrators")
        except Exception:
            return False

    sam_owner = win32con.WRITE_OWNER | win32con.KEY_WOW64_64KEY
    sam_dacl = (win32con.READ_CONTROL | win32con.WRITE_DAC |
                win32con.KEY_WOW64_64KEY)
    try:
        k = win32api.RegOpenKeyEx(hive, path, 0, sam_owner)
        sd = win32security.SECURITY_DESCRIPTOR()
        sd.SetSecurityDescriptorOwner(admins, False)
        win32api.RegSetKeySecurity(k, win32security.OWNER_SECURITY_INFORMATION, sd)
        k.Close()
    except Exception:
        pass

    try:
        k = win32api.RegOpenKeyEx(hive, path, 0, sam_dacl)
        sd = win32api.RegGetKeySecurity(k, win32security.DACL_SECURITY_INFORMATION)
        dacl = sd.GetSecurityDescriptorDacl()
        if dacl is None:
            dacl = win32security.ACL()
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION_DS,
            win32security.CONTAINER_INHERIT_ACE,
            win32con.KEY_ALL_ACCESS, admins)
        sd.SetSecurityDescriptorDacl(1, dacl, 0)
        win32api.RegSetKeySecurity(k, win32security.DACL_SECURITY_INFORMATION, sd)
        k.Close()
        return True
    except Exception:
        return False


def take_ownership_recursive(hive: int, path: str, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        return
    take_key_ownership(hive, path)
    for name in _subkeys(hive, path):
        take_ownership_recursive(hive, path + "\\" + name, depth + 1)


# --------------------------------------------------------------------------
# Backup
# --------------------------------------------------------------------------

class RegBackup:
    """Appends multiple `reg export` outputs into one valid .reg file.

    Gemini's scripts exported every key to the same filename with /y, so the
    backup only ever held the last key. This concatenates properly: the
    'Windows Registry Editor Version 5.00' header is kept once.
    """

    HEADER = "Windows Registry Editor Version 5.00"

    def __init__(self, path: str):
        self.path = path
        self._started = False
        self.key_count = 0

    def _write(self, text: str, mode: str) -> None:
        with open(self.path, mode, encoding="utf-16") as fh:
            fh.write(text)

    def add_key(self, hive: int, subpath: str) -> bool:
        full = f"{HIVE_NAMES[hive]}\\{subpath}"
        tmp = os.path.join(tempfile.gettempdir(),
                           f"_blueaway_{os.getpid()}_{self.key_count}.reg")
        try:
            proc = subprocess.run(
                ["reg.exe", "export", full, tmp, "/y"],
                capture_output=True, text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if proc.returncode != 0 or not os.path.exists(tmp):
                return False
            with open(tmp, "r", encoding="utf-16") as fh:
                body = fh.read()
        except Exception:
            return False
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass

        lines = body.splitlines()
        while lines and (not lines[0].strip() or
                         lines[0].strip().startswith("Windows Registry Editor")):
            lines.pop(0)
        chunk = "\r\n".join(lines).strip("\r\n")
        if not chunk:
            return False

        if not self._started:
            self._write(self.HEADER + "\r\n\r\n", "w")
            self._started = True
        self._write(chunk + "\r\n\r\n", "a")
        self.key_count += 1
        return True

    def finalize(self) -> Optional[str]:
        return self.path if self._started else None


# --------------------------------------------------------------------------
# Deletion
# --------------------------------------------------------------------------

def delete_key_tree(hive: int, path: str,
                    log: Optional[Callable[[str], None]] = None,
                    depth: int = 0) -> Tuple[int, int]:
    """Depth-first delete. Returns (deleted, failed)."""
    say = log or (lambda _m: None)
    deleted = failed = 0
    if depth > MAX_DEPTH:
        return 0, 1

    for name in _subkeys(hive, path):
        d, f = delete_key_tree(hive, path + "\\" + name, log, depth + 1)
        deleted += d
        failed += f

    parent, _, leaf = path.rpartition("\\")
    try:
        ph = winreg.OpenKey(hive, parent, 0,
                            winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY)
    except OSError:
        take_key_ownership(hive, parent)
        try:
            ph = winreg.OpenKey(hive, parent, 0,
                                winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY)
        except OSError as exc:
            say(f"    ! cannot open parent of {leaf}: {exc}")
            return deleted, failed + 1
    try:
        try:
            winreg.DeleteKeyEx(ph, leaf, winreg.KEY_WOW64_64KEY, 0)
            deleted += 1
        except PermissionError:
            take_ownership_recursive(hive, path)
            try:
                winreg.DeleteKeyEx(ph, leaf, winreg.KEY_WOW64_64KEY, 0)
                deleted += 1
            except OSError as exc:
                say(f"    ! denied: {path} ({exc})")
                failed += 1
        except OSError as exc:
            if getattr(exc, "winerror", None) == 2:
                pass  # already gone
            else:
                say(f"    ! failed: {path} ({exc})")
                failed += 1
    finally:
        ph.Close()
    return deleted, failed


def delete_values(hive: int, path: str, names: Sequence[str],
                  log: Optional[Callable[[str], None]] = None) -> Tuple[int, int]:
    say = log or (lambda _m: None)
    ok = bad = 0
    try:
        k = winreg.OpenKey(hive, path, 0,
                           winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY)
    except OSError:
        take_key_ownership(hive, path)
        try:
            k = winreg.OpenKey(hive, path, 0,
                               winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY)
        except OSError as exc:
            say(f"    ! cannot open {path}: {exc}")
            return 0, len(names)
    try:
        for n in names:
            try:
                winreg.DeleteValue(k, "" if n == "(Default)" else n)
                ok += 1
            except OSError as exc:
                say(f"    ! value {n}: {exc}")
                bad += 1
    finally:
        k.Close()
    return ok, bad


# --------------------------------------------------------------------------
# PnP / service integration
# --------------------------------------------------------------------------

def _run(cmd: Sequence[str], timeout: int = 45) -> Tuple[int, str]:
    try:
        p = subprocess.run(list(cmd), capture_output=True, text=True,
                           timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:
        return -1, str(exc)


def winrt_unpair(mac12: str, log: Optional[Callable[[str], None]] = None) -> bool:
    """Ask Windows to unpair properly first. This is the supported API and
    lets Windows clean up most of its own references; the registry sweep then
    only has to handle the leftovers."""
    say = log or (lambda _m: None)
    aqs = ("System.Devices.Aep.DeviceAddress:=\"%s\"" %
           ":".join(mac12.upper()[i:i + 2] for i in range(0, 12, 2)))
    ps = f'''
$ErrorActionPreference = "Stop"
[Windows.Devices.Enumeration.DeviceInformation,Windows.Devices.Enumeration,ContentType=WindowsRuntime] > $null
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }})[0]
function Await($op, $t) {{
    $m = $asTaskGeneric.MakeGenericMethod($t)
    $task = $m.Invoke($null, @($op)); $task.Wait(12000) > $null; $task.Result
}}
$devs = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync(
    '{aqs}', $null, [Windows.Devices.Enumeration.DeviceInformationKind]::AssociationEndpoint)
) ([Windows.Devices.Enumeration.DeviceInformationCollection])
$n = 0
foreach ($d in $devs) {{
    if ($d.Pairing -and $d.Pairing.IsPaired) {{
        $r = Await ($d.Pairing.UnpairAsync()) ([Windows.Devices.Enumeration.DeviceUnpairingResult])
        Write-Output "unpair:$($r.Status)"; $n++
    }}
}}
Write-Output "count:$n"
'''
    rc, out = _run(["powershell.exe", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=60)
    if rc == 0 and "unpair:" in out:
        say(f"  WinRT unpair: {out.strip().splitlines()[-2:]}")
        return True
    say("  WinRT unpair: nothing to unpair (or unavailable)")
    return False


def pnp_remove(instance_ids: Iterable[str],
               log: Optional[Callable[[str], None]] = None) -> int:
    say = log or (lambda _m: None)
    n = 0
    for iid in instance_ids:
        rc, out = _run(["pnputil.exe", "/remove-device", iid, "/subtree"])
        if rc != 0:
            rc, out = _run(["pnputil.exe", "/remove-device", iid])
        if rc == 0:
            n += 1
            say(f"  pnputil removed {iid}")
        else:
            say(f"  pnputil could not remove {iid}")
    return n


def restart_bluetooth(log: Optional[Callable[[str], None]] = None) -> None:
    say = log or (lambda _m: None)
    for svc in ("BTAGService", "bthserv"):
        _run(["sc.exe", "stop", svc], timeout=20)
    time.sleep(1.0)
    for svc in ("bthserv", "BTAGService"):
        _run(["sc.exe", "start", svc], timeout=20)
    say("  Bluetooth services restarted")


def restart_audio_gateway(log: Optional[Callable[[str], None]] = None) -> bool:
    """Bounce just the Bluetooth Audio Gateway Service (and the AVCTP
    service underneath it) to force Windows to re-provision the
    Hands-Free audio endpoint for whatever is currently connected --
    without touching pairing, bonding, or the registry at all.

    This is the fix for: a Bluetooth headset auto-reconnects (silently,
    outside the user's control -- normal for audio-class devices under
    Secure Simple Pairing) and Hands-Free never gets rebuilt as an
    output device, even though the underlying link is fine.
    """
    say = log or (lambda _m: None)
    ok = True
    say("[~] Restarting Bluetooth Audio Gateway Service...")
    for svc in ("bthavctpsvc", "BTAGService"):
        rc, out = _run(["sc.exe", "stop", svc], timeout=20)
        if rc not in (0, 1062):  # 1062 = service not running, fine
            say(f"    ! stop {svc} returned {rc}: {out.strip()[:120]}")
    time.sleep(1.5)
    for svc in ("BTAGService", "bthavctpsvc"):
        rc, out = _run(["sc.exe", "start", svc], timeout=20)
        if rc == 0:
            say(f"    started {svc}")
        elif rc == 1056:  # already running -- e.g. auto-started as a
                          # dependency of the service just started before it
            say(f"    {svc} already running")
        else:
            say(f"    ! start {svc} returned {rc}: {out.strip()[:120]}")
            ok = False
    say("[+] Done. Reselect the Hands-Free device in Sound settings if it "
        "doesn't reappear automatically." if ok else
        "[-] One or more services failed to restart -- try running as "
        "Administrator.")
    return ok


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------

@dataclass
class ExecResult:
    backup_path: Optional[str] = None
    keys_deleted: int = 0
    keys_failed: int = 0
    values_deleted: int = 0
    values_failed: int = 0
    pnp_removed: int = 0
    dry_run: bool = True


def execute_plan(plan: Plan, selected: Sequence[Reference], backup_dir: str,
                 dry_run: bool = True, do_unpair: bool = True,
                 do_pnp: bool = True, do_restart: bool = True,
                 log: Optional[Callable[[str], None]] = None) -> ExecResult:
    say = log or (lambda _m: None)
    res = ExecResult(dry_run=dry_run)

    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[\\/:*?"<>|]', "_", plan.device.display)[:48]
    backup_path = os.path.join(
        backup_dir, f"{safe}_{plan.device.mac}_{stamp}.reg")

    keys = [r for r in selected if r.action == "DELETE_KEY"]
    vals = [r for r in selected if r.action == "DELETE_VALUES"]

    if dry_run:
        say(f"[DRY RUN] would delete {len(keys)} keys, "
            f"edit {len(vals)} keys' values")
        for r in keys:
            say(f"  [key ] {r.record.full}")
        for r in vals:
            say(f"  [vals] {r.record.full} :: {', '.join(r.value_names)}")
        return res

    # 1. Back up everything we are about to touch.
    backup = RegBackup(backup_path)
    for r in keys + vals:
        backup.add_key(r.record.hive, r.record.path)
    res.backup_path = backup.finalize()
    say(f"[+] Backup: {res.backup_path} ({backup.key_count} keys)")

    # 2. Ask Windows to unpair cleanly before we start cutting.
    if do_unpair:
        winrt_unpair(plan.device.mac, say)

    # 3. Let PnP remove its own nodes -- cleaner than deleting Enum by hand.
    if do_pnp:
        iids = set(plan.device.instance_ids)
        for r in keys:
            m = re.match(r"SYSTEM\\CurrentControlSet\\Enum\\"
                         r"([^\\]+\\[^\\]+\\[^\\]+)$", r.record.path, re.I)
            if m:
                iids.add(m.group(1))
        res.pnp_removed = pnp_remove(sorted(iids), say)

    # 4. Delete keys deepest-first so children never orphan their parents.
    for r in sorted(keys, key=lambda x: -x.record.depth):
        d, f = delete_key_tree(r.record.hive, r.record.path, say)
        res.keys_deleted += d
        res.keys_failed += f
        if d:
            say(f"  [-] {r.record.full}")

    # 5. Surgical value removals in shared keys.
    for r in vals:
        ok, bad = delete_values(r.record.hive, r.record.path, r.value_names, say)
        res.values_deleted += ok
        res.values_failed += bad
        if ok:
            say(f"  [v] {r.record.full} :: {ok} value(s)")

    if do_restart:
        restart_bluetooth(say)

    say(f"[+] Done. {res.keys_deleted} keys deleted "
        f"({res.keys_failed} failed), {res.values_deleted} values removed.")
    return res


def plan_to_dict(plan: Plan) -> dict:
    return {
        "device": {
            "mac": plan.device.mac,
            "pretty_mac": pretty_mac(plan.device.mac),
            "name": plan.device.name,
            "kinds": sorted(plan.device.kinds),
            "instance_ids": sorted(plan.device.instance_ids),
            "container_ids": sorted(plan.device.container_ids),
        },
        "rounds": plan.rounds,
        "identifiers": [
            {"text": t.text, "kind": t.kind, "origin": t.origin,
             "confidence": t.confidence}
            for t in (plan.identity.tokens() if plan.identity else [])
        ],
        "rejected": (plan.identity.rejected if plan.identity else []),
        "notes": plan.notes,
        "references": [
            {"key": r.record.full, "action": r.action,
             "confidence": r.confidence, "reason": r.reason,
             "values": r.value_names}
            for r in plan.references
        ],
    }


def save_report(plan: Plan, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan_to_dict(plan), fh, indent=2)
    return path
