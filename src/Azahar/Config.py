"""
Azahar/Config.py
Everything that understands AzaharPlus's qt-config.ini input format.

Azahar (a Citra fork) has a single player. Its [Controls] section holds a Qt
array of input profiles plus the index of the active one
(src/citra_qt/configuration/config.cpp, ReadControlValues):

    profile=0                                   active profile, 0-based
    profiles\\size=2
    profiles\\1\\name=Default
    profiles\\1\\button_a="engine:sdl,guid:0300...,port:0,api:controller,button:1"
    profiles\\1\\circle_pad="engine:sdl,guid:0300...,port:0,axis_x:0,axis_y:1"
    profiles\\2\\name=Pro Controller
    ...

A binding identifies its pad by:
    guid  full SDL joystick GUID string (32 hex)
    port  index among the connected pads that share that GUID

So the launcher's profiles ARE Azahar's profiles. At launch the chosen one
becomes active and every SDL binding inside it is pointed at the assigned
pad. Other profiles and every other line stay untouched: the file is edited
line by line, keeping Qt's quoting and "\\default" companions.
"""

import json
import os
import re

from Core.Log import log, fatal

SECTION = "Controls"
GUID_CACHE_FILE = "AzaharLauncher-guids.json"

_PROFILE_KEY_RE = re.compile(r"^profiles\\(\d+)\\(.+)$")
_GUID_RE = re.compile(r"(?<![A-Za-z0-9_])guid:[0-9A-Fa-f]+")
_GUID_VALUE_RE = re.compile(r"(?<![A-Za-z0-9_])guid:([0-9A-Fa-f]{32})")
_PORT_RE = re.compile(r"(?<![A-Za-z0-9_])port:-?\d+")


