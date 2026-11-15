"""
MelonDS/Config.py
Everything that understands melonDS's melonDS.toml joystick settings.

melonDS 1.x (src/frontend/qt_sdl/EmuInstanceInput.cpp) has one player per
emulator instance and picks its pad by SDL2 device index:

    [Instance0]
    JoystickID = 0            # SDL_JoystickOpen(JoystickID), all joysticks

    [Instance0.Joystick]
    A = 1                     # button index / hat 0x1xx / axis 0x1xxxx, -1 = unbound
    ...

The button mapping lives in [Instance0.Joystick] and does not name a pad, so
it is the single "Default" profile; the launcher only sets JoystickID to the
assigned pad's index among ALL joysticks (Core's "joystick_index").

Speed hotkeys (EmuInstanceInput.cpp hotkeyNames) take one input, not a combo:
    HK_FastForward = R2      fast-forward while held
    HK_SlowMo      = L2      slow motion while held (melonDS has no rewind)
They are written in melonDS's joystick encoding, using the joystick-level
button/axis SDL reports behind each trigger:
    button n                -> n
    hat n, direction mask   -> 0x100 | n << 4 | mask
    axis n as a trigger     -> 0xFFFF | 0x10000 | 2 << 20 | n << 24
A trigger already used by a DS button is left alone.

melonDS saves its config on exit, so the value written here is what it reads
on start.
"""

import os

from Core.Log import log, fatal

from . import Toml

INSTANCE = "Instance0"
DEFAULT_PROFILE = "Default"
SPEED_HOTKEYS = (("HK_FastForward", "righttrigger", "R2"), ("HK_SlowMo", "lefttrigger", "L2"))


def _joy_value(bind):
    """melonDS's joystick mapping int for a raw SDL binding, or None."""
    if not bind:
        return None
    if bind[0] == "button":
        return bind[1]
    if bind[0] == "hat":
        return 0x100 | (bind[1] << 4) | bind[2]
    if bind[0] == "axis":
        return 0xFFFF | 0x10000 | (2 << 20) | (bind[1] << 24)
    return None


def _set_speed_hotkeys(lines, hw):
    prefix = f"{INSTANCE}.Joystick."
    used = {Toml.get(lines, k): k for k in Toml.all_values(lines)
            if k.startswith(prefix) and not k[len(prefix):].startswith("HK_")}
    bindings = hw.get("raw_bindings") or {}
    for hotkey, trigger, label in SPEED_HOTKEYS:
        value = _joy_value(bindings.get(trigger))
        if value is None:
            log("WARNING", f"{label} not found on this pad, {hotkey} left unchanged", hw["name"])
        elif value in used:
            log("WARNING", f"{label} is already mapped to {used[value]}, {hotkey} left unchanged")
        else:
            Toml.set(lines, prefix + hotkey, value)
            log("INFO", f"Speed hotkey (hold): {hotkey} = {label}", hex(value))


def _read_lines(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        return f.read().splitlines()


def _write_lines(path, lines):
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def load_profiles(config_file):
    """Require a joystick mapping: melonDS's defaults leave every button unbound."""
    try:
        values = Toml.all_values(_read_lines(config_file)) if os.path.exists(config_file) else {}
    except Exception as e:
        log("EXCEPTION", "Config read exception", e)
        values = {}

    prefix = f"{INSTANCE}.Joystick."
    mapped = [k for k, v in values.items()
              if k.startswith(prefix) and v.split("#", 1)[0].strip() not in ("", "-1")]
    if not mapped:
        fatal(
            "Controller Setup Required",
            "No joystick mapping was found in melonDS.\n\n"
            "Open melonDS, go to Config > Input and hotkeys, map the buttons "
            "of any controller on the Joystick side and press OK.\n"
            "The launcher reuses that mapping for the controller you assign.",
            "No joystick mapping found", config_file
        )
    log("INFO", "Joystick bindings found", str(len(mapped)))
    return {DEFAULT_PROFILE: None}


def write_input(config_file, assignments, hardware):
    """Point instance 0 at the first assigned pad."""
    if not assignments:
        return
    pads = {hw["path"]: hw for hw in hardware}
    hw = pads.get(assignments[0]["path"])
    if not hw:
        return

    try:
        lines = _read_lines(config_file)
    except Exception as e:
        log("EXCEPTION", "Config read failed, melonDS will use the old config", e)
        return

    index = hw["joystick_index"]
    log("INFO", f"Saving -> Player 1 | {hw['name']} | {INSTANCE}.JoystickID = {index}")
    Toml.set(lines, f"{INSTANCE}.JoystickID", index)
    _set_speed_hotkeys(lines, hw)

    try:
        _write_lines(config_file, lines)
    except Exception as e:
        log("EXCEPTION", "Config write failed, melonDS will use the old config", e)
