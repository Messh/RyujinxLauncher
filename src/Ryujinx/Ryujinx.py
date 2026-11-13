"""
Ryujinx/Ryujinx.py
The Ryujinx implementation of the Core.Emulator contract.

Everything Ryujinx-specific enters the launcher through this class:
where the binary and Config.json live, how the version is detected, which
SDL backend that version needs, and what environment Ryujinx wants.
"""

import os
import re
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import find_appimage, read_path_override
from Core.Process import mount_appimage, unmount_appimage

from . import Config, Version

# Ryujinx switched its SDL backend after this version
SDL2_MAX_VERSION = "1.3.205"


class Ryujinx(Emulator):
    """Ryujinx (Nintendo Switch emulator)."""

    name = "Ryujinx"

    def __init__(self):
        super().__init__()
        self.version = Version.DEFAULT_VERSION
        self.backend = "SDL2"
        self.backend_string = "GamepadSDL2"
        self.appimage_path = None
        self.data_root = None     # -r folder or portable/, when Ryujinx uses one

    # ------------------------------------------------------------------
    # 1. Where everything lives
    # ------------------------------------------------------------------
    def locate(self, base):
        """
        Resolve the Ryujinx directory, binary and Config.json.

        Directory priority : RyujinxPath.config override > launcher directory.
        Data priority      : -r <dir> > <exe dir>/portable > per-user default.
        On Linux an AppImage is mounted and self.dir becomes <mount>/usr/bin,
        so version detection, the SDL search path and the binary path all keep
        working unchanged from the mount point. The mount stays alive for the
        whole session and is released in cleanup().
        """
        self.dir = read_path_override(base, self.name) or base

        if sys.platform == "win32":
            self.exe = os.path.join(self.dir, "Ryujinx.exe")

            # Without a data root (below): local > AppData
            local_config = os.path.join(self.dir, "Config.json")
            appdata_config = os.path.join(os.getenv('APPDATA'), "Ryujinx", "Config.json")
            self.config_path = local_config if os.path.exists(local_config) else appdata_config

        elif sys.platform == "darwin":
            self.exe = os.path.join(self.dir, "Ryujinx")
            self.config_path = os.path.expanduser("~/.config/Ryujinx/Config.json")

        else:  # Linux
            self.appimage_path = find_appimage(self.dir, "ryujinx")
            self.is_appimage = self.appimage_path is not None
            if self.is_appimage:
                mount_point = mount_appimage(self.appimage_path)
                self.dir = os.path.join(mount_point, "usr", "bin")

            self.exe = os.path.join(self.dir, "Ryujinx")
            self.config_path = os.path.expanduser("~/.config/Ryujinx/Config.json")

        # A data root replaces everything above, same priority Ryujinx uses:
        #   1. -r / --root-data-dir on the command line
        #   2. a "portable" folder next to the binary (it only has to exist)
        # Ryujinx keeps Config.json, profiles/ and Logs/ there, so the launcher
        # must write the controller mapping there too.
        self.data_root = _root_data_dir(sys.argv[1:])
        if not self.data_root:
            portable = os.path.join(self.dir, "portable")
            if os.path.isdir(portable):
                self.data_root = portable
        if self.data_root:
            self.config_path = os.path.join(self.data_root, "Config.json")

        if not os.path.exists(self.exe):
            fatal(
                "Ryujinx Missing",
                f"Could not find {self.exe} in:\n{self.dir}",
                "Ryujinx binary not found", self.exe
            )

    def log_dir(self):
        if self.data_root:
            return os.path.join(self.data_root, "Logs")
        if sys.platform == "win32":
            return os.path.join(self.dir, "Logs")
        return os.path.expanduser("~/.config/Ryujinx/Logs")

    # ------------------------------------------------------------------
    # 2. Runtime setup - runs before the SDL wrapper is imported
    # ------------------------------------------------------------------
    def prepare(self):
        """Detect the version, pick the SDL backend, snapshot the child env."""
        # Version must be read from the real binary, before the .sh wrapper swap
        self.version = Version.detect(self.exe)

        # Prefer Ryujinx.sh over the raw binary when available.
        # The shell wrapper sets LANG=C.UTF-8, DOTNET_EnableAlternateStackCheck=1,
        # and enables gamemoderun if installed - giving better runtime stability.
        if sys.platform not in ("win32", "darwin"):
            wrapper = os.path.join(self.dir, "Ryujinx.sh")
            if os.path.exists(wrapper):
                self.exe = wrapper
                log("INFO", "Launch wrapper detected", self.exe)

        # SDL backend follows the Ryujinx version
        if _version_tuple(self.version) <= _version_tuple(SDL2_MAX_VERSION):
            self.backend = "SDL2"
            self.backend_string = "GamepadSDL2"
        else:
            self.backend = "SDL3"
            self.backend_string = "GamepadSDL3"

        # Old builds mis-detect controllers through the RawInput backend
        if self.version == Version.DEFAULT_VERSION:
            os.environ["SDL_JOYSTICK_RAWINPUT"] = "0"

        # Snapshot now, before Core.Sdl publishes its SDL_* loader variables -
        # those are for the launcher's python bindings and must not reach Ryujinx
        self.env = os.environ.copy()

    def sdl_backend(self):
        return self.backend

    def sdl_dir(self):
        # Ryujinx ships the SDL shared library next to its binary
        return self.dir

    # ------------------------------------------------------------------
    # 3. Controller profiles
    # ------------------------------------------------------------------
    def load_profiles(self):
        template = Config.load_template(self.config_path, self.backend_string)
        return Config.load_profiles(self.config_path, template)

    # ------------------------------------------------------------------
    # 4. Writing the launch configuration
    # ------------------------------------------------------------------
    def write_input_config(self, assignments, hardware):
        Config.write_input(
            self.config_path,
            assignments,
            hardware,
            self.profiles,
            self.version,
            self.backend_string
        )

    # ------------------------------------------------------------------
    # 5. Teardown
    # ------------------------------------------------------------------
    def cleanup(self):
        if self.is_appimage:
            unmount_appimage()


def _root_data_dir(args):
    """
    The value of Ryujinx's -r / --root-data-dir option, as an absolute path.

    Accepts "-r DIR", "--root-data-dir DIR" and "--root-data-dir=DIR".
    Relative paths resolve against the working directory, like Ryujinx does.
    Returns None when the option is absent.
    """
    for i, arg in enumerate(args):
        if arg.startswith("--root-data-dir="):
            value = arg.split("=", 1)[1]
        elif arg in ("-r", "--root-data-dir") and i + 1 < len(args):
            value = args[i + 1]
        else:
            continue
        return os.path.abspath(value.strip('"'))
    return None


def _version_tuple(version):
    """"1.3.205" -> (1, 3, 205), for ordered comparison."""
    return tuple(map(int, re.findall(r'\d+', version)))
