"""
Nextendo/Nextendo.py
The Ryujinx-Nextendo implementation of the Core.Emulator contract.

Ryujinx-Nextendo (https://git.nextendo.network/NextendoNetwork/Ryujinx-Nextendo)
is a Ryujinx fork. This package is self-contained: it depends on Core only,
never on the Ryujinx package, so the two launchers evolve independently.

    Data folder : always portable, never %APPDATA%. The launcher uses -r when
                  given, otherwise <exe dir>/portable, creating it if needed
                  so Nextendo also starts in portable mode when opened
                  directly.
    Input       : SDL3 only, a single Config.json input format (see Config.py).
"""

import os
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

from . import Config

# Releases ship the binary as Ryujinx(.exe); the others are accepted in case a
# build renames it
EXE_NAMES = ("Ryujinx", "Nextendo", "Ryujinx-Nextendo")


class Nextendo(Emulator):
    """Ryujinx-Nextendo (Ryujinx fork with Nextendo Network)."""

    name = "Nextendo"

    def __init__(self):
        super().__init__()
        self.data_root = None

    # ------------------------------------------------------------------
    # 1. Where everything lives
    # ------------------------------------------------------------------
    def locate(self, base):
        """
        Resolve the Nextendo directory, binary and Config.json.

        Directory priority : NextendoPath.config override > launcher directory.
        Data priority      : -r <dir> > <exe dir>/portable. Never %APPDATA%.
        """
        self.dir = read_path_override(base, self.name) or base

        ext = ".exe" if sys.platform == "win32" else ""
        candidates = [os.path.join(self.dir, n + ext) for n in EXE_NAMES]
        self.exe = next((c for c in candidates if os.path.exists(c)), None)
        if not self.exe:
            fatal(
                "Nextendo Missing",
                f"Could not find Ryujinx{ext} (Nextendo) in:\n{self.dir}\n\n"
                "Place NextendoLauncher next to it, or write its folder "
                "in a NextendoPath.config file.",
                "Nextendo binary not found", self.dir
            )

        # The portable folder always exists, even when -r is used, so that
        # Nextendo started any other way still stays out of %APPDATA%
        portable = os.path.join(self.dir, "portable")
        self.data_root = _root_data_dir(sys.argv[1:]) or portable
        for folder in {portable, self.data_root}:
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as e:
                fatal(
                    "Nextendo Data Folder",
                    f"Could not create the data folder:\n{folder}\n\n{e}",
                    "Data folder creation failed", folder
                )

        self.config_path = os.path.join(self.data_root, "Config.json")

    def log_dir(self):
        return os.path.join(self.data_root, "Logs")

    # ------------------------------------------------------------------
    # 2. Runtime setup - runs before the SDL wrapper is imported
    # ------------------------------------------------------------------
    def prepare(self):
        """Pick the launch binary and snapshot the child env."""
        # Prefer Ryujinx.sh over the raw binary on Linux when shipped: it sets
        # LANG=C.UTF-8, DOTNET_EnableAlternateStackCheck=1 and gamemoderun
        if sys.platform not in ("win32", "darwin"):
            wrapper = os.path.join(self.dir, "Ryujinx.sh")
            if os.path.exists(wrapper):
                self.exe = wrapper
                log("INFO", "Launch wrapper detected", self.exe)

        # Snapshot now, before Core.Sdl publishes its SDL_* loader variables -
        # those are for the launcher's python bindings and must not reach Nextendo
        self.env = os.environ.copy()

    def sdl_backend(self):
        return "SDL3"

    def sdl_dir(self):
        # Nextendo ships the SDL3 shared library next to its binary
        return self.dir

    # ------------------------------------------------------------------
    # 3. Controller profiles
    # ------------------------------------------------------------------
    def load_profiles(self):
        template = Config.load_template(self.config_path)
        return Config.load_profiles(self.config_path, template)

    # ------------------------------------------------------------------
    # 4. Writing the launch configuration
    # ------------------------------------------------------------------
    def write_input_config(self, assignments, hardware):
        Config.write_input(self.config_path, assignments, hardware, self.profiles)


def _root_data_dir(args):
    """
    The value of the -r / --root-data-dir option, as an absolute path.

    Accepts "-r DIR", "--root-data-dir DIR" and "--root-data-dir=DIR".
    Relative paths resolve against the working directory.
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
