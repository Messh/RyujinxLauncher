"""
Azahar/Azahar.py
The AzaharPlus implementation of the Core.Emulator contract.

AzaharPlus (https://github.com/AzaharPlus/AzaharPlus) is a fork of the Azahar
3DS emulator. Its binary is azahar.exe. A 3DS has one player, so the launcher
shows a single slot. This package depends on Core only.

Data folder (src/common/file_util.cpp, SetUserPath):
    Azahar uses <exe dir>/user/ when that folder exists, otherwise
    %APPDATA%/AzaharPlus. The launcher never uses %APPDATA%: it creates user/
    when missing, so Azahar itself starts in portable mode too.

    user/config/qt-config.ini   [Controls]: input profiles + active profile
    user/log/                   logs (the launcher writes its own there too)

SDL: Azahar links SDL2, usually statically, so there may be no SDL DLL next
to it. The launcher then looks next to itself, and stops with instructions
if it finds none.
"""

import glob
import os
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

from . import Config

EXE_NAMES = ("azahar.exe", "Azahar.exe") if sys.platform == "win32" else ("azahar", "Azahar")

# Azahar is an SDL2 program, so SDL2 is preferred when both are found
_SDL_PATTERNS = {
    "SDL2": ("SDL2.dll", "libSDL2*.so*", "libSDL2*.dylib"),
    "SDL3": ("SDL3.dll", "libSDL3*.so*", "libSDL3*.dylib"),
}


class Azahar(Emulator):
    """AzaharPlus (Nintendo 3DS emulator, Citra fork)."""

    name = "Azahar"
    max_players = 1

    def __init__(self):
        super().__init__()
        self.backend = "SDL2"
        self.lib_dir = None
        self.user_dir = None
        self.base = None

    # ------------------------------------------------------------------
    # 1. Where everything lives
    # ------------------------------------------------------------------
    def locate(self, base):
        """
        Resolve the Azahar directory, binary and qt-config.ini.

        Directory priority : AzaharPath.config override > launcher directory.
        Data               : <exe dir>/user/, created if missing. Never %APPDATA%.
        """
        self.base = base
        self.dir = read_path_override(base, self.name) or base

        candidates = [os.path.join(self.dir, n) for n in EXE_NAMES]
        self.exe = next((c for c in candidates if os.path.exists(c)), None)
        if not self.exe:
            fatal(
                "Azahar Missing",
                f"Could not find {EXE_NAMES[0]} in:\n{self.dir}\n\n"
                "Place AzaharLauncher next to it, or write its folder "
                "in an AzaharPath.config file.",
                "Azahar binary not found", self.dir
            )

        self.user_dir = os.path.join(self.dir, "user")
        try:
            os.makedirs(self.user_dir, exist_ok=True)
        except OSError as e:
            fatal(
                "Azahar Data Folder",
                f"Could not create the portable folder:\n{self.user_dir}\n\n{e}",
                "Portable folder creation failed", self.user_dir
            )
        self.config_path = os.path.join(self.user_dir, "config", "qt-config.ini")

    def log_dir(self):
        return os.path.join(self.user_dir, "log")

    # ------------------------------------------------------------------
    # 2. Runtime setup - runs before the SDL wrapper is imported
    # ------------------------------------------------------------------
    def prepare(self):
        """Find an SDL library for the launcher, snapshot env."""
        self.backend, self.lib_dir = self._find_sdl()
        if not self.lib_dir:
            fatal(
                "SDL Library Missing",
                "Azahar has SDL built in, so the launcher needs its own copy "
                "to read the controllers.\n\n"
                f"Place SDL2.dll next to azahar.exe:\n{self.dir}\n\n"
                "(SDL2.dll comes in the SDL2-<version>-win32-x64.zip release "
                "at github.com/libsdl-org/SDL/releases.)",
                "No SDL library found", self.dir
            )
        log("INFO", f"{self.backend} library found in", self.lib_dir)

        # Snapshot first: Azahar must start with an untouched environment
        self.env = os.environ.copy()

        # Azahar sets no enumeration hints (input_common/sdl/sdl_impl.cpp), so
        # its SDL2 runs with SDL2's defaults, where RawInput is ON: XInput pads
        # get RawInput GUIDs (driver byte 'r'). SDL3 defaults RawInput to OFF
        # and would report XInput GUIDs ('x', other version and name CRC) that
        # Azahar never matches. Turn it on so the launcher computes the same
        # GUID Azahar does, even for a pad Azahar has never been mapped with.
        os.environ["SDL_JOYSTICK_RAWINPUT"] = "1"
        log("INFO", "SDL hint", "SDL_JOYSTICK_RAWINPUT=1")

    def _find_sdl(self):
        for backend in ("SDL2", "SDL3"):
            for folder in (self.dir, self.base):
                for pattern in _SDL_PATTERNS[backend]:
                    if folder and glob.glob(os.path.join(folder, pattern)):
                        return backend, folder
        return "SDL2", None

    def sdl_backend(self):
        return self.backend

    def sdl_dir(self):
        return self.lib_dir

    # ------------------------------------------------------------------
    # 3. Controller profiles
    # ------------------------------------------------------------------
    def load_profiles(self):
        return Config.load_profiles(self.config_path)

    # ------------------------------------------------------------------
    # 4. Writing the launch configuration
    # ------------------------------------------------------------------
    def write_input_config(self, assignments, hardware):
        Config.write_input(self.config_path, assignments, hardware, self.profiles)
