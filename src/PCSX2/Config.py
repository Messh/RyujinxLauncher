"""
PCSX2/Config.py
Everything that understands PCSX2's ini input format.

PCSX2 (Qt, SDL3) stores one section per virtual pad, Pad1..Pad8:

    [Pad1]
    Type = DualShock2
    Cross = SDL-0/FaceSouth
    LUp = SDL-0/-LeftY
    L2 = SDL-0/+LeftTrigger
    LargeMotor = SDL-0/LargeMotor
    ...

"SDL-N" names a physical pad by N = the SDL player index the pad had when
PCSX2 opened it, or, when that index is invalid or already taken, the
smallest free number (pcsx2/Input/SDLInputSource.cpp, OpenDevice /
GetFreePlayerId). The launcher computes the same N from its own SDL scan.

A profile is the key/value set of one [PadN] section: the user's own
mapping from the config (RL Default) or from inputprofiles/*.ini. At launch
every "SDL-<anything>/" device prefix in it is replaced with the assigned
pad's SDL-N, so the user's layout, deadzones and rumble keys are kept.

Pads beyond port 2 need the multitap. Pad numbering (both emulators by this
author): Pad1 = port 1A, Pad2 = port 2A, Pad3-5 = 1B-1D, Pad6-8 = 2B-2D.

The file is edited line by line; nothing outside [PadN] and the multitap
keys is touched.
"""

import glob
import os
import re

from Core.Log import log, fatal

EMULATOR = "PCSX2"
TYPE_NONE = "None"
DEFAULT_PROFILE = "RL Default"
PAD_COUNT = 8

# Multitap: (section, key) per port, stored as true/false
MULTITAP_KEYS = (("Pad", "MultitapPort1"), ("Pad", "MultitapPort2"))

# A binding names its device as SDL-<n> or XInput-<slot>, then the input
_DEVICE_RE = re.compile(r"(SDL|XInput)-[^/\s&]+/([^\s&]+)")

# XInput source (XInput-<slot>/A ...): the slot is the pad's XInput user index
# (0-3), which SDL reports as the player index of pads it opens through its
# XInput driver. Mappings made with the XInput source are written back as
# XInput-<slot> for XInput pads; any other pad gets SDL-<n>, with these XInput
# button names translated to SDL's (axes, d-pad, shoulders, motors are equal).
XINPUT_SLOTS = 4
XINPUT_DRIVER = "78"      # SDL GUID byte 14 = 'x'
XINPUT_TO_SDL = {"A": "FaceSouth", "B": "FaceEast", "X": "FaceWest", "Y": "FaceNorth"}
_SECTION_RE = re.compile(r"^\s*\[(.+)\]\s*$")

# Pad types with rumble motors, and the motor bindings / strength keys
MOTOR_TYPES = ("DualShock2",)
MOTORS = ("LargeMotor", "SmallMotor")
MOTOR_SCALES = ("LargeMotorScale", "SmallMotorScale")


