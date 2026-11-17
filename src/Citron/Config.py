"""
Citron/Config.py
Everything that understands Citron's qt-config.ini input format.

Citron is a yuzu fork and keeps yuzu's Qt INI layout. Inside [Controls], each
player owns a flat set of keys:

    player_0_connected=true
    player_0_type=0                                   (0 = Pro Controller)
    player_0_button_a="engine:sdl,port:0,guid:0300...,button:1"
    player_0_button_a\\default=false
    player_0_lstick="engine:sdl,port:0,guid:0300...,axis_x:0,axis_y:1,deadzone:0.15"
    ...

Input profiles (<config dir>/input/<name>.ini) hold the same keys without the
"player_N_" prefix.

A binding identifies its pad by two parameters:
    guid  SDL joystick GUID, 32 hex chars, with the name-CRC bytes zeroed
    port  index among the connected pads that share that GUID

So a "profile" here is just {suffix: raw value}. At launch the guid/port of
every SDL binding is rewritten to point at the pad assigned to that player,
which keeps the user's own button layout, deadzones and motion settings.

The file is edited line by line rather than through configparser: Qt's
"key\\default" companions, quoting and key order all survive untouched, and
nothing outside the player keys is ever rewritten.
"""

import glob
import json
import os
import re

from Core.Log import log, fatal

SECTION = "Controls"
MAX_PLAYERS = 8                  # player_0 .. player_7 (8 = handheld, untouched)
PRO_CONTROLLER = "0"             # Settings::ControllerType::ProController
DEFAULT_PROFILE = "RL Default"

# Per-player keys that write_input() owns; never copied from a profile
INJECTED_SUFFIXES = ("connected", "type", "profile_name")

# Vibration: global switch plus per-player switch and strength (percent)
VIBRATION_KEY = "vibration_enabled"
VIBRATION_STRENGTH = "vibration_strength"
FULL_STRENGTH = "100"

_GUID_RE = re.compile(r"(?<![A-Za-z0-9_])guid:[0-9A-Fa-f]+")
_PORT_RE = re.compile(r"(?<![A-Za-z0-9_])port:\d+")


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


def _profile_from_items(items, prefix=""):
    """Strip `prefix` and drop Qt's \\default companions and injected keys."""
    profile = {}
    for key, value in items.items():
        if not key.startswith(prefix) or "\\" in key:
            continue
        suffix = key[len(prefix):]
        if suffix and suffix not in INJECTED_SUFFIXES:
            profile[suffix] = value
    return profile


def _is_sdl_profile(profile):
    return any("engine:sdl" in v for v in profile.values())


def read_controls(config_file):
    """{key: raw value} of [Controls], or {} if the file is missing/unreadable."""
    try:
        return _section_items(_read_lines(config_file), SECTION)
    except Exception:
        return {}


# ============================================================================
# TEMPLATE + PROFILES
# ============================================================================
def load_template(config_file):
    """
    The user's own SDL mapping, taken from the first connected player that is
    bound to an SDL pad. Returns {} when there is none (fresh install, or only
    keyboard bindings).
    """
    if not os.path.exists(config_file):
        return {}

    try:
        items = _section_items(_read_lines(config_file), SECTION)
    except Exception as e:
        log("EXCEPTION", "Config read exception", e)
        fatal(
            "Configuration Error",
            "Could not read the Citron config file.\n\n"
            "Please open Citron manually once to generate valid configuration files.\n"
            "Then try launching this tool again."
        )

    for i in range(MAX_PLAYERS):
        prefix = f"player_{i}_"
        if items.get(prefix + "connected", "").strip().lower() != "true":
            continue
        profile = _profile_from_items(items, prefix)
        if _is_sdl_profile(profile):
            log("INFO", "Default mapping taken from", f"player_{i}")
            return profile
    return {}


def load_profiles(config_file, template):
    """
    {"display name": {suffix: raw value}}, insertion-ordered.

    "RL Default" (the template) comes first when available, then every
    <config dir>/input/*.ini. A profile literally named "RL Default" replaces
    the built-in one. Keyboard-only profiles are skipped: the launcher assigns
    gamepads, and rebinding a keyboard profile to a pad would do nothing.
    """
    profiles = {}
    if template:
        profiles[DEFAULT_PROFILE] = template

    profiles_dir = os.path.join(os.path.dirname(config_file), "input")
    for filepath in sorted(glob.glob(os.path.join(profiles_dir, "*.ini"))):
        name = os.path.splitext(os.path.basename(filepath))[0]
        try:
            profile = _profile_from_items(_section_items(_read_lines(filepath), SECTION))
        except Exception as e:
            log("WARNING", "Skipping unreadable profile", filepath)
            log("EXCEPTION", "Profile load exception", e)
            continue
        if not _is_sdl_profile(profile):
            log("INFO", "Skipping non-gamepad profile", name)
            continue
        profiles[name] = profile

    if DEFAULT_PROFILE in profiles and next(iter(profiles)) != DEFAULT_PROFILE:
        # an on-disk "RL Default" still has to be the first entry
        profiles = {DEFAULT_PROFILE: profiles.pop(DEFAULT_PROFILE), **profiles}

    if not profiles:
        fatal(
            "Controller Setup Required",
            "No gamepad mapping was found in Citron.\n\n"
            "Open Citron once, go to Emulation > Configure > Controls, map any "
            "controller to Player 1 and press OK.\n"
            "The launcher reuses that mapping for every controller.",
            "No SDL mapping found", config_file
        )

    log("INFO", "Profiles loaded", str(len(profiles)))
    return profiles


