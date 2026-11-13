"""
Eden/Eden.py
The Eden implementation of the Core.Emulator contract.

Eden is a yuzu fork. Compared to Ryujinx it needs no version detection: the
input format has been stable since yuzu. Eden builds against SDL3; SDL2 is
only used if an older build ships an SDL2 library instead.

Data directory layout (src/common/fs/path_util.cpp, Eden master):

    Windows        portable  <exe dir>/user/          config/qt-config.ini, log/
                   default   %APPDATA%/eden/          config/qt-config.ini, log/
    Linux / macOS  portable  <current dir>/user/      config/qt-config.ini, log/
                   default   $XDG_CONFIG_HOME/eden/   qt-config.ini
                             $XDG_DATA_HOME/eden/     log/

macOS uses the XDG paths too, and Eden chdirs to the folder holding eden.app,
so "portable" there means a user/ folder next to the bundle.

Input profiles live in <dir of qt-config.ini>/input/*.ini.
"""

import glob
import os
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import find_appimage, read_path_override
from Core.Process import mount_appimage, unmount_appimage

from . import Config

# Shared-library patterns per SDL major version, searched in sdl_dir()
_SDL_PATTERNS = {
    "SDL3": ("SDL3.dll", "libSDL3*.so*", "libSDL3*.dylib"),
    "SDL2": ("SDL2.dll", "libSDL2*.so*", "libSDL2*.dylib"),
}


def _xdg(var, fallback):
    return os.environ.get(var) or os.path.expanduser(fallback)


def _first_existing(paths):
    return next((p for p in paths if os.path.exists(p)), None)


class Eden(Emulator):
    """Eden (Nintendo Switch emulator, yuzu fork)."""

    name = "Eden"

    def __init__(self):
        super().__init__()
        self.backend = "SDL2"
        self.lib_dir = None
        self.user_dir = None      # holds log/ (and config/ on Windows/portable)
        self.appimage_path = None

    # ------------------------------------------------------------------
    # 1. Where everything lives
    # ------------------------------------------------------------------
    def locate(self, base):
        """
        Resolve the Eden directory, binary and qt-config.ini.

        Directory priority: EdenPath.config override > launcher directory.
        A "user" folder means portable mode, which wins over the per-user
        directories - same rule Eden itself applies.
        """
        self.dir = read_path_override(base, self.name) or base
        install_dir = self.dir

        if sys.platform == "win32":
            self.exe = _first_existing(
                [os.path.join(self.dir, n) for n in ("eden.exe", "Eden.exe")]
            ) or os.path.join(self.dir, "eden.exe")

        elif sys.platform == "darwin":
            self.exe = _first_existing([
                os.path.join(self.dir, b, "Contents", "MacOS", "eden")
                for b in ("eden.app", "Eden.app")
            ] + [os.path.join(self.dir, "eden")]   # launcher placed inside MacOS/
            ) or os.path.join(self.dir, "eden.app", "Contents", "MacOS", "eden")
            self.dir = os.path.dirname(self.exe)

        else:  # Linux
            self.appimage_path = find_appimage(self.dir, "eden")
            self.is_appimage = self.appimage_path is not None
            if self.is_appimage:
                mount_point = mount_appimage(self.appimage_path)
                self.dir = os.path.join(mount_point, "usr", "bin")
            self.exe = _first_existing(
                [os.path.join(self.dir, n) for n in ("eden", "Eden")]
            ) or os.path.join(self.dir, "eden")

        if not os.path.exists(self.exe):
            fatal(
                "Eden Missing",
                f"Could not find {self.exe} in:\n{self.dir}",
                "Eden binary not found", self.exe
            )

        self._locate_user_data(install_dir)

    def _locate_user_data(self, install_dir):
        # Windows: next to eden.exe. macOS: Eden chdirs next to eden.app.
        # Linux: Eden checks its working directory, which it inherits from us.
        portable_root = os.getcwd() if sys.platform.startswith("linux") else install_dir
        portable = os.path.join(portable_root, "user")
        if os.path.isdir(portable):
            self.user_dir = portable
            self.config_path = os.path.join(portable, "config", "qt-config.ini")
            return

        if sys.platform == "win32":
            self.user_dir = os.path.join(os.getenv("APPDATA", ""), "eden")
            self.config_path = os.path.join(self.user_dir, "config", "qt-config.ini")
            return

        self.config_path = os.path.join(_xdg("XDG_CONFIG_HOME", "~/.config"), "eden", "qt-config.ini")
        self.user_dir = os.path.join(_xdg("XDG_DATA_HOME", "~/.local/share"), "eden")

    def log_dir(self):
        return os.path.join(self.user_dir, "log")

    # ------------------------------------------------------------------
    # 2. Runtime setup - runs before the SDL wrapper is imported
    # ------------------------------------------------------------------
    def prepare(self):
        """Pick the SDL backend from the library Eden ships, snapshot env."""
        self.backend, self.lib_dir = self._find_sdl()
        if self.lib_dir:
            log("INFO", f"{self.backend} library found in", self.lib_dir)
        else:
            log("WARNING", "No SDL library next to Eden, using the system one", self.backend)

        # Snapshot before Core.Sdl publishes its SDL_* loader variables
        self.env = os.environ.copy()

    def _find_sdl(self):
        """
        Look next to the binary, in an AppImage's usr/lib, and in a macOS
        bundle's Frameworks. SDL3 wins when both are present. When nothing is
        shipped (static build), fall back to the system SDL3.
        """
        dirs = [
            self.dir,
            os.path.normpath(os.path.join(self.dir, "..", "lib")),
            os.path.normpath(os.path.join(self.dir, "..", "Frameworks")),
        ]
        for backend in ("SDL3", "SDL2"):
            for d in dirs:
                for pattern in _SDL_PATTERNS[backend]:
                    if glob.glob(os.path.join(d, pattern)):
                        return backend, d
        return "SDL3", None

    def sdl_backend(self):
        return self.backend

    def sdl_dir(self):
        return self.lib_dir

    # ------------------------------------------------------------------
    # 3. Controller profiles
    # ------------------------------------------------------------------
    def load_profiles(self):
        return Config.load_profiles(self.config_path, Config.load_template(self.config_path))

    # ------------------------------------------------------------------
    # 4. Writing the launch configuration
    # ------------------------------------------------------------------
    def write_input_config(self, assignments, hardware):
        Config.write_input(self.config_path, assignments, hardware, self.profiles)

    # ------------------------------------------------------------------
    # 5. Teardown
    # ------------------------------------------------------------------
    def cleanup(self):
        if self.is_appimage:
            unmount_appimage()