# ============================================================================
# INI - minimal line-preserving reader/writer ("Key = Value")
# ============================================================================
def _read_lines(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
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


def _section_items(lines, section):
    bounds = _section_bounds(lines, section)
    if not bounds:
        return {}
    items = {}
    for line in lines[bounds[0]:bounds[1]]:
        if "=" in line and not line.lstrip().startswith((";", "#")):
            key, value = line.split("=", 1)
            items[key.strip()] = value.strip()
    return items


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
        if "=" in lines[i] and not lines[i].lstrip().startswith((";", "#")):
            index[lines[i].split("=", 1)[0].strip()] = i

    pending = []
    for key, value in updates.items():
        line = f"{key} = {value}"
        if key in index:
            lines[index[key]] = line
        else:
            pending.append(line)

    insert_at = end
    while insert_at > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines[insert_at:insert_at] = pending


def read_section(config_file, section):
    """{key: value} of one section, or {} if the file is missing/unreadable."""
    try:
        return _section_items(_read_lines(config_file), section)
    except Exception:
        return {}


# ============================================================================
# TEMPLATE + PROFILES
# ============================================================================
def _is_sdl_pad(items):
    """A pad bound to a controller through the SDL or XInput source."""
    return (items.get("Type", TYPE_NONE) != TYPE_NONE and
            any(_DEVICE_RE.search(v) for v in items.values()))


def _source(items):
    """"XInput" when the mapping was made with the XInput source, else "SDL"."""
    for value in items.values():
        match = _DEVICE_RE.search(value)
        if match:
            return match.group(1)
    return "SDL"


def template_source(config_file):
    """Source of the user's default mapping, read before SDL is loaded."""
    try:
        _, items = _first_sdl_pad(_read_lines(config_file))
    except Exception:
        return "SDL"
    return _source(items)


def is_xinput(hw):
    pid = hw.get("player_index", -1)
    return hw["guid"].lower()[28:30] == XINPUT_DRIVER and 0 <= pid < XINPUT_SLOTS


def _retarget(value, device):
    """
    Point every controller binding in `value` at `device`. XInput button
    names are translated when an XInput binding moves to an SDL device.
    """
    to_sdl = device.startswith("SDL-")

    def repl(match):
        name = match.group(2)
        if to_sdl and match.group(1) == "XInput":
            sign = name[0] if name[:1] in "+-" else ""
            name = sign + XINPUT_TO_SDL.get(name[len(sign):], name[len(sign):])
        return f"{device}/{name}"
    return _DEVICE_RE.sub(repl, value)


def _first_sdl_pad(lines):
    for n in range(1, PAD_COUNT + 1):
        items = _section_items(lines, f"Pad{n}")
        if _is_sdl_pad(items):
            return n, items
    return None, {}


def load_profiles(config_file, profiles_dir):
    """
    {"display name": {key: value}}, insertion-ordered.

    "RL Default" is the first pad in the config bound to an SDL controller,
    then every inputprofiles/*.ini that has one.
    """
    profiles = {}

    if os.path.exists(config_file):
        try:
            n, items = _first_sdl_pad(_read_lines(config_file))
        except Exception as e:
            log("EXCEPTION", "Config read exception", e)
            fatal(
                "Configuration Error",
                f"Could not read the {EMULATOR} config file:\n{config_file}\n\n"
                f"Open {EMULATOR} manually once to generate valid configuration "
                "files, then try again."
            )
        if items:
            log("INFO", "Default mapping taken from", f"Pad{n}")
            profiles[DEFAULT_PROFILE] = items

    for filepath in sorted(glob.glob(os.path.join(profiles_dir, "*.ini"))):
        name = os.path.splitext(os.path.basename(filepath))[0]
        try:
            n, items = _first_sdl_pad(_read_lines(filepath))
        except Exception as e:
            log("WARNING", "Skipping unreadable profile", filepath)
            log("EXCEPTION", "Profile load exception", e)
            continue
        if not items:
            log("INFO", "Skipping non-gamepad profile", name)
            continue
        profiles[name] = items

    if DEFAULT_PROFILE in profiles and next(iter(profiles)) != DEFAULT_PROFILE:
        profiles = {DEFAULT_PROFILE: profiles.pop(DEFAULT_PROFILE), **profiles}

    if not profiles:
        fatal(
            "Controller Setup Required",
            f"No gamepad mapping was found in {EMULATOR}.\n\n"
            f"Open {EMULATOR}, go to Settings > Controllers, map a controller "
            "to Controller Port 1 (SDL or XInput source, Automatic "
            "Mapping works) and close it.\n"
            "The launcher reuses that mapping for every controller.",
            "No SDL mapping found", config_file
        )

    log("INFO", "Profiles loaded", str(len(profiles)))
    return profiles


# ============================================================================
# MULTITAP + PAD ORDER
# ============================================================================
def _multitap(lines):
    def on(section, key):
        return _section_items(lines, section).get(key, "false").strip().lower() == "true"
    return [on(*MULTITAP_KEYS[0]), on(*MULTITAP_KEYS[1])]


def _player_pads(tap1, tap2):
    """[PadN, ...] in player order for the given multitap state."""
    port1 = [1, 3, 4, 5] if tap1 else [1]
    port2 = [2, 6, 7, 8] if tap2 else [2]
    return port1 + port2


def _ensure_multitap(lines, players):
    """Enable the fewest multitaps that fit `players`; never disables one."""
    tap1, tap2 = _multitap(lines)
    while len(_player_pads(tap1, tap2)) < players:
        if not tap1:
            tap1 = True
        elif not tap2:
            tap2 = True
        else:
            break
        log("INFO", "Enabling multitap for players", str(players))
    for (section, key), state in zip(MULTITAP_KEYS, (tap1, tap2)):
        if state:
            _apply(lines, section, {key: "true"})
    return _player_pads(tap1, tap2)


# ============================================================================
# SDL PLAYER IDS
# ============================================================================
def sdl_player_ids(hardware):
    """
    {hid path: N} - the N in "SDL-N" the emulator will give each pad.

    Same rule as SDLInputSource::OpenDevice: SDL's player index when valid
    and unused, otherwise the smallest free number, in open order.
    """
    used = set()
    ids = {}
    for hw in hardware:
        pid = hw.get("player_index", -1)
        if pid is None or pid < 0 or pid in used:
            pid = 0
            while pid in used:
                pid += 1
        used.add(pid)
        ids[hw["path"]] = pid
    return ids


# ============================================================================
# SPEED HOTKEYS (R3 on player 1's pad)
# ============================================================================
HOTKEYS_SECTION = "Hotkeys"
FAST_FORWARD_HOTKEY = "HoldTurbo"     # R3, fast-forward while held
# Not auto-configured: PCSX2 has no rewind and its slow motion is a toggle.
# Only the bindings older launcher versions wrote for it are removed.
SLOW_HOTKEY = "ToggleSlowMotion"

# A binding this launcher wrote before, on any device: a stick click, a
# shoulder + stick click chord, or
# the Select + trigger chord older versions used
_CHORD_RE = re.compile(r"^(SDL|XInput)-[^/\s&]+/(LeftStick|RightStick)$"
                       r"|^(SDL|XInput)-[^/\s&]+/Back\s*&\s*(SDL|XInput)-[^/\s&]+/\+(Right|Left)Trigger$"
                       r"|^(SDL|XInput)-[^/\s&]+/(Left|Right)Shoulder\s*&\s*(SDL|XInput)-[^/\s&]+/(Left|Right)Stick$")

# Save / load the selected state slot, once per press:
#   L1 + L3 -> save      R1 + R3 -> load
# Press the shoulder first: the stick click alone is a speed hotkey.
STATE_HOTKEYS = (
    ("SaveStateToSlot", "LeftShoulder", "LeftStick"),
    ("LoadStateFromSlot", "RightShoulder", "RightStick"),
)


def _set_hotkey(lines, hotkey, chord):
    """
    Bind `hotkey` to `chord` in [Hotkeys] (None only removes the launcher's).

    The emulator reads every "<hotkey> = ..." line of [Hotkeys] as one more
    binding, so the user's own bindings (e.g. Keyboard/Tab) are kept; only a
    binding this launcher wrote for another pad is replaced.
    """
    bounds = _section_bounds(lines, HOTKEYS_SECTION)
    if not bounds:
        if chord is None:
            return
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{HOTKEYS_SECTION}]", f"{hotkey} = {chord}"]
        return

    start, end = bounds
    for i in range(end - 1, start - 1, -1):
        if "=" in lines[i]:
            key, value = (p.strip() for p in lines[i].split("=", 1))
            if key == hotkey and _CHORD_RE.match(value):
                del lines[i]
                end -= 1
    if chord is None:
        return
    insert_at = end
    while insert_at > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, f"{hotkey} = {chord}")


