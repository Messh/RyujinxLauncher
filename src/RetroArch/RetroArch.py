"""
RetroArch/RetroArch.py
The RetroArch (Windows) implementation of the Core.Emulator contract,
aimed at the FinalBurn Neo core. Depends on Core only, never on another
emulator package.

Config file (frontend/drivers/platform_win32.c, retroarch.c config lookup):
    Windows RetroArch first loads retroarch.cfg from the exe folder and only
    falls back to %APPDATA%\\RetroArch when there is none. The launcher never
    lets that happen: it creates an empty retroarch.cfg next to the exe when
    missing (RetroArch fills in its defaults and saves them there).

Input (input/drivers_joypad/sdl_joypad.c, configuration.c):
    input_joypad_driver = "sdl2"
    input_player1_joypad_index = "0"     SDL2 device index (all joysticks, in
                                         SDL enumeration order) = Core's
                                         "joystick_index"
    input_player1_a_btn = "1"            SDL_GameController button number
    input_player1_r2_axis = "+5"         SDL_GameController axis (+/-)
    The binds name no pad, so player 1's joypad binds (*_btn / *_axis and
    analog_dpad_mode) are the profile: at launch every assigned player gets
    them plus its pad's joypad index. Keyboard binds are left alone.

    Players that are not assigned are moved to a joypad index nobody has, so
    a pad never drives two players.

Hotkeys come from player 1's pad and are left untouched: with
input_enable_hotkey set (e.g. Select) RetroArch gates every hotkey behind
it, so a single-button R3/L3 hotkey cannot be added without unlocking all
the others (menu, exit, save state...).

Menu: input_menu_toggle_gamepad_combo is set to L3 + R3 (input_defines.h,
enum input_combo_type: INPUT_COMBO_L3_R3 = 2). The combo is a fixed list,
so no four-button combo is possible; arcade games rarely use stick clicks.

SDL: RetroArch ships SDL2.dll next to retroarch.exe and sets no
enumeration hints. The launcher loads that same SDL2.dll with SDL's
defaults so device indexes match.

retroarch.cfg is rewritten by RetroArch on exit (config_save_on_exit);
the values written here are the ones it reads on start.
"""

import glob
import os
import re
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

EXE_NAMES = ("retroarch.exe",) if sys.platform == "win32" else ("retroarch",)
CONFIG_NAME = "retroarch.cfg"
DEFAULT_PROFILE = "Default"
SDL_PATTERNS = ("SDL2.dll", "libSDL2*.so*", "libSDL2*.dylib")
MAX_PLAYERS = 8                 # launcher UI limit (RetroArch has 16)
MENU_COMBO_L3_R3 = 2            # INPUT_COMBO_L3_R3

_LINE_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*"?(.*?)"?\s*$')
# player 1 joypad binds: input_player1_<name>_btn / _axis
_P1_JOY_RE = re.compile(r"^input_player1_(.+_(?:btn|axis))$")
_P1_EXTRA = ("analog_dpad_mode",)


# ============================================================================
# CFG - line preserving ("key = "value"")
# ============================================================================
def _read_lines(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        return f.read().splitlines()


def _write_lines(path, lines):
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))


def _values(lines):
    out = {}
    for line in lines:
        m = _LINE_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _set(lines, updates):
    """Replace keys in place; append the missing ones at the end."""
    index = {}
    for i, line in enumerate(lines):
        m = _LINE_RE.match(line)
        if m:
            index[m.group(1)] = i
    for key, value in updates.items():
        line = f'{key} = "{value}"'
        if key in index:
            lines[index[key]] = line
        else:
            lines.append(line)


