"""
BizHawk/BizHawk.py
The BizHawk (EmuHawk) implementation of the Core.Emulator contract, used for
Sega Mega Drive / Genesis. Depends on Core only, never on another emulator
package.

Data folder (src/BizHawk.Client.EmuHawk/Program.cs):
    config.ini next to EmuHawk.exe, always (JSON despite the name). BizHawk
    has no non-portable mode, so there is no marker to create.

Input (src/BizHawk.Bizware.Input/SDL2/SDL2Gamepad.cs, Config.cs):
    "AllTrollers": { "GPGX Genesis Controller": { "P1 Up": "Up, X1 DpadUp", ... } }
    A binding is a comma-separated list of alternatives ('+' joins a chord).
    Pad inputs are "<prefix> <button>", prefix = "X<n>" for an SDL game
    controller and "J<n>" for a plain joystick, n = SDL2 device index + 1.
    That is the launcher's "joystick_index" when it enumerates with the same
    SDL2 library and hints.

At launch, for each controller definition below, every assigned player's
"P<n> <button>" binding is rebuilt as: that player's own non-pad
alternatives (keyboard, mouse) + Player 1's pad layout moved to the
assigned pad. Unassigned players lose only the pad alternatives that point
at a pad given to someone else.

Genesis Plus GX defaults to two pads (ControlTypeLeft/Right = Normal), so
two players.

SDL: BizHawk ships SDL2.dll in dll\\ and sets no enumeration hints, only
SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS. The launcher loads that same
SDL2.dll with SDL's defaults.
"""

import json
import os
import re
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

EXE_NAMES = ("EmuHawk.exe",) if sys.platform == "win32" else ("EmuHawkMono.sh",)
DEFAULT_PROFILE = "Default"

# Controller definitions BizHawk uses for Mega Drive games, per core
CONTROLLERS = ("GPGX Genesis Controller", "PicoDrive Genesis Controller")
TEMPLATE_CONTROLLER = CONTROLLERS[0]

_SDL_LIBS = ("SDL2.dll",) if sys.platform == "win32" else ()
# A whole pad alternative: "X1 A", "J2 POV1U", "X1 LeftThumbX Axis"
_PAD_TERM_RE = re.compile(r"^([XJ])(\d+) (.+)$")
_PLAYER_KEY_RE = re.compile(r"^P(\d+) (.+)$")


def _terms(binding):
    return [t.strip() for t in (binding or "").split(",") if t.strip()]


def _pad_numbers(term):
    """1-based pad numbers referenced by an alternative (chords included)."""
    return {int(m.group(2)) for part in term.split("+")
            if (m := _PAD_TERM_RE.match(part.strip()))}


def _template(binds):
    """{button: [pad button names]} from Player 1's game-controller ("X") binds."""
    layout = {}
    for key, value in binds.items():
        m = _PLAYER_KEY_RE.match(key)
        if not m or m.group(1) != "1":
            continue
        buttons = [pm.group(3) for t in _terms(value)
                   if (pm := _PAD_TERM_RE.match(t)) and pm.group(1) == "X"]
        layout[m.group(2)] = list(dict.fromkeys(buttons))
    return layout


class BizHawk(Emulator):
    """BizHawk (EmuHawk), used for Sega Mega Drive / Genesis."""

    name = "BizHawk"
    max_players = 2

    def __init__(self):
        super().__init__()
        self.lib_dir = None

    def locate(self, base):
        self.dir = read_path_override(base, self.name) or base

        candidates = [os.path.join(self.dir, n) for n in EXE_NAMES]
        self.exe = next((c for c in candidates if os.path.exists(c)), None)
        if not self.exe:
            fatal(
                "BizHawk Missing",
                f"Could not find {EXE_NAMES[0]} in:\n{self.dir}\n\n"
                "Place BizHawkLauncher next to it, or write its folder "
                "in a BizHawkPath.config file.",
                "BizHawk binary not found", self.dir
            )
        self.config_path = os.path.join(self.dir, "config.ini")
        self.cwd = self.dir

    def log_dir(self):
        return os.path.join(self.dir, "logs")

    def prepare(self):
        if _SDL_LIBS:
            dll_dir = os.path.join(self.dir, "dll")
            if not any(os.path.exists(os.path.join(dll_dir, n)) for n in _SDL_LIBS):
                fatal(
                    "SDL2 Missing",
                    f"SDL2.dll was not found in BizHawk's dll folder:\n{dll_dir}\n\n"
                    "The launcher needs BizHawk's own SDL2 to number the "
                    "controllers the same way. BizHawk's release includes it.",
                    "SDL2 not found", dll_dir
                )
            self.lib_dir = dll_dir
        log("INFO", "SDL2 library", self.lib_dir or "system")
        # BizHawk sets no enumeration hints; SDL's defaults apply to both
        self.env = os.environ.copy()

    def sdl_backend(self):
        return "SDL2"

    def sdl_dir(self):
        return self.lib_dir

    def _load(self):
        try:
            with open(self.config_path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:
            log("EXCEPTION", "config.ini read failed", e)
            return None

    def load_profiles(self):
        config = self._load() or {}
        binds = (config.get("AllTrollers") or {}).get(TEMPLATE_CONTROLLER) or {}
        if not any(_template(binds).values()):
            fatal(
                "Controller Setup Required",
                "No Mega Drive controller mapping was found in BizHawk.\n\n"
                "Open BizHawk, load a Mega Drive game, go to Config > Controllers "
                "and map Player 1 to a controller (BizHawk maps Xbox-style pads "
                "by default), then close BizHawk.\n"
                "The launcher reuses that layout for every controller you assign.",
                "No GPGX pad mapping found", self.config_path
            )
        return {DEFAULT_PROFILE: None}

    def write_input_config(self, assignments, hardware):
        config = self._load()
        if config is None:
            log("ERROR", "config.ini missing or unreadable, BizHawk will use the old config")
            return
        all_trollers = config.get("AllTrollers")
        if not isinstance(all_trollers, dict):
            return
        layout = _template(all_trollers.get(TEMPLATE_CONTROLLER) or {})

        pads = {h["path"]: h for h in hardware}
        assigned = {}       # player (1-based) -> pad number (1-based)
        for a in assignments:
            hw = pads.get(a["path"])
            if not hw or len(assigned) >= self.max_players:
                continue
            player = len(assigned) + 1
            assigned[player] = hw["joystick_index"] + 1
            log("INFO", f"Saving -> Player {player} | {hw['name']} | X{assigned[player]}")
        taken = set(assigned.values())

        for controller in CONTROLLERS:
            binds = all_trollers.get(controller)
            if not isinstance(binds, dict):
                continue
            for player in range(1, self.max_players + 1):
                pad = assigned.get(player)
                for button, pad_buttons in layout.items():
                    key = f"P{player} {button}"
                    if key not in binds and pad is None:
                        continue
                    old = _terms(binds.get(key))
                    if pad is None:
                        new = [t for t in old if not _pad_numbers(t) & taken]
                    else:
                        new = [t for t in old if not _pad_numbers(t)]
                        new += [f"X{pad} {b}" for b in pad_buttons]
                    binds[key] = ", ".join(new)
            log("INFO", "Bindings written for", controller)

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log("EXCEPTION", "config.ini write failed, BizHawk will use the old config", e)
