"""
Nextendo/Config.py
Everything that understands Ryujinx-Nextendo's Config.json format.

Three jobs:
    1. load_template()  - reuse the user's own ProController mapping as the
                          default profile, so their button layout survives.
    2. load_profiles()  - discover profiles/controller/*.json.
    3. write_input()    - rewrite Config.json's "input_config" for a launch.

Nextendo has a single input format (SDL3, masked-bus GUID, "name" key, HOME
and Capture buttons), so nothing here branches on version.

Core never looks inside any of this; profile payloads are opaque to it.
"""

import copy
import glob
import json
import os

from Core.Log import log, fatal

BACKEND_STRING = "GamepadSDL3"

# ============================================================================
# DEFAULT CONTROLLER MAPPING TEMPLATE
# ============================================================================
# Fallback template if no existing config found (Nintendo Pro Controller layout)
FALLBACK_TEMPLATE = {
    "version": 1,
    "backend": BACKEND_STRING,
    "id": "",
    "name": "",
    "controller_type": "ProController",
    "player_index": "",
    "deadzone_left": 0.1,
    "deadzone_right": 0.1,
    "range_left": 1,
    "range_right": 1,
    "trigger_threshold": 0.5,
    "left_joycon_stick": {
        "joystick": "Left",
        "invert_stick_x": False,
        "invert_stick_y": False,
        "rotate90_cw": False,
        "stick_button": "LeftStick"
    },
    "right_joycon_stick": {
        "joystick": "Right",
        "invert_stick_x": False,
        "invert_stick_y": False,
        "rotate90_cw": False,
        "stick_button": "RightStick"
    },
    "motion": {
        "motion_backend": "GamepadDriver",
        "sensitivity": 100,
        "gyro_deadzone": 1,
        "enable_motion": True
    },
    "rumble": {
        "strong_rumble": 1,
        "weak_rumble": 1,
        "enable_rumble": True,
        "use_hdrumble": True
    },
    "led": {
        "enable_led": False,
        "turn_off_led": False,
        "use_rainbow": False,
        "led_color": 0
    },
    "left_joycon": {
        "button_minus": "Back",
        "button_capture": "Misc1",
        "button_l": "LeftShoulder",
        "button_zl": "LeftTrigger",
        "button_sl": "SingleLeftTrigger0",
        "button_sr": "SingleRightTrigger0",
        "dpad_up": "DpadUp",
        "dpad_down": "DpadDown",
        "dpad_left": "DpadLeft",
        "dpad_right": "DpadRight"
    },
    "right_joycon": {
        "button_plus": "Start",
        "button_home": "Guide",
        "button_r": "RightShoulder",
        "button_zr": "RightTrigger",
        "button_sl": "SingleLeftTrigger1",
        "button_sr": "SingleRightTrigger1",
        "button_x": "X",
        "button_b": "B",
        "button_y": "Y",
        "button_a": "A"
    }
}

# Nextendo's HOME menu buttons, added to a user mapping that lacks them
HOME_MENU_DEFAULTS = {
    "left_joycon": {"button_capture": "Misc1"},
    "right_joycon": {"button_home": "Guide"},
}

# Fields write_input() injects per launch, stripped from profiles on load
INJECTED_FIELDS = ("backend", "id", "name", "controller_type", "player_index")

PRO_CONTROLLER = "ProController"

# Last "RL Default" taken from a ProController entry, for launches after which
# every player was a Joy-Con
TEMPLATE_CACHE_FILE = "NextendoLauncher-template.json"

# ----------------------------------------------------------------------------
# Single Joy-Con profiles, derived from "RL Default"
#
# A single Joy-Con reaches the game raw (Ryujinx HLE NpadDevices only sets its style,
# nothing is rotated); the game itself turns it sideways. So a pad that plays
# as a sideways Joy-Con must press the Joy-Con's own buttons and feed its stick
# in the Joy-Con's vertical frame:
#
#   sideways     east  south  north  west
#   Joy-Con (L)  Down  Left   Right  Up
#   Joy-Con (R)  X     A      Y      B
#
# Mapping entries are (section, key) <- (template section, template key): the
# Joy-Con input takes the pad button the template binds to the source input.
# The pad's left stick drives the Joy-Con's only stick, a quarter turn rotated.
# ----------------------------------------------------------------------------
_L, _R = "left_joycon", "right_joycon"
JOYCON_PROFILES = {
    "RL Joy-Con (L)": {
        "controller_type": "JoyconLeft",
        "buttons": [
            ((_L, "dpad_down"), (_R, "button_a")),
            ((_L, "dpad_left"), (_R, "button_b")),
            ((_L, "dpad_right"), (_R, "button_x")),
            ((_L, "dpad_up"), (_R, "button_y")),
            ((_L, "button_sl"), (_L, "button_l")),
            ((_L, "button_sr"), (_R, "button_r")),
            ((_L, "button_l"), (_L, "button_zl")),
            ((_L, "button_zl"), (_R, "button_zr")),
            ((_L, "button_minus"), (_R, "button_plus")),
        ],
        "quarter_turns_cw": 1,   # Joy-Con (L) is held rotated counter-clockwise
    },
    "RL Joy-Con (R)": {
        "controller_type": "JoyconRight",
        "buttons": [
            ((_R, "button_x"), (_R, "button_a")),
            ((_R, "button_a"), (_R, "button_b")),
            ((_R, "button_y"), (_R, "button_x")),
            ((_R, "button_b"), (_R, "button_y")),
            ((_R, "button_sl"), (_L, "button_l")),
            ((_R, "button_sr"), (_R, "button_r")),
            ((_R, "button_r"), (_L, "button_zl")),
            ((_R, "button_zr"), (_R, "button_zr")),
        ],
        "quarter_turns_cw": 3,   # Joy-Con (R) is held rotated clockwise
    },
}