def _set_speed_hotkeys(lines, device):
    binding = f"{device}/RightStick"
    _set_hotkey(lines, FAST_FORWARD_HOTKEY, binding)
    log("INFO", "Speed hotkey", f"{FAST_FORWARD_HOTKEY} = {binding}")
    _set_hotkey(lines, SLOW_HOTKEY, None)


def _set_state_hotkeys(lines, device):
    for hotkey, shoulder, stick in STATE_HOTKEYS:
        chord = f"{device}/{shoulder} & {device}/{stick}"
        _set_hotkey(lines, hotkey, chord)
        log("INFO", "State hotkey", f"{hotkey} = {chord}")


# ============================================================================
# VIBRATION
# ============================================================================
def _enable_rumble(updates, current, device):
    """
    Bind both motors of a pad type that has them to the assigned pad, so it
    vibrates even when the mapping was made without them. Scales of 0
    (vibration turned down to nothing) go back to full.
    """
    pad_type = updates.get("Type", current.get("Type", TYPE_NONE))
    if pad_type not in MOTOR_TYPES:
        return
    for motor in MOTORS:
        if not updates.get(motor, current.get(motor, "")).strip():
            updates[motor] = f"{device}/{motor}"
    for scale in MOTOR_SCALES:
        value = updates.get(scale, current.get(scale))
        if value is None:
            continue
        try:
            off = float(value) <= 0
        except ValueError:
            off = True
        if off:
            updates[scale] = "1"
    log("INFO", "Vibration enabled", device)