# ============================================================================
# GUID
# ============================================================================
def guid_fix(raw_hex):
    """
    SDL GUID -> the form Citron stores. Citron (like yuzu) zeroes bytes 2-3, the
    controller-name CRC SDL embeds, so the same model matches regardless of
    the name the driver reports.
    """
    raw_hex = raw_hex.lower()
    if len(raw_hex) < 32:
        return raw_hex
    return raw_hex[:4] + "0000" + raw_hex[8:]


# ----------------------------------------------------------------------------
# Learning the GUIDs Citron itself sees
#
# Bytes 12-13 of an SDL GUID hold the product version, and on Windows Citron's
# SDL and the launcher's SDL do not always read the same one for the same pad
# (e.g. Citron 0x0100, launcher 0x0000). Citron matches GUIDs exactly, so a pad is
# only found when the launcher writes Citron's version. That version cannot be
# computed here, but it can be learned: any GUID in qt-config.ini or input/*.ini
# that equals the launcher's except for those bytes was written by Citron.
# Learned GUIDs are cached, because the player slot holding one is overwritten
# as soon as another pad is assigned to it.
# ----------------------------------------------------------------------------
_GUID_VALUE_RE = re.compile(r"(?<![A-Za-z0-9_])guid:([0-9A-Fa-f]{32})")
GUID_CACHE_FILE = "CitronLauncher-guids.json"


def _signature(guid):
    """GUID with the product version (bytes 12-13) blanked out."""
    return guid[:24] + "0000" + guid[28:]


def _cache_path(config_file):
    return os.path.join(os.path.dirname(config_file), GUID_CACHE_FILE)


def _known_guids(config_file, existing, profiles):
    """
    {signature: [guid, ...]} - cached GUIDs first, then every SDL GUID found in
    [Controls] and in the loaded profiles.
    """
    known = {}
    try:
        with open(_cache_path(config_file), "r", encoding="utf-8") as f:
            for guid in json.load(f).values():
                known.setdefault(_signature(guid), []).append(guid.lower())
    except FileNotFoundError:
        pass
    except Exception as e:
        log("WARNING", "Ignoring unreadable GUID cache", e)

    values = list(existing.values())
    for profile in profiles.values():
        values.extend(profile.values())
    for value in values:
        for guid in _GUID_VALUE_RE.findall(value):
            guid = guid.lower()
            sig = _signature(guid)
            if guid not in known.setdefault(sig, []):
                known[sig].append(guid)

    return known


def _citron_guid(guid, known, config_file):
    """
    The GUID Citron uses for this pad: a known one that differs from the
    launcher's only in the product version, else the launcher's own.
    """
    candidates = [g for g in known.get(_signature(guid), []) if g != guid]
    if not candidates:
        return guid

    learned = candidates[0]
    log("INFO", "Using Citron's GUID", f"{guid} -> {learned}")
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
    return _PORT_RE.sub(f"port:{port}", value)


# ============================================================================
# WRITING THE LAUNCH CONFIG
# ============================================================================
def write_input(config_file, assignments, hardware, profiles):
    """
    Rewrite players 0-7 in [Controls] for this launch. Every other line of
    qt-config.ini is left exactly as it was.
    """
    if not os.path.exists(config_file):
        log("WARNING", "Config not found, nothing written", config_file)
        return

    try:
        lines = _read_lines(config_file)
    except Exception as e:
        log("EXCEPTION", "Config read failed, Citron will use the old config", e)
        return
    existing = _section_items(lines, SECTION)

    known = _known_guids(config_file, existing, profiles)

    # Citron's "port" counts pads sharing a GUID, in enumeration order, across
    # every connected pad - not just the assigned ones
    enumerated = {}
    counters = {}
    for hw in hardware:
        guid = _citron_guid(guid_fix(hw["guid"]), known, config_file)
        enumerated[hw["path"]] = (guid, counters.get(guid, 0), hw["name"])
        counters[guid] = counters.get(guid, 0) + 1

    updates = {}  # key -> raw value (ordered)
    player = 0
    for assignment in assignments:
        matched = enumerated.get(assignment["path"])
        if not matched:
            continue
        guid, port, name = matched
        prefix = f"player_{player}_"
        log("INFO", f"Saving -> Player {player+1} | {name} | Profile: {assignment['profile_key']} | port {port} | guid {guid}")

        updates[prefix + "connected"] = "true"
        updates[prefix + "type"] = PRO_CONTROLLER
        # Bindings the profile does not define must not keep pointing at
        # whichever pad this player slot had last time
        for suffix, value in _profile_from_items(existing, prefix).items():
            if "engine:sdl" in value:
                updates[prefix + suffix] = _retarget(value, guid, port)
        for suffix, value in profiles[assignment["profile_key"]].items():
            updates[prefix + suffix] = _retarget(value, guid, port)
        # Vibration on for every assigned pad (a strength of 0 is no vibration)
        updates[prefix + VIBRATION_KEY] = "true"
        strength = updates.get(prefix + VIBRATION_STRENGTH,
                               existing.get(prefix + VIBRATION_STRENGTH, "")).strip()
        if not strength.isdigit() or int(strength) <= 0:
            updates[prefix + VIBRATION_STRENGTH] = FULL_STRENGTH
        player += 1

    if player:
        updates[VIBRATION_KEY] = "true"

    for i in range(player, MAX_PLAYERS):
        updates[f"player_{i}_connected"] = "false"

    # Qt marks values equal to the built-in default with key\default=true and
    # then ignores the stored value - force every written key to be honoured
    for key in list(updates):
        updates[key + "\\default"] = "false"

    _apply(lines, SECTION, updates)

    try:
        with open(config_file, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        log("EXCEPTION", "Config write failed, Citron will use the old config", e)


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

    # insert before trailing blank lines so the section stays visually grouped
    insert_at = end
    while insert_at > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines[insert_at:insert_at] = pending
