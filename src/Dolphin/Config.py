"""
Dolphin/Config.py
Everything that understands Dolphin's GameCube controller ini files.

GCPadNew.ini has one section per GameCube port, [GCPad1]..[GCPad4]:

    [GCPad1]
    Device = XInput/0/Gamepad          <source>/<id>/<name>
    Buttons/A = `Button B`
    Main Stick/Up = `Left Y+`
    ...

Device names (ControllerInterface, CoreDevice.cpp AddDevice):
    XInput/<slot>/Gamepad    Dolphin's XInput backend; id = XInput user index
    SDL/<n>/<name>           SDL3 backend; name = SDL_GetGamepadName, n = the
                             lowest id free among SDL devices of that name,
                             i.e. their order of appearance
Xbox-style pads are written as XInput/<slot>; any other pad as SDL/<n>.
SDL's gamepads also accept the XInput button names ("Button A" = south), so
a mapping made on an XInput pad works on an SDL pad unchanged. The other
way round, SDL's "Button S/E/W/N" are translated to "Button A/B/X/Y".

A profile is the key/value set of [GCPad1] (the "Default" profile) or of a
Profiles/GCPad/<name>.ini [Profile] section. At launch each assigned port's
section is rebuilt as Device + profile, so the user's layout, calibration
and rumble are kept.

Dolphin.ini [Core] SIDevice0..3 says what is plugged into each port
(SIDEVICE_NONE = 0, SIDEVICE_GC_CONTROLLER = 6). Assigned ports that are
empty get a GameCube controller; unassigned ports holding a GameCube
controller are emptied, so no stale mapping drives a second player. Other
device types (GBA, keyboard, bongos...) are left alone.

Hotkeys.ini [Hotkeys] "Emulation Speed/Disable Emulation Speed Limit" is a
held hotkey (fast-forward while held). R3 of player 1's pad is added to it
as a device-qualified term (`<device>:Thumb R`), OR-ed with the user's own
binding. Dolphin has no rewind and no slow-motion hotkey.

Files are edited line by line; nothing else is touched.
"""

import glob
import os
import re

from Core.Log import log, fatal

PORTS = 4
DEFAULT_PROFILE = "Default"
TEMPLATE_SECTION = "GCPad1"

XINPUT_SLOTS = 4
XINPUT_DRIVER = "78"          # SDL GUID byte 14 = 'x'
SDL_TO_XINPUT = {"Button S": "Button A", "Button E": "Button B",
                 "Button W": "Button X", "Button N": "Button Y"}

SI_NONE = "0"
SI_GC_CONTROLLER = "6"

FAST_FORWARD_KEY = "Emulation Speed/Disable Emulation Speed Limit"
FAST_FORWARD_INPUT = "Thumb R"
# A term this launcher added before: `<any device>:Thumb R`
_FF_TERM_RE = re.compile(r"\s*\|?\s*`[^`]+:" + re.escape(FAST_FORWARD_INPUT) + r"`")

_SECTION_RE = re.compile(r"^\s*\[(.+)\]\s*$")
_SDL_NAME_RE = re.compile(r"\bButton [SEWN]\b")


# ============================================================================
# INI - minimal line-preserving reader/writer ("Key = Value")
# ============================================================================
def _read_lines(path):
    with open(path, "r", encoding="utf-8-sig", errors="surrogateescape") as f:
        return f.read().splitlines()


def _write_lines(path, lines):
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def _section_bounds(lines, section):
    start = None
    for i, line in enumerate(lines):
        match = _SECTION_RE.match(line)
        if start is None:
            if match and match.group(1).strip() == section:
                start = i + 1
        elif match:
            return start, i
    return (start, len(lines)) if start is not None else None


def _items(lines, section):
    bounds = _section_bounds(lines, section)
    items = {}
    if bounds:
        for line in lines[bounds[0]:bounds[1]]:
            if "=" in line and not line.lstrip().startswith((";", "#")):
                key, value = line.split("=", 1)
                items[key.strip()] = value.strip()
    return items


def read_section(path, section):
    try:
        return _items(_read_lines(path), section) if os.path.exists(path) else {}
    except OSError:
        return {}


def _replace_section(lines, section, items):
    """Rebuild a whole section with `items` (in order)."""
    body = [f"{k} = {v}" for k, v in items.items()]
    bounds = _section_bounds(lines, section)
    if not bounds:
        lines += [f"[{section}]"] + body
        return
    start, end = bounds
    lines[start:end] = body


def _set_key(lines, section, key, value):
    bounds = _section_bounds(lines, section)
    if not bounds:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]", f"{key} = {value}"]
        return
    start, end = bounds
    for i in range(start, end):
        if "=" in lines[i] and lines[i].split("=", 1)[0].strip() == key:
            lines[i] = f"{key} = {value}"
            return
    insert_at = end
    while insert_at > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, f"{key} = {value}")


