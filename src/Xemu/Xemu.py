"""
Xemu/Xemu.py
The xemu implementation of the Core.Emulator contract.
Depends on Core only, never on another emulator package.

Data folder (ui/xemu-settings.cc):
    xemu is portable when xemu.toml already exists next to xemu.exe;
    otherwise it uses %APPDATA%\\xemu\\xemu. The launcher never lets that
    happen: it creates an empty xemu.toml when missing (xemu fills in
    defaults on first start).

SDL: xemu links SDL3 statically, so there is no SDL library next to it.
The launcher looks for SDL3.dll (or SDL2.dll) next to xemu.exe, then next to
itself, and stops with instructions if it finds none.
"""

import glob
import os
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

from . import Config

EXE_NAMES = ("xemu.exe",) if sys.platform == "win32" else ("xemu",)
_SDL_PATTERNS = {
    "SDL3": ("SDL3.dll", "libSDL3*.so*", "libSDL3*.dylib"),
    "SDL2": ("SDL2.dll", "libSDL2*.so*", "libSDL2*.dylib"),
}


class Xemu(Emulator):
    """xemu (original Xbox emulator)."""

    name = "Xemu"
    max_players = 4

    def __init__(self):
        super().__init__()
        self.base = None
        self.backend = "SDL3"
        self.lib_dir = None

    def locate(self, base):
        self.base = base
        self.dir = read_path_override(base, self.name) or base

        candidates = [os.path.join(self.dir, n) for n in EXE_NAMES]
        self.exe = next((c for c in candidates if os.path.exists(c)), None)
        if not self.exe:
            fatal(
                "xemu Missing",
                f"Could not find {EXE_NAMES[0]} in:\n{self.dir}\n\n"
                "Place XemuLauncher next to it, or write its folder "
                "in a XemuPath.config file.",
                "xemu binary not found", self.dir
            )

        self.config_path = os.path.join(self.dir, "xemu.toml")
        if not os.path.exists(self.config_path):
            try:
                open(self.config_path, "a").close()
                log("INFO", "Portable mode enabled", self.config_path)
            except OSError as e:
                fatal(
                    "xemu Portable Mode",
                    f"Could not create:\n{self.config_path}\n\n{e}",
                    "Portable config creation failed", self.config_path
                )
        self.cwd = self.dir

    def log_dir(self):
        return self.dir

    def prepare(self):
        self.backend, self.lib_dir = self._find_sdl()
        if not self.lib_dir:
            fatal(
                "SDL Library Missing",
                "xemu has SDL built in, so the launcher needs its own copy "
                "to read the controllers.\n\n"
                f"Place SDL3.dll next to xemu.exe:\n{self.dir}\n\n"
                "(SDL3.dll comes in the SDL3-<version>-win32-x64.zip release "
                "at github.com/libsdl-org/SDL/releases.)",
                "No SDL library found", self.dir
            )
        log("INFO", f"{self.backend} library found in", self.lib_dir)
        # xemu sets no enumeration hints of its own; keep SDL's defaults
        self.env = os.environ.copy()

    def _find_sdl(self):
        for backend in ("SDL3", "SDL2"):
            for folder in (self.dir, self.base):
                for pattern in _SDL_PATTERNS[backend]:
                    if folder and glob.glob(os.path.join(folder, pattern)):
                        return backend, folder
        return "SDL3", None

    def sdl_backend(self):
        return self.backend

    def sdl_dir(self):
        return self.lib_dir

    def load_profiles(self):
        return Config.load_profiles()

    def write_input_config(self, assignments, hardware):
        Config.write_input(self.config_path, assignments, hardware)