# ============================================================================
# TEMPLATE
# ============================================================================
def load_template(config_file):
    """
    Load the default controller mapping from the user's Config.json.

    Reuses the first SDL ProController entry found, so the user's own button
    layout, deadzones and motion settings become the "RL Default" profile.

    Returns:
        dict: The mapping template, or FALLBACK_TEMPLATE if none was found.
    """
    template = copy.deepcopy(FALLBACK_TEMPLATE)

    if not os.path.exists(config_file):
        return template

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        found = False
        if isinstance(data.get("input_config"), list):
            for entry in data["input_config"]:
                if (entry.get("backend") in ("GamepadSDL2", "GamepadSDL3") and
                        entry.get("controller_type") == PRO_CONTROLLER):
                    template = copy.deepcopy(entry)
                    found = True
                    break
        if found:
            _save_template(config_file, template)
        else:
            # Every pad played as a Joy-Con last time: reuse the last Pro mapping
            cached = _cached_template(config_file)
            if cached:
                log("INFO", "Default mapping taken from", TEMPLATE_CACHE_FILE)
                template = cached
    except Exception as e:
        log("ERROR", "Config file corrupted", config_file)
        log("EXCEPTION", "Config read exception", e)
        fatal(
            "Configuration Error",
            "Could not read the Nextendo Config file:\n"
            f"{config_file}\n\n"
            "Open Nextendo manually once to generate valid configuration files.\n"
            "Then try launching this tool again."
        )

    template["backend"] = BACKEND_STRING
    for section, defaults in HOME_MENU_DEFAULTS.items():
        if isinstance(template.get(section), dict):
            for key, value in defaults.items():
                template[section].setdefault(key, value)

    return template


def _template_cache_path(config_file):
    return os.path.join(os.path.dirname(config_file), TEMPLATE_CACHE_FILE)


