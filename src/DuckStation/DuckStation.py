"""
DuckStation/DuckStation.py
The DuckStation (Qt) implementation of the Core.Emulator contract.
Depends on Core only, never on another emulator package.

Data folder (DuckStation README):
    An empty portable.txt next to the exe means portable mode, with all data
    in the exe folder. Without it DuckStation uses %LOCALAPPDATA%\\DuckStation
    (or Documents\\DuckStation). The launcher never lets that happen: it
    creates portable.txt when missing.

    settings.ini        settings, [PadN] controller sections
    inputprofiles/      input profiles

SDL: DuckStation loads SDL3.dll from its own folder. The launcher loads that
same library and applies DuckStation's joystick hints, so SDL hands out the
same player indexes in both processes (see Config.sdl_player_ids).
"""

import glob
import os
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

from . import Config

EXE_PATTERNS = (("duckstation-qt*.exe", "duckstation*.exe") if sys.platform == "win32"
                else ("duckstation-qt*", "DuckStation*"))
SDL_PATTERNS = ("SDL3.dll", "libSDL3*.so*", "libSDL3*.dylib")


class DuckStation(Emulator):
    """DuckStation (PlayStation emulator)."""

    name = "DuckStation"
    max_players = 8   # two multitaps

    def __init__(self):
        super().__init__()
        self.lib_dir = None

    # ------------------------------------------------------------------
    # 1. Where everything lives
    # ------------------------------------------------------------------
    def locate(self, base):
        self.dir = read_path_override(base, self.name) or base

        self.exe = next((m for p in EXE_PATTERNS
                         for m in sorted(glob.glob(os.path.join(self.dir, p)))
                         if "updater" not in os.path.basename(m).lower()), None)
        if not self.exe:
            fatal(
                "DuckStation Missing",
                f"Could not find duckstation-qt-*.exe in:\n{self.dir}\n\n"
                "Place DuckStationLauncher next to it, or write its folder "
                "in a DuckStationPath.config file.",
                "DuckStation binary not found", self.dir
            )

        marker = os.path.join(self.dir, "portable.txt")
        if not os.path.exists(marker):
            try:
                open(marker, "a").close()
                log("INFO", "Portable mode enabled", marker)
            except OSError as e:
                fatal(
                    "DuckStation Portable Mode",
                    f"Could not create:\n{marker}\n\n{e}",
                    "Portable marker creation failed", marker
                )

        self.config_path = os.path.join(self.dir, "settings.ini")
        self.cwd = self.dir

    def log_dir(self):
        return os.path.join(self.dir, "logs")

    # ------------------------------------------------------------------
    # 2. Runtime setup - runs before the SDL wrapper is imported
    # ------------------------------------------------------------------
    def prepare(self):
        self.lib_dir = self.dir if any(
            glob.glob(os.path.join(self.dir, p)) for p in SDL_PATTERNS) else None
        if not self.lib_dir:
            fatal(
                "SDL3 Missing",
                f"SDL3.dll was not found next to DuckStation:\n{self.dir}\n\n"
                "The launcher must use DuckStation's own SDL3 so controllers "
                "get the same numbers in both programs.",
                "SDL3 not found next to DuckStation", self.dir
            )

        # Snapshot before the hints below and before Core.Sdl's loader vars
        self.env = os.environ.copy()

        for hint, value in self._sdl_hints().items():
            os.environ[hint] = value
            log("INFO", "SDL hint", f"{hint}={value}")

    def _sdl_hints(self):
        """
        The enumeration-affecting hints SDLInputSource::SetHints() applies
        with DuckStation's defaults, then the user's own [SDLHints] last.
        """
        sources = Config.read_section(self.config_path, "InputSources")
        raw = sources.get("SDLRawInput", "false").lower() == "true"
        hints = {
            "SDL_JOYSTICK_HIDAPI_WII": "1",
            "SDL_JOYSTICK_HIDAPI_PS3": "1",
            "SDL_JOYSTICK_HIDAPI_XBOX": "0",
        }
        if sys.platform == "win32":
            hints.update({
                "SDL_JOYSTICK_RAWINPUT": "1" if raw else "0",
                "SDL_JOYSTICK_DIRECTINPUT": "1",
                "SDL_XINPUT_ENABLED": "1",
                "SDL_JOYSTICK_WGI": "0",
                "SDL_JOYSTICK_GAMEINPUT": "0",
            })
        hints.update(Config.read_section(self.config_path, "SDLHints"))

        # A mapping made with the XInput source needs each pad's XInput slot,
        # which SDL reports only for pads it opens through its XInput driver;
        # RawInput would take those pads over. Launcher-only: the emulator
        # still gets its own settings.
        if Config.template_source(self.config_path) == "XInput":
            hints["SDL_JOYSTICK_RAWINPUT"] = "0"
            hints["SDL_XINPUT_ENABLED"] = "1"
            log("INFO", "Default mapping uses the XInput source", "reading XInput slots")
        return hints

    def sdl_backend(self):
        return "SDL3"

    def sdl_dir(self):
        return self.lib_dir

    # ------------------------------------------------------------------
    # 3. Controller profiles
    # ------------------------------------------------------------------
    def load_profiles(self):
        return Config.load_profiles(self.config_path, os.path.join(self.dir, "inputprofiles"))

    # ------------------------------------------------------------------
    # 4. Writing the launch configuration
    # ------------------------------------------------------------------
    def write_input_config(self, assignments, hardware):
        Config.write_input(self.config_path, assignments, hardware, self.profiles)
