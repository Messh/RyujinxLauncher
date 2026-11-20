"""
Yuzu/Yuzu.py
The yuzu implementation of the Core.Emulator contract.

yuzu (mainline / early access, development ended in 2024) needs no version
detection: its input format is the one Eden and Citron inherited, see
Config.py. Windows builds ship SDL2. This package depends on Core only, never
on another emulator package.

Data folder (src/common/fs/path_util.cpp):
    Windows        <exe dir>/user/       when it exists, else %APPDATA%/yuzu
    Linux / macOS  <working dir>/user/   when it exists, else the XDG folders

    user/config/qt-config.ini   [Controls]
    user/config/input/*.ini     input profiles
    user/log/                   logs (the launcher writes its own there too)

The launcher is portable-only: it never uses %APPDATA% or the XDG folders. It
creates user/ when missing (next to yuzu.exe, or next to the AppImage / binary
/ yuzu.app on Linux and macOS, which becomes yuzu's working directory), so
yuzu starts in portable mode too, even when opened without the launcher.
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


def _first_existing(paths):
    return next((p for p in paths if os.path.exists(p)), None)


class Yuzu(Emulator):
    """yuzu (Nintendo Switch emulator)."""

    name = "Yuzu"

    def __init__(self):
        super().__init__()
        self.backend = "SDL2"
        self.lib_dir = None
        self.user_dir = None
        self.appimage_path = None

    # ------------------------------------------------------------------
    # 1. Where everything lives
    # ------------------------------------------------------------------
    def locate(self, base):
        """
        Resolve the yuzu directory, binary and qt-config.ini.

        Directory priority : YuzuPath.config override > launcher directory.
        Data               : <install dir>/user/, created if missing.
                             Never %APPDATA% or the XDG folders.
        """
        self.dir = read_path_override(base, self.name) or base
        install_dir = self.dir

        if sys.platform == "win32":
            self.exe = _first_existing(
                [os.path.join(self.dir, n) for n in ("yuzu.exe", "Yuzu.exe")]
            ) or os.path.join(self.dir, "yuzu.exe")

        elif sys.platform == "darwin":
            self.exe = _first_existing([
                os.path.join(self.dir, b, "Contents", "MacOS", "yuzu")
                for b in ("yuzu.app", "Yuzu.app")
            ] + [os.path.join(self.dir, "yuzu")]   # launcher placed inside MacOS/
            ) or os.path.join(self.dir, "yuzu.app", "Contents", "MacOS", "yuzu")
            self.dir = os.path.dirname(self.exe)

        else:  # Linux
            self.appimage_path = find_appimage(self.dir, "yuzu")
            self.is_appimage = self.appimage_path is not None
            if self.is_appimage:
                mount_point = mount_appimage(self.appimage_path)
                self.dir = os.path.join(mount_point, "usr", "bin")
            self.exe = _first_existing(
                [os.path.join(self.dir, n) for n in ("yuzu", "Yuzu")]
            ) or os.path.join(self.dir, "yuzu")

        if not os.path.exists(self.exe):
            fatal(
                f"{self.name} Missing",
                f"Could not find {os.path.basename(self.exe)} in:\n{self.dir}\n\n"
                f"Place {self.name}Launcher next to it, or write its folder "
                f"in a {self.name}Path.config file.",
                "yuzu binary not found", self.exe
            )

        # Windows: yuzu looks next to yuzu.exe. Linux/macOS: yuzu looks in its
        # working directory, so start it from the install folder
        if sys.platform != "win32":
            self.cwd = install_dir

        self.user_dir = os.path.join(install_dir, "user")
        try:
            os.makedirs(self.user_dir, exist_ok=True)
        except OSError as e:
            fatal(
                f"{self.name} Data Folder",
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
        """Pick the SDL backend from the library yuzu ships, snapshot env."""
        self.backend, self.lib_dir = self._find_sdl()
        if self.lib_dir:
            log("INFO", f"{self.backend} library found in", self.lib_dir)
        else:
            log("WARNING", "No SDL library next to yuzu, using the system one", self.backend)

        # Snapshot before Core.Sdl publishes its SDL_* loader variables, and
        # before the hints below: yuzu sets its own hints and must not inherit ours
        self.env = os.environ.copy()

        # The launcher's SDL must enumerate pads exactly like yuzu's, or the
        # GUIDs it writes (whose last bytes name the Windows driver: 'x' XInput,
        # 'r' RawInput, 'h' HIDAPI) never match a pad yuzu can see
        for hint, value in self._sdl_hints().items():
            os.environ[hint] = value
            log("INFO", "SDL hint", f"{hint}={value}")

    def _sdl_hints(self):
        """
        The enumeration-affecting hints yuzu sets in its SDL driver
        (input_common/drivers/sdl_driver.cpp), following [Controls].
        """
        controls = Config.read_controls(self.config_path)

        def enabled(key, default):
            return controls.get(key, default).strip().strip('"').lower() == "true"

        hints = {
            "SDL_JOYSTICK_HIDAPI_XBOX": "0",
            "SDL_JOYSTICK_HIDAPI_SWITCH": "0" if enabled("enable_procon_driver", "false") else "1",
            "SDL_JOYSTICK_HIDAPI_JOY_CONS": "0" if enabled("enable_joycon_driver", "true") else "1",
            "SDL_ACCELEROMETER_AS_JOYSTICK": "0",
        }
        # yuzu only touches this hint to disable RawInput; with raw input on,
        # SDL2's own default (RawInput ON) applies to both processes
        if not enabled("enable_raw_input", "false"):
            hints["SDL_JOYSTICK_RAWINPUT"] = "0"
        return hints

    def _find_sdl(self):
        """
        Look next to the binary, in an AppImage's usr/lib, and in a macOS
        bundle's Frameworks. SDL3 wins when both are present. When nothing is
        shipped (static build), fall back to the system SDL2 yuzu builds with.
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
        return "SDL2", None

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