def _save_template(config_file, template):
    try:
        with open(_template_cache_path(config_file), 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log("WARNING", "Could not save the default mapping", e)


def _cached_template(config_file):
    try:
        with open(_template_cache_path(config_file), 'r', encoding='utf-8') as f:
            template = json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        log("WARNING", "Ignoring unreadable default mapping cache", e)
        return None
    if not isinstance(template, dict) or template.get("controller_type") != PRO_CONTROLLER:
        return None
    return template


# ============================================================================
# PROFILES
# ============================================================================
def load_profiles(config_file, template):
    """
    Load controller profiles from Nextendo's profiles/controller/ directory.

    The first entry is always "RL Default", built from `template`. Remaining
    entries come from *.json files on disk. Fields that write_input() injects
    at launch time are stripped so the correct values are used then. A profile
    file literally named "RL Default.json" overrides the built-in default.

    Returns:
        dict: {"display_name": data_dict, ...}
    """
    profiles = {"RL Default": copy.deepcopy(template)}

    profiles_dir = os.path.join(os.path.dirname(config_file), "profiles", "controller")

    if os.path.isdir(profiles_dir):
        for filepath in sorted(glob.glob(os.path.join(profiles_dir, "*.json"))):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                for key in INJECTED_FIELDS:
                    raw.pop(key, None)
                display_name = os.path.splitext(os.path.basename(filepath))[0]
                profiles[display_name] = raw
            except Exception as e:
                log("WARNING", "Skipping corrupted profile", filepath)
                log("EXCEPTION", "Profile load exception", e)

    # Joy-Con profiles right after "RL Default" (even an on-disk one), built
    # from it, unless a profile on disk already uses that name
    default = profiles.pop("RL Default")
    joycons = {name: _joycon_profile(default, spec)
               for name, spec in JOYCON_PROFILES.items() if name not in profiles}
    profiles = {"RL Default": default, **joycons, **profiles}

    log("INFO", "Profiles loaded", str(len(profiles)))
    return profiles


def _joycon_profile(template, spec):
    """A copy of `template` that plays as a sideways single Joy-Con."""
    profile = copy.deepcopy(template)
    profile["controller_type"] = spec["controller_type"]

    for (section, key), (src_section, src_key) in spec["buttons"]:
        source = template.get(src_section)
        if isinstance(source, dict) and src_key in source:
            profile.setdefault(section, {})[key] = source[src_key]

    left = copy.deepcopy(template.get("left_joycon_stick") or {"joystick": "Left"})
    if spec["controller_type"] == "JoyconRight":
        # the right Joy-Con's stick is driven by the pad's left stick (and its
        # click); the physical right stick moves to the unused left slot
        right = copy.deepcopy(template.get("right_joycon_stick") or {"joystick": "Right"})
        profile["left_joycon_stick"] = right
        profile["right_joycon_stick"] = left
    else:
        profile["left_joycon_stick"] = left
    _turn_stick(left, spec["quarter_turns_cw"])
    return profile


def _turn_stick(stick, quarter_turns_cw):
    """
    Add quarter turns (clockwise) to a stick config. Ryujinx applies
    invert_stick_x/y first, then rotate90_cw as (x, y) -> (y, -x)
    (Ryujinx.Input.SDL3/SDL3Gamepad.cs GetStick). Two turns are both axes
    inverted, which commutes with the rotation.
    """
    turns = (quarter_turns_cw + (1 if stick.get("rotate90_cw") else 0)) % 4
    if turns >= 2:
        stick["invert_stick_x"] = not stick.get("invert_stick_x", False)
        stick["invert_stick_y"] = not stick.get("invert_stick_y", False)
    stick["rotate90_cw"] = bool(turns % 2)


# ============================================================================
# GUID FORMATTING
# ============================================================================
def guid_fix(raw_hex):
    """
    Convert an SDL3 GUID into the format Nextendo expects.

    Layout 000000XX-YYZZ-AABB-CCCC-DDDDDDDDDDDD: bus ID masked into the first
    block, the next two blocks endian-swapped, the rest as-is.
    """
    if len(raw_hex) < 32:
        return raw_hex  # Invalid GUID, return as-is

    part1 = f"000000{raw_hex[:2]}"
    part2 = raw_hex[10:12] + raw_hex[8:10]
    part3 = raw_hex[14:16] + raw_hex[12:14]
    part4_a = raw_hex[16:20]
    part4_b = raw_hex[20:]

    return f"{part1}-{part2}-{part3}-{part4_a}-{part4_b}"


def enable_rumble(entry):
    """Vibration on for every assigned pad; strengths of 0 become full."""
    rumble = entry.get("rumble")
    if not isinstance(rumble, dict):
        rumble = entry["rumble"] = {}
    rumble["enable_rumble"] = True
    for key in ("strong_rumble", "weak_rumble"):
        if not rumble.get(key):
            rumble[key] = 1


# ============================================================================
# WRITING THE LAUNCH CONFIG
# ============================================================================
def write_input(config_file, assignments, hardware, profiles):
    """
    Rewrite the "input_config" section of Config.json for this launch.

    Only that key is replaced - the rest of the user's settings are preserved.

    Args:
        config_file (str):        Path to Config.json
        assignments (list[dict]): Player order: {"path", "name", "profile_key"}
        hardware    (list[dict]): Fresh SDL scan: {"path", "guid", "name"}
        profiles    (dict):       {profile_key: mapping dict}
    """
    if not os.path.exists(config_file):
        return  # No config file to modify

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return  # Corrupted config

    # Duplicate pads are told apart by an index prefix on the GUID, counted in
    # OS enumeration order across every connected pad - not just assigned ones
    enumerated = []
    guid_counters = {}
    for hw in hardware:
        base_guid = guid_fix(hw["guid"])
        idx = guid_counters.get(base_guid, 0)
        guid_counters[base_guid] = idx + 1
        enumerated.append({
            "path": hw["path"],
            "ryu_id": f"{idx}-{base_guid}",
            "name": hw["name"]
        })

    new_input = []

    for i, assignment in enumerate(assignments):
        matched_hw = next(
            (x for x in enumerated if x["path"] == assignment["path"]),
            None
        )
        if not matched_hw:
            continue

        profile_data = profiles[assignment["profile_key"]]
        log("INFO", f"Saving -> Player {i+1} | {matched_hw['name']} | Profile: {assignment['profile_key']}")

        entry = copy.deepcopy(profile_data)
        entry["id"] = matched_hw["ryu_id"]
        enable_rumble(entry)
        entry["name"] = matched_hw["name"]
        entry["player_index"] = f"Player{i+1}"
        entry["backend"] = BACKEND_STRING
        # On-disk profiles lose controller_type on load, so they stay Pro
        entry["controller_type"] = profile_data.get("controller_type") or PRO_CONTROLLER
        new_input.append(entry)

    data["input_config"] = new_input
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log("EXCEPTION", "Config write failed, Nextendo will use the old config", e)
