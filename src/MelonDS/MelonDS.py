"""
MelonDS/MelonDS.py
The melonDS implementation of the Core.Emulator contract.
Depends on Core only, never on another emulator package.

Data folder (src/frontend/qt_sdl/main.cpp, pathInit):
    1. a "portable" folder next to melonDS.exe, when it exists
    2. the exe folder itself (Windows builds with WIN32_PORTABLE, the default)
    3. otherwise the per-user Qt config folder
The launcher never lets 3 happen: it uses portable/ when present, the exe
folder when melonDS.toml is already there, and otherwise creates portable/.

SDL: melonDS uses SDL2. The launcher loads the SDL2.dll next to melonDS.exe
(or next to itself) so joystick indexes match.
"""

import glob
import os
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

from . import Config

EXE_NAMES = ("melonDS.exe",) if sys.platform == "win32" else ("melonDS",)
SDL_PATTERNS = ("SDL2.dll", "libSDL2*.so*", "libSDL2*.dylib")


class MelonDS(Emulator):
    """melonDS (Nintendo DS emulator)."""

    name = "MelonDS"
    max_players = 1

    def __init__(self):
        super().__init__()
        self.base = None
        self.data_dir = None
        self.lib_dir = None

    def locate(self, base):
        self.base = base
        self.dir = read_path_override(base, self.name) or base

        candidates = [os.path.join(self.dir, n) for n in EXE_NAMES]
        self.exe = next((c for c in candidates if os.path.exists(c)), None)
        if not self.exe:
            fatal(
                "melonDS Missing",
                f"Could not find {EXE_NAMES[0]} in:\n{self.dir}\n\n"
                "Place MelonDSLauncher next to it, or write its folder "
                "in a MelonDSPath.config file.",
                "melonDS binary not found", self.dir
            )

        portable = os.path.join(self.dir, "portable")
        if os.path.isdir(portable):
            self.data_dir = portable
        elif os.path.exists(os.path.join(self.dir, "melonDS.toml")):
            self.data_dir = self.dir
        else:
            try:
                os.makedirs(portable, exist_ok=True)
                log("INFO", "Portable mode enabled", portable)
            except OSError as e:
                fatal(
                    "melonDS Portable Mode",
                    f"Could not create:\n{portable}\n\n{e}",
                    "Portable folder creation failed", portable
                )
            self.data_dir = portable

        self.config_path = os.path.join(self.data_dir, "melonDS.toml")
        self.cwd = self.dir

    def log_dir(self):
        return self.data_dir

    def prepare(self):
        self.lib_dir = next((d for d in (self.dir, self.base) if d and any(
            glob.glob(os.path.join(d, p)) for p in SDL_PATTERNS)), None)
        if not self.lib_dir:
            fatal(
                "SDL2 Missing",
                f"SDL2.dll was not found next to melonDS:\n{self.dir}\n\n"
                "The launcher needs SDL2 to number the controllers the same "
                "way melonDS does. Place SDL2.dll (SDL2-<version>-win32-x64.zip "
                "at github.com/libsdl-org/SDL/releases) next to melonDS.exe.",
                "SDL2 not found", self.dir
            )
        log("INFO", "SDL2 library found in", self.lib_dir)
        # melonDS sets no enumeration hints; keep SDL's defaults
        self.env = os.environ.copy()

    def sdl_backend(self):
        return "SDL2"

    def sdl_dir(self):
        return self.lib_dir

    def load_profiles(self):
        return Config.load_profiles(self.config_path)

    def write_input_config(self, assignments, hardware):
        Config.write_input(self.config_path, assignments, hardware)