class RetroArch(Emulator):
    """RetroArch with the FinalBurn Neo core (arcade)."""

    name = "RetroArch"
    max_players = 4

    def __init__(self):
        super().__init__()
        self.base = None
        self.lib_dir = None

    def locate(self, base):
        self.base = base
        self.dir = read_path_override(base, self.name) or base

        candidates = [os.path.join(self.dir, n) for n in EXE_NAMES]
        self.exe = next((c for c in candidates if os.path.exists(c)), None)
        if not self.exe:
            fatal(
                "RetroArch Missing",
                f"Could not find {EXE_NAMES[0]} in:\n{self.dir}\n\n"
                "Place RetroArchLauncher next to it, or write its folder "
                "in a RetroArchPath.config file.",
                "RetroArch binary not found", self.dir
            )

        self.config_path = os.path.join(self.dir, CONFIG_NAME)
        if not os.path.exists(self.config_path):
            try:
                open(self.config_path, "a").close()
                log("INFO", "Portable config created", self.config_path)
            except OSError as e:
                fatal("RetroArch Portable Mode", f"Could not create:\n{self.config_path}\n\n{e}",
                      "Portable config creation failed", self.config_path)
        self.cwd = self.dir

        try:
            users = int(_values(_read_lines(self.config_path)).get("input_max_users", "4"))
        except (OSError, ValueError):
            users = 4
        self.max_players = max(1, min(users, MAX_PLAYERS))

    def log_dir(self):
        return os.path.join(self.dir, "logs")

    def prepare(self):
        self.lib_dir = next((d for d in (self.dir, self.base) if d and any(
            glob.glob(os.path.join(d, p)) for p in SDL_PATTERNS)), None)
        if not self.lib_dir:
            fatal(
                "SDL2 Missing",
                f"SDL2.dll was not found next to RetroArch:\n{self.dir}\n\n"
                "The launcher needs SDL2 to number the controllers the same "
                "way RetroArch's sdl2 joypad driver does. Place SDL2.dll "
                "(SDL2-<version>-win32-x64.zip at github.com/libsdl-org/SDL/releases) "
                "next to retroarch.exe.",
                "SDL2 not found", self.dir
            )
        log("INFO", "SDL2 library found in", self.lib_dir)

        driver = _values(_read_lines(self.config_path)).get("input_joypad_driver", "")
        if driver and driver != "sdl2":
            fatal(
                "RetroArch Joypad Driver",
                f"RetroArch uses the \"{driver}\" joypad driver.\n\n"
                "The launcher can only pin controllers with the sdl2 driver. "
                "In RetroArch go to Settings > Drivers > Controller, choose "
                "sdl2, then restart RetroArch so it saves the change.",
                "Unsupported joypad driver", driver
            )
        # RetroArch sets no enumeration hints; keep SDL's defaults
        self.env = os.environ.copy()

    def sdl_backend(self):
        return "SDL2"

    def sdl_dir(self):
        return self.lib_dir

    def load_profiles(self):
        """Player 1's joypad binds are the single profile."""
        try:
            values = _values(_read_lines(self.config_path))
        except OSError as e:
            log("EXCEPTION", "retroarch.cfg read failed", e)
            values = {}
        binds = {}
        for key, value in values.items():
            m = _P1_JOY_RE.match(key)
            if m:
                binds[m.group(1)] = value
        for extra in _P1_EXTRA:
            if f"input_player1_{extra}" in values:
                binds[extra] = values[f"input_player1_{extra}"]
        mapped = [k for k, v in binds.items() if k.endswith(("_btn", "_axis")) and v not in ("", "nul")]
        log("INFO", "Player 1 joypad binds found", str(len(mapped)))
        if not mapped:
            log("WARNING", "Player 1 has no joypad binds; only joypad indexes will be set "
                           "(RetroArch's autoconfig decides the buttons)")
            binds = {}
        return {DEFAULT_PROFILE: binds}

    def write_input_config(self, assignments, hardware):
        try:
            lines = _read_lines(self.config_path)
        except OSError as e:
            log("EXCEPTION", "retroarch.cfg read failed, RetroArch will use the old config", e)
            return
        pads = {h["path"]: h for h in hardware}

        updates = {}
        used = set()
        player = 0
        for a in assignments:
            hw = pads.get(a["path"])
            if not hw:
                log("WARNING", "Assigned pad not found in the final scan", a.get("name", a["path"]))
                continue
            if player >= self.max_players:
                continue
            n = player + 1
            index = hw["joystick_index"]
            used.add(index)
            updates[f"input_player{n}_joypad_index"] = index
            if n > 1:
                for key, value in (self.profiles.get(a.get("profile_key")) or
                                   self.profiles.get(DEFAULT_PROFILE) or {}).items():
                    updates[f"input_player{n}_{key}"] = value
            log("INFO", f"Saving -> Player {n} | {hw['name']} | joypad index {index}")
            player += 1

        # Unassigned players: point them at an index no pad has
        first_free = max([h["joystick_index"] for h in hardware] + [-1]) + 1
        spare = iter(range(first_free, first_free + 64))
        for n in range(player + 1, self.max_players + 1):
            index = next(spare)
            updates[f"input_player{n}_joypad_index"] = index
            log("INFO", f"Player {n} unassigned -> joypad index {index} (no pad)")

        updates["input_menu_toggle_gamepad_combo"] = MENU_COMBO_L3_R3
        log("INFO", "Menu toggle combo", "L3 + R3")

        _set(lines, updates)
        try:
            _write_lines(self.config_path, lines)
        except OSError as e:
            log("EXCEPTION", "retroarch.cfg write failed, RetroArch will use the old config", e)
