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
different GUIDs for the same pad (name CRC, version and driver bytes). The
launcher learns the GUID xemu wrote for a model from xemu.toml and keeps it
in a cache, like the other GUID-based launchers.
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
def _signature(guid):
    """Bus, vendor and product only: CRC, version and driver are blanked out."""
    guid = guid.lower()
    return guid[:4] + "0000" + guid[8:24] + "00000000"


def _cache_path(config_file):
    return os.path.join(os.path.dirname(config_file), GUID_CACHE_FILE)


def _known_guids(config_file, lines):
    known = {}
    try:
        with open(_cache_path(config_file), "r", encoding="utf-8") as f:
            for guid in json.load(f).values():
                known.setdefault(_signature(guid), []).append(guid.lower())
    except FileNotFoundError:
        pass
    except Exception as e:
        log("WARNING", "Ignoring unreadable GUID cache", e)

    for guid in _GUID_VALUE_RE.findall("\n".join(lines)):
        guid = guid.lower()
        if guid not in known.setdefault(_signature(guid), []):
            known[_signature(guid)].append(guid)
    return known


def _xemu_guid(guid, known, config_file):
    guid = guid.lower()
    candidates = [g for g in known.get(_signature(guid), []) if g != guid]
    if not candidates:
        return guid
    learned = candidates[0]
    log("INFO", "Using xemu's GUID", f"{guid} -> {learned}")
    _remember(config_file, learned)
    return learned


def _remember(config_file, guid):
    path = _cache_path(config_file)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    if cache.get(_signature(guid)) == guid:
        return
    cache[_signature(guid)] = guid
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        log("WARNING", "Could not save GUID cache", e)


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

    known = _known_guids(config_file, lines)
    pads = {hw["path"]: hw for hw in hardware}

    port = 0
    for assignment in assignments:
        hw = pads.get(assignment["path"])
        if not hw or port >= PORTS:
            continue
        port += 1
        guid = _xemu_guid(hw["guid"], known, config_file)
        log("INFO", f"Saving -> Player {port} | {hw['name']} | port{port} | guid {guid}")
        Toml.set(lines, f"input.bindings.port{port}", guid)
        if not Toml.get(lines, f"input.bindings.port{port}_driver"):
            Toml.set(lines, f"input.bindings.port{port}_driver", DEFAULT_DRIVER)

    # A stale GUID on a free port would grab an unassigned pad of that model
    for free in range(port + 1, PORTS + 1):
        if Toml.get(lines, f"input.bindings.port{free}") is not None:
            Toml.set(lines, f"input.bindings.port{free}", "")

    try:
        _write_lines(config_file, lines)
    except Exception as e:
        log("EXCEPTION", "Config write failed, xemu will use the old config", e)
