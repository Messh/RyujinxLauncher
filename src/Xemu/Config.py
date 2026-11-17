"""
Xemu/Config.py
Everything that understands xemu's xemu.toml input bindings.

xemu (config_spec.yml, ui/xemu-input.c) binds up to 4 ports by SDL GUID:

    [input.bindings]
    port1_driver = 'usb-xbox-gamepad'
    port1 = '03000000...'          # SDL GUID string, or 'keyboard'

When a pad connects, xemu puts it on the first unbound port whose GUID equals
the pad's GUID exactly (strcmp). So two identical pads cannot be told apart;
they fill matching ports in connection order.

Button layout is not part of the binding (xemu maps every pad the same way,
with optional per-GUID [[input.gamepad_mappings]]), so there is a single
"Default" profile.

GUIDs: xemu's statically linked SDL3 and the launcher's SDL can report
different GUIDs for the same pad (name CRC, version and driver bytes, and for
XInput pads even VID/PID). The launcher learns xemu's GUID two ways and keeps
it in a cache:
  - by model (bus/vendor/product) from the GUIDs already in xemu.toml;
  - exactly, for pads xemu had never seen: their GUID matches no port, so
    xemu auto-binds them to the free port the launcher wrote and saves its
    own GUID there; the next launch reads it back.
"""

import json
import os
import re

from Core.Log import log

from . import Toml

PORTS = 4
DEFAULT_DRIVER = "usb-xbox-gamepad"
DEFAULT_PROFILE = "Default"
GUID_CACHE_FILE = "XemuLauncher-guids.json"

_GUID_VALUE_RE = re.compile(r"""["']([0-9A-Fa-f]{32})["']""")

# Vibration: per-pad enable_rumble in [[input.gamepad_mappings]] (default
# true), and the deprecated global allow_vibration
MAPPINGS_HEADER = "input.gamepad_mappings"
_HEADER_RE = re.compile(r"^\s*\[")
_ARRAY_HEADER_RE = re.compile(r"^\s*\[\[\s*([^\]]+?)\s*\]\]")
_ASSIGN_RE = re.compile(r"^(\s*)([A-Za-z0-9_-]+)\s*=\s*(.*)$")