# ============================================================================
# WRITING THE LAUNCH CONFIG
# ============================================================================
def write_input(config_file, assignments, hardware, profiles):
    """Rewrite the [PadN] sections for this launch."""
    if not os.path.exists(config_file):
        log("WARNING", "Config not found, nothing written", config_file)
        return

    try:
        lines = _read_lines(config_file)
    except Exception as e:
        log("EXCEPTION", f"Config read failed, {EMULATOR} will use the old config", e)
        return

    ids = sdl_player_ids(hardware)
    names = {hw["path"]: hw["name"] for hw in hardware}
    matched = [a for a in assignments if a["path"] in ids]

    pads = _ensure_multitap(lines, len(matched))
    used = set()
    pads_by_path = {hw["path"]: hw for hw in hardware}
    for assignment, pad in zip(matched, pads):
        hw = pads_by_path[assignment["path"]]
        profile = profiles[assignment["profile_key"]]
        if _source(profile) == "XInput" and is_xinput(hw):
            device = f"XInput-{hw['player_index']}"
        else:
            device = f"SDL-{ids[assignment['path']]}"
        section = f"Pad{pad}"
        log("INFO", f"Saving -> Player {len(used)+1} | {names[assignment['path']]} | "
                    f"Profile: {assignment['profile_key']} | {section} | {device}")

        updates = {}
        # Bindings the profile does not define must not keep pointing at
        # whichever pad this section had last time
        for key, value in _section_items(lines, section).items():
            if _DEVICE_RE.search(value):
                updates[key] = _retarget(value, device)
        for key, value in profile.items():
            updates[key] = _retarget(value, device)
        _enable_rumble(updates, _section_items(lines, section), device)
        _apply(lines, section, updates)
        if not used:
            _set_speed_hotkeys(lines, device)
            _set_state_hotkeys(lines, device)
        used.add(pad)

    # Every other pad is unplugged, so no stale binding drives a second player
    for n in range(1, PAD_COUNT + 1):
        if n not in used and _section_bounds(lines, f"Pad{n}"):
            _apply(lines, f"Pad{n}", {"Type": TYPE_NONE})

    try:
        _write_lines(config_file, lines)
    except Exception as e:
        log("EXCEPTION", f"Config write failed, {EMULATOR} will use the old config", e)