# ============================================================================
# QT INI - minimal line-preserving reader/writer
# ============================================================================
def _read_lines(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        return f.read().splitlines()


def _section_bounds(lines, section):
    """Return (start, end) line indices of a section's body, or None."""
    header = f"[{section}]"
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if start is None:
            if stripped == header:
                start = i + 1
        elif stripped.startswith("[") and stripped.endswith("]"):
            return start, i
    return (start, len(lines)) if start is not None else None


def _section_items(lines, section):
    """{key: raw value} for one section. Values keep their Qt quoting."""
    bounds = _section_bounds(lines, section)
    if not bounds:
        return {}
    items = {}
    for line in lines[bounds[0]:bounds[1]]:
        if "=" in line and not line.lstrip().startswith((";", "#")):
            key, value = line.split("=", 1)
            items[key.strip()] = value
    return items


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def _profiles(items):
    """{array index (1-based): {field: raw value}} from [Controls]."""
    profiles = {}
    for key, value in items.items():
        match = _PROFILE_KEY_RE.match(key)
        if not match or match.group(2).endswith("\\default"):
            continue
        profiles.setdefault(int(match.group(1)), {})[match.group(2)] = value
    return dict(sorted(profiles.items()))


def _is_sdl_profile(fields):
    return any("engine:sdl" in v for v in fields.values())


def _active_index(items, count):
    """1-based array index of the active profile, clamped like Azahar does."""
    try:
        active = int(_unquote(items.get("profile", "0")))
    except ValueError:
        active = 0
    return min(max(active, 0), max(count - 1, 0)) + 1


# ============================================================================
# PROFILES
# ============================================================================
def load_profiles(config_file):
    """
    {"display name": array index}, insertion-ordered, gamepad profiles only.

    The profile active in Azahar comes first, so a newly assigned pad keeps
    what the user picked last time in Azahar itself.
    """
    if not os.path.exists(config_file):
        _setup_required(config_file)

    try:
        items = _section_items(_read_lines(config_file), SECTION)
    except Exception as e:
        log("EXCEPTION", "Config read exception", e)
        fatal(
            "Configuration Error",
            "Could not read the Azahar config file.\n\n"
            "Please open Azahar manually once to generate valid configuration files.\n"
            "Then try launching this tool again."
        )

    stored = _profiles(items)
    active = _active_index(items, len(stored))

    profiles = {}
    order = sorted(stored, key=lambda i: i != active)   # active one first
    for index in order:
        fields = stored[index]
        name = _unquote(fields.get("name", f"Profile {index}")) or f"Profile {index}"
        if not _is_sdl_profile(fields):
            log("INFO", "Skipping non-gamepad profile", name)
            continue
        if name in profiles:
            name = f"{name} ({index})"
        profiles[name] = index

    if not profiles:
        _setup_required(config_file)

    log("INFO", "Profiles loaded", str(len(profiles)))
    return profiles


def _setup_required(config_file):
    fatal(
        "Controller Setup Required",
        "No gamepad mapping was found in Azahar.\n\n"
        "Open Azahar once, go to Emulation > Configure > Controls, map any "
        "controller and press OK.\n"
        "The launcher reuses that mapping for the controller you assign.",
        "No SDL mapping found", config_file
    )


# ============================================================================
# GUID
#
# Azahar stores the full SDL GUID string. Azahar's SDL2 and the launcher's SDL
# may disagree on three parts of it for the same pad: bytes 2-3 (the name CRC,
# filled only by newer SDL), bytes 12-13 (the product version) and bytes 14-15
# (the driver: Azahar may see a pad through RawInput, 'r' = 72, while the
# launcher sees it through XInput, 'x' = 78). Azahar
# matches GUIDs exactly, so the launcher learns the GUID Azahar wrote for this
# model from qt-config.ini and keeps it in a cache, because the binding that
# held it is overwritten as soon as another pad is assigned.
# ============================================================================
def _signature(guid):
    """Bus, vendor and product only: CRC, version and driver are blanked out."""
    guid = guid.lower()
    return guid[:4] + "0000" + guid[8:24] + "00000000"


def _cache_path(config_file):
    return os.path.join(os.path.dirname(config_file), GUID_CACHE_FILE)


def _known_guids(config_file, items):
    """{signature: [guid, ...]} - cached GUIDs first, then those in [Controls]."""
    known = {}
    try:
        with open(_cache_path(config_file), "r", encoding="utf-8") as f:
            for guid in json.load(f).values():
                known.setdefault(_signature(guid), []).append(guid.lower())
    except FileNotFoundError:
        pass
    except Exception as e:
        log("WARNING", "Ignoring unreadable GUID cache", e)

    for value in items.values():
        for guid in _GUID_VALUE_RE.findall(value):
            guid = guid.lower()
            if guid not in known.setdefault(_signature(guid), []):
                known[_signature(guid)].append(guid)
    return known


RAWINPUT_DRIVER = "72"   # GUID byte 14 = 'r'


def _driver(guid):
    return guid[28:30]


def _azahar_guid(guid, known, config_file):
    guid = guid.lower()
    # With RawInput on (Azahar.prepare) the launcher sees XInput pads the way
    # Azahar's SDL2 does, so a RawInput GUID is already Azahar's. Learning it
    # instead could pick up a stale XInput GUID an older launcher build wrote.
    if _driver(guid) == RAWINPUT_DRIVER:
        return guid

    # Otherwise any other GUID for the same model may be the one Azahar's SDL
    # produced; RawInput ones first, since those can only come from Azahar
    candidates = [g for g in known.get(_signature(guid), []) if g != guid]
    candidates.sort(key=lambda g: _driver(g) != RAWINPUT_DRIVER)
    if not candidates:
        return guid
    learned = candidates[0]
    log("INFO", "Using Azahar's GUID", f"{guid} -> {learned}")
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


def _retarget(value, guid, port):
    """Point every SDL binding in a raw value at the given pad."""
    if "engine:sdl" not in value:
        return value
    value = _GUID_RE.sub(f"guid:{guid}", value)
    if _PORT_RE.search(value):
        return _PORT_RE.sub(f"port:{port}", value)
    return value.replace("engine:sdl", f"engine:sdl,port:{port}", 1)


# ============================================================================
# WRITING THE LAUNCH CONFIG
# ============================================================================
def write_input(config_file, assignments, hardware, profiles):
    """
    Activate the chosen profile and point its SDL bindings at the assigned
    pad. Azahar has one player, so only the first assignment is used.
    """
    if not assignments:
        return
    if not os.path.exists(config_file):
        log("WARNING", "Config not found, nothing written", config_file)
        return

    try:
        lines = _read_lines(config_file)
    except Exception as e:
        log("EXCEPTION", "Config read failed, Azahar will use the old config", e)
        return
    items = _section_items(lines, SECTION)
    known = _known_guids(config_file, items)

    # "port" counts pads sharing a GUID, in enumeration order
    enumerated = {}
    counters = {}
    for hw in hardware:
        guid = _azahar_guid(hw["guid"], known, config_file)
        enumerated[hw["path"]] = (guid, counters.get(guid, 0), hw["name"])
        counters[guid] = counters.get(guid, 0) + 1

    assignment = assignments[0]
    matched = enumerated.get(assignment["path"])
    if not matched:
        return
    guid, port, name = matched
    index = profiles[assignment["profile_key"]]
    log("INFO", f"Saving -> Player 1 | {name} | Profile: {assignment['profile_key']} | port {port} | guid {guid}")

    stored = _profiles(items)
    updates = {"profile": str(index - 1), "profile\\default": "false"}
    for field, value in stored.get(index, {}).items():
        if "engine:sdl" in value:
            updates[f"profiles\\{index}\\{field}"] = _retarget(value, guid, port)

    _apply(lines, SECTION, updates)

    try:
        with open(config_file, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        log("EXCEPTION", "Config write failed, Azahar will use the old config", e)


def _apply(lines, section, updates):
    """Replace keys in place; append missing ones at the end of the section."""
    bounds = _section_bounds(lines, section)
    if not bounds:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{section}]")
        bounds = (len(lines), len(lines))

    start, end = bounds
    index = {}
    for i in range(start, end):
        if "=" in lines[i]:
            index[lines[i].split("=", 1)[0].strip()] = i

    pending = []
    for key, value in updates.items():
        if key in index:
            lines[index[key]] = f"{key}={value}"
        else:
            pending.append(f"{key}={value}")

    insert_at = end
    while insert_at > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines[insert_at:insert_at] = pending
