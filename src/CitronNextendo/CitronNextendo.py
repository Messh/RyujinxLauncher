"""
CitronNextendo/CitronNextendo.py
The Citron-Nextendo (git.nextendo.network) implementation of the Core.Emulator contract.

Citron is a yuzu fork; the input format is yuzu's (see Config.py). This
package depends on Core only, never on another emulator package.

Data folder (src/common/fs/path_util.cpp):
    Citron uses <exe dir>/user/ when that folder exists, otherwise
    %APPDATA%/citron - a folder every Citron build shares. The launcher never
    uses %APPDATA%: it creates user/ when missing, so Citron itself starts in
    portable mode too, even when opened without the launcher.

    user/config/qt-config.ini   [Controls]
    user/config/input/*.ini     input profiles
    user/log/                   logs (the launcher writes its own there too)
"""

import glob
import os
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

from . import Config

EXE_NAMES = ("citron.exe", "Citron.exe") if sys.platform == "win32" else ("citron", "Citron")

# Shared-library patterns per SDL major version, searched in sdl_dir()
_SDL_PATTERNS = {
    "SDL3": ("SDL3.dll", "libSDL3*.so*", "libSDL3*.dylib"),
    "SDL2": ("SDL2.dll", "libSDL2*.so*", "libSDL2*.dylib"),
}


class CitronNextendo(Emulator):
    """Citron-Nextendo (Citron fork with Nextendo Network)."""

    name = "CitronNextendo"

    def __init__(self):
        super().__init__()
        self.backend = "SDL3"
        self.lib_dir = None
        self.user_dir = None

    # ------------------------------------------------------------------
    # 1. Where everything lives
    # ------------------------------------------------------------------
    def locate(self, base):
        """
        Resolve the Citron directory, binary and qt-config.ini.

        Directory priority : CitronNextendoPath.config override > launcher directory.
        Data               : <exe dir>/user/, created if missing. Never %APPDATA%.
        """
        self.dir = read_path_override(base, self.name) or base

        candidates = [os.path.join(self.dir, n) for n in EXE_NAMES]
        self.exe = next((c for c in candidates if os.path.exists(c)), None)
        if not self.exe:
            fatal(
                f"{self.name} Missing",
                f"Could not find {EXE_NAMES[0]} in:\n{self.dir}\n\n"
                f"Place {self.name}Launcher next to it, or write its folder "
                f"in a {self.name}Path.config file.",
                "Citron binary not found", self.dir
            )

        self.user_dir = os.path.join(self.dir, "user")
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
        """Pick the SDL backend from the library Citron ships, snapshot env."""
        self.backend, self.lib_dir = self._find_sdl()
        if self.lib_dir:
            log("INFO", f"{self.backend} library found in", self.lib_dir)
        else:
            log("WARNING", "No SDL library next to Citron, using the system one", self.backend)

        # Snapshot before Core.Sdl publishes its SDL_* loader variables, and
        # before the hints below: Citron sets its own hints and must not inherit ours
        self.env = os.environ.copy()

        # The launcher's SDL must enumerate pads exactly like Citron's, or the
        # GUIDs it writes never match a pad Citron can see
        for hint, value in self._sdl_hints().items():
            os.environ[hint] = value
            log("INFO", "SDL hint", f"{hint}={value}")

    def _sdl_hints(self):
        """
        The enumeration-affecting hints Citron sets in its SDL driver
        (input_common/drivers/sdl_driver.cpp), following [Controls].
        """
        controls = Config.read_controls(self.config_path)

        def enabled(key, default):
            return controls.get(key, default).strip().strip('"').lower() == "true"

        hints = {
            "SDL_JOYSTICK_HIDAPI_XBOX": "0",
            "SDL_JOYSTICK_HIDAPI_SWITCH": "0" if enabled("enable_procon_driver", "false") else "1",
            "SDL_JOYSTICK_HIDAPI_JOY_CONS": "0" if enabled("enable_joycon_driver", "true") else "1",
            "SDL_JOYSTICK_HIDAPI_COMBINE_JOY_CONS": "1",
            "SDL_JOYSTICK_HIDAPI_VERTICAL_JOY_CONS": "1",
            "SDL_JOYSTICK_HIDAPI_SWITCH2": "1",
        }
        # Citron only touches this hint to disable RawInput
        if not enabled("enable_raw_input", "false"):
            hints["SDL_JOYSTICK_RAWINPUT"] = "0"
        return hints

    def _find_sdl(self):
        """SDL3 wins over SDL2. Static builds fall back to the system SDL3."""
        for backend in ("SDL3", "SDL2"):
            for pattern in _SDL_PATTERNS[backend]:
                if glob.glob(os.path.join(self.dir, pattern)):
                    return backend, self.dir
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