def _read_lines(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        return f.read().splitlines()


def _write_lines(path, lines):
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def load_profiles():
    return {DEFAULT_PROFILE: None}


# ============================================================================
# GUID learning
# ============================================================================
# Cache file (next to xemu.toml):
#     {"signatures": {signature: xemu guid},     learned from xemu.toml
#      "exact":      {launcher guid: xemu guid}, learned by diffing ports
#      "written":    {"1".."4": launcher guid}}  what the last launch wrote
# Older versions stored the "signatures" dict flat at the top level.
def _signature(guid):
    """Bus, vendor and product only: CRC, version and driver are blanked out."""
    guid = guid.lower()
    return guid[:4] + "0000" + guid[8:24] + "00000000"


def _cache_path(config_file):
    return os.path.join(os.path.dirname(config_file), GUID_CACHE_FILE)


def _load_cache(config_file):
    cache = {"signatures": {}, "exact": {}, "written": {}}
    try:
        with open(_cache_path(config_file), "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return cache
    except Exception as e:
        log("WARNING", "Ignoring unreadable GUID cache", e)
        return cache
    if not isinstance(data, dict):
        return cache
    if any(k in data for k in cache):
        for k in cache:
            if isinstance(data.get(k), dict):
                cache[k] = {str(a).lower(): str(b).lower() for a, b in data[k].items()}
    else:  # old flat format
        cache["signatures"] = {str(a).lower(): str(b).lower() for a, b in data.items()}
    return cache


def _save_cache(config_file, cache):
    try:
        with open(_cache_path(config_file), "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        log("WARNING", "Could not save GUID cache", e)


def _known_guids(cache, lines):
    known = {}
    for guid in cache["signatures"].values():
        known.setdefault(_signature(guid), []).append(guid)
    for guid in _GUID_VALUE_RE.findall("\n".join(lines)):
        guid = guid.lower()
        if guid not in known.setdefault(_signature(guid), []):
            known[_signature(guid)].append(guid)
    return known


def _learn_from_last_run(cache, lines, hardware):
    """
    xemu's statically linked SDL3 may report a pad with a GUID that shares
    nothing with the launcher's (e.g. the launcher sees a generic
    "XInput Controller" with no VID/PID, xemu sees the real ones). Such a pad
    does not match the port the launcher wrote, so xemu auto-binds it to that
    same free port and saves its own GUID there. Comparing the port with what
    the launcher wrote last time reveals xemu's GUID for that pad.
    """
    written = cache["written"]
    connected = {hw["guid"].lower() for hw in hardware}
    for port, ours in written.items():
        now = Toml.get(lines, f"input.bindings.port{port}")
        if not isinstance(now, str) or not _GUID_VALUE_RE.fullmatch(f"'{now}'"):
            continue
        now = now.lower()
        if now == ours or cache["exact"].get(ours) == now:
            continue
        # Another pad the launcher can see (or wrote elsewhere) took the port
        if now in connected or now in written.values() or now in cache["exact"].values():
            continue
        cache["exact"][ours] = now
        log("INFO", "Learned xemu's GUID from its last binding", f"{ours} -> {now}")
    cache["written"] = {}


def _xemu_guid(guid, known, cache):
    """xemu's GUID for a pad, and whether it is already confirmed."""
    guid = guid.lower()
    if guid in cache["exact"]:
        learned = cache["exact"][guid]
        log("INFO", "Using xemu's learned GUID", f"{guid} -> {learned}")
        return learned, True
    candidates = [g for g in known.get(_signature(guid), []) if g != guid]
    if not candidates:
        return guid, False
    learned = candidates[0]
    log("INFO", "Using xemu's GUID", f"{guid} -> {learned}")
    cache["signatures"][_signature(learned)] = learned
    return learned, True


# ============================================================================
# VIBRATION
# ============================================================================
def _enable_rumble(lines, guids):
    """
    Turn vibration back on wherever it was switched off for an assigned pad.
    xemu vibrates by default, so only explicit "false" values are changed.
    """
    if Toml.get(lines, "input.allow_vibration") in (False, "false"):
        Toml.set_raw(lines, "input.allow_vibration", "true")
        log("INFO", "Vibration enabled", "input.allow_vibration = true")

    block, gamepad, rumble_line = False, None, None

    def flush():
        if block and gamepad in guids and rumble_line is not None:
            indent, key, _ = _ASSIGN_RE.match(lines[rumble_line]).groups()
            lines[rumble_line] = f"{indent}{key} = true"
            log("INFO", "Vibration enabled", f"gamepad_mappings {gamepad}")

    for i, line in enumerate(lines):
        if _HEADER_RE.match(line):
            flush()
            m = _ARRAY_HEADER_RE.match(line)
            block = bool(m) and m.group(1).replace(" ", "") == MAPPINGS_HEADER
            gamepad, rumble_line = None, None
            continue
        m = _ASSIGN_RE.match(line) if block else None
        if not m:
            continue
        key, value = m.group(2), m.group(3).split("#", 1)[0].strip()
        if key == "gamepad_id":
            gamepad = value.strip("\"'").lower()
        elif key == "enable_rumble" and value == "false":
            rumble_line = i
    flush()


# ============================================================================
# WRITING THE LAUNCH CONFIG
# ============================================================================
def write_input(config_file, assignments, hardware):
    """Bind ports 1-4 to the assigned pads; clear the remaining ports."""
    lines = []
    if os.path.exists(config_file):
        try:
            lines = _read_lines(config_file)
        except Exception as e:
            log("EXCEPTION", "Config read failed, xemu will use the old config", e)
            return

    cache = _load_cache(config_file)
    _learn_from_last_run(cache, lines, hardware)
    known = _known_guids(cache, lines)
    pads = {hw["path"]: hw for hw in hardware}

    port = 0
    unconfirmed = False
    written_guids = set()
    for assignment in assignments:
        hw = pads.get(assignment["path"])
        if not hw or port >= PORTS:
            continue
        port += 1
        guid, confirmed = _xemu_guid(hw["guid"], known, cache)
        if not confirmed:
            unconfirmed = True
            cache["written"][str(port)] = guid
        log("INFO", f"Saving -> Player {port} | {hw['name']} | port{port} | guid {guid}"
                    + ("" if confirmed else " (not confirmed by xemu yet)"))
        Toml.set(lines, f"input.bindings.port{port}", guid)
        written_guids.add(guid)
        if not Toml.get(lines, f"input.bindings.port{port}_driver"):
            Toml.set(lines, f"input.bindings.port{port}_driver", DEFAULT_DRIVER)

    # A stale GUID on a free port would grab an unassigned pad of that model
    for free in range(port + 1, PORTS + 1):
        if Toml.get(lines, f"input.bindings.port{free}") is not None:
            Toml.set(lines, f"input.bindings.port{free}", "")

    # A pad xemu has never seen may report a different GUID there. It then
    # matches no port, and only auto_bind puts it on the (free) port we wrote
    if unconfirmed and Toml.get(lines, "input.auto_bind") not in (None, True, "true"):
        Toml.set_raw(lines, "input.auto_bind", "true")
        log("INFO", "auto_bind enabled so xemu binds pads it has not seen yet")

    _enable_rumble(lines, written_guids)
    _save_cache(config_file, cache)

    try:
        _write_lines(config_file, lines)
    except Exception as e:
        log("EXCEPTION", "Config write failed, xemu will use the old config", e)
