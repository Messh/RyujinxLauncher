"""
Dolphin/Dolphin.py
The Dolphin (Qt) implementation of the Core.Emulator contract, for
GameCube games. Depends on Core only, never on another emulator package.

Data folder (Source/Core/UICommon/UICommon.cpp, SetUserDirectory):
    portable.txt next to Dolphin.exe (its content is ignored) means
    portable mode: everything lives in <exe dir>/User. Otherwise Dolphin
    uses the registry, Documents or %APPDATA%. The launcher never lets that
    happen: it creates portable.txt when missing.

    User/Config/GCPadNew.ini         [GCPad1]..[GCPad4]
    User/Config/Dolphin.ini          [Core] SIDevice0..3, [SDL_Hints]
    User/Config/Hotkeys.ini          [Hotkeys]
    User/Config/Profiles/GCPad/*.ini [Profile] controller profiles

SDL: Dolphin uses SDL3 with its own hints (ControllerInterface/SDL/SDL.cpp)
plus everything in Dolphin.ini [SDL_Hints]. The launcher applies the same
hints, then opens Xbox-style pads through SDL's XInput driver so SDL
reports their XInput slot (Dolphin's own XInput backend numbers them by
that slot). It needs an SDL3.dll next to Dolphin or next to itself.
"""

import glob
import os
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

from . import Config

EXE_NAMES = ("Dolphin.exe",) if sys.platform == "win32" else ("dolphin-emu", "Dolphin")
SDL_PATTERNS = ("SDL3.dll", "libSDL3*.so*", "libSDL3*.dylib")

# ControllerInterface/SDL/SDL.cpp defaults (written to [SDL_Hints] if unset)
DOLPHIN_SDL_HINTS = {
    "SDL_JOYSTICK_ENHANCED_REPORTS": "1",
    "SDL_JOYSTICK_WGI": "0",
    "SDL_JOYSTICK_HIDAPI_PS5_PLAYER_LED": "0",
    "SDL_JOYSTICK_DIRECTINPUT": "1",
    "SDL_JOYSTICK_HIDAPI_COMBINE_JOY_CONS": "1",
    "SDL_JOYSTICK_HIDAPI_VERTICAL_JOY_CONS": "0",
}
# Launcher only: XInput slots are reported for pads SDL opens via XInput
XINPUT_HINTS = {
    "SDL_JOYSTICK_RAWINPUT": "0",
    "SDL_XINPUT_ENABLED": "1",
    "SDL_JOYSTICK_HIDAPI_XBOX": "0",
}


class Dolphin(Emulator):
    """Dolphin (GameCube emulator)."""

    name = "Dolphin"
    max_players = Config.PORTS

    def __init__(self):
        super().__init__()
        self.base = None
        self.lib_dir = None
        self.config_dir = None

    def locate(self, base):
        self.base = base
        self.dir = read_path_override(base, self.name) or base

        candidates = [os.path.join(self.dir, n) for n in EXE_NAMES]
        self.exe = next((c for c in candidates if os.path.exists(c)), None)
        if not self.exe:
            fatal(
                "Dolphin Missing",
                f"Could not find {EXE_NAMES[0]} in:\n{self.dir}\n\n"
                "Place DolphinLauncher next to it, or write its folder "
                "in a DolphinPath.config file.",
                "Dolphin binary not found", self.dir
            )

        marker = os.path.join(self.dir, "portable.txt")
        if not os.path.exists(marker):
            try:
                open(marker, "a").close()
                log("INFO", "Portable mode enabled", marker)
            except OSError as e:
                fatal("Dolphin Portable Mode", f"Could not create:\n{marker}\n\n{e}",
                      "Portable marker creation failed", marker)

        self.config_dir = os.path.join(self.dir, "User", "Config")
        self.config_path = os.path.join(self.config_dir, "GCPadNew.ini")
        self.cwd = self.dir

    def log_dir(self):
        return os.path.join(self.dir, "User", "Logs")

    def prepare(self):
        self.lib_dir = next((d for d in (self.dir, self.base) if d and any(
            glob.glob(os.path.join(d, p)) for p in SDL_PATTERNS)), None)
        if not self.lib_dir:
            fatal(
                "SDL3 Missing",
                "The launcher needs SDL3 to find each controller.\n\n"
                f"Place SDL3.dll next to Dolphin:\n{self.dir}\n\n"
                "(SDL3.dll comes in the SDL3-<version>-win32-x64.zip release "
                "at github.com/libsdl-org/SDL/releases.)",
                "No SDL3 library found", self.dir
            )
        log("INFO", "SDL3 library found in", self.lib_dir)

        self.env = os.environ.copy()
        hints = dict(DOLPHIN_SDL_HINTS)
        hints.update(Config.read_section(os.path.join(self.config_dir, "Dolphin.ini"), "SDL_Hints"))
        hints.update(XINPUT_HINTS)
        for hint, value in hints.items():
            os.environ[hint] = value
            log("INFO", "SDL hint", f"{hint}={value}")

    def sdl_backend(self):
        return "SDL3"

    def sdl_dir(self):
        return self.lib_dir

    def load_profiles(self):
        return Config.load_profiles(self.config_path, os.path.join(self.config_dir, "Profiles", "GCPad"))

    def write_input_config(self, assignments, hardware):
        Config.write_input(self.config_dir, assignments, hardware, self.profiles)