# ============================================================================
# PROFILES
# ============================================================================
def load_profiles(config_file, profiles_dir):
    """{name: {key: value}} - [GCPad1] first, then Profiles/GCPad/*.ini."""
    template = {k: v for k, v in read_section(config_file, TEMPLATE_SECTION).items() if k != "Device"}
    if not any(v for v in template.values()):
        fatal(
            "Controller Setup Required",
            "No GameCube controller mapping was found in Dolphin.\n\n"
            "Open Dolphin, go to Controllers > GameCube Port 1 > Configure, "
            "pick your controller as Device, map the buttons (or use Default) "
            "and close Dolphin.\n"
            "The launcher reuses that mapping for every controller you assign.",
            "No [GCPad1] mapping found", config_file
        )
    profiles = {DEFAULT_PROFILE: template}
    for path in sorted(glob.glob(os.path.join(profiles_dir, "*.ini"))):
        items = {k: v for k, v in read_section(path, "Profile").items() if k != "Device"}
        if items:
            profiles[os.path.splitext(os.path.basename(path))[0]] = items
    log("INFO", "GameCube profiles", ", ".join(profiles))
    return profiles


# ============================================================================
# DEVICES
# ============================================================================
def _is_xinput(hw):
    return (hw["guid"].lower()[28:30] == XINPUT_DRIVER
            and 0 <= hw.get("player_index", -1) < XINPUT_SLOTS)


def device_names(hardware):
    """{path: Dolphin device string} for every scanned pad."""
    names, seen = {}, {}
    for hw in hardware:
        n = seen.get(hw["name"], 0)
        seen[hw["name"]] = n + 1        # SDL sees every pad, XInput ones too
        if _is_xinput(hw):
            names[hw["path"]] = f"XInput/{hw['player_index']}/Gamepad"
        else:
            names[hw["path"]] = f"SDL/{n}/{hw['name']}"
    return names


def _for_device(profile, device):
    if not device.startswith("XInput/"):
        return dict(profile)
    return {k: _SDL_NAME_RE.sub(lambda m: SDL_TO_XINPUT[m.group(0)], v) for k, v in profile.items()}


# ============================================================================
# WRITING THE LAUNCH CONFIG
# ============================================================================
def write_input(config_dir, assignments, hardware, profiles):
    pad_ini = os.path.join(config_dir, "GCPadNew.ini")
    dolphin_ini = os.path.join(config_dir, "Dolphin.ini")
    hotkeys_ini = os.path.join(config_dir, "Hotkeys.ini")

    try:
        lines = _read_lines(pad_ini)
    except OSError as e:
        log("EXCEPTION", "GCPadNew.ini read failed, Dolphin will use the old config", e)
        return

    names = device_names(hardware)
    pads = {hw["path"]: hw for hw in hardware}
    assigned = {}          # port index -> device string
    for a in assignments:
        hw = pads.get(a["path"])
        if not hw or len(assigned) >= PORTS:
            continue
        port = len(assigned)
        device = names[hw["path"]]
        profile = profiles.get(a.get("profile_key")) or profiles.get(DEFAULT_PROFILE) or {}
        _replace_section(lines, f"GCPad{port + 1}", {"Device": device, **_for_device(profile, device)})
        assigned[port] = device
        log("INFO", f"Saving -> Port {port + 1} | {hw['name']} | {device} | Profile: {a.get('profile')}")

    try:
        _write_lines(pad_ini, lines)
    except OSError as e:
        log("EXCEPTION", "GCPadNew.ini write failed, Dolphin will use the old config", e)
        return

    _set_si_devices(dolphin_ini, assigned)
    if 0 in assigned:
        _set_fast_forward(hotkeys_ini, assigned[0])


def _set_si_devices(path, assigned):
    try:
        lines = _read_lines(path) if os.path.exists(path) else []
    except OSError as e:
        log("EXCEPTION", "Dolphin.ini read failed, ports left as they are", e)
        return
    core = _items(lines, "Core")
    changed = False
    for port in range(PORTS):
        key = f"SIDevice{port}"
        current = core.get(key, SI_GC_CONTROLLER if port == 0 else SI_NONE)
        if port in assigned and current == SI_NONE:
            new = SI_GC_CONTROLLER
        elif port not in assigned and current == SI_GC_CONTROLLER:
            new = SI_NONE
        else:
            continue
        _set_key(lines, "Core", key, new)
        changed = True
        log("INFO", f"Port {port + 1}", "GameCube controller" if new == SI_GC_CONTROLLER else "empty")
    if changed:
        try:
            _write_lines(path, lines)
        except OSError as e:
            log("EXCEPTION", "Dolphin.ini write failed, ports left as they are", e)


def _set_fast_forward(path, device):
    """OR `<device>:Thumb R` into the held speed-limit hotkey."""
    try:
        lines = _read_lines(path) if os.path.exists(path) else []
    except OSError as e:
        log("EXCEPTION", "Hotkeys.ini read failed, fast-forward not set", e)
        return
    if not _section_bounds(lines, "Hotkeys"):
        # Creating [Hotkeys] with one key would drop Dolphin's default hotkeys
        log("WARNING", "No [Hotkeys] in Hotkeys.ini yet; open Dolphin > Options > Hotkey "
                       "Settings once and close it", "fast-forward not set")
        return
    current = _items(lines, "Hotkeys").get(FAST_FORWARD_KEY, "")
    kept = _FF_TERM_RE.sub("", current).strip().strip("|").strip()
    term = f"`{device}:{FAST_FORWARD_INPUT}`"
    value = f"{kept}|{term}" if kept else term
    _set_key(lines, "Hotkeys", FAST_FORWARD_KEY, value)
    log("INFO", "Speed hotkey (hold)", f"{FAST_FORWARD_KEY} = {value}")
    try:
        _write_lines(path, lines)
    except OSError as e:
        log("EXCEPTION", "Hotkeys.ini write failed, fast-forward not set", e)
