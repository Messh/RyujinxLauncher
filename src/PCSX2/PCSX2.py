"""
PCSX2/PCSX2.py
The PCSX2 (Qt) implementation of the Core.Emulator contract.
Depends on Core only, never on another emulator package.

Data folder (pcsx2/Pcsx2Config.cpp, EmuFolders):
    portable.ini or portable.txt next to the exe means portable mode, with
    the data root in the exe folder (portable.txt may hold another path).
    Without either, PCSX2 uses Documents\\PCSX2. The launcher never lets
    that happen: it creates an empty portable.ini when no marker exists.

    <data>/inis/PCSX2.ini     settings, [PadN] controller sections
    <data>/inputprofiles/     input profiles
    <data>/logs/              logs (the launcher writes its own there too)

SDL: PCSX2 ships SDL3.dll next to its exe. The launcher loads that same
library and applies PCSX2's joystick hints, so SDL hands out the same player
indexes in both processes (see Config.sdl_player_ids).
"""

import glob
import os
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

from . import Config

EXE_PATTERNS = ("pcsx2-qt.exe", "pcsx2*.exe") if sys.platform == "win32" else ("pcsx2-qt", "pcsx2*")
PORTABLE_MARKERS = ("portable.ini", "portable.txt")
SDL_PATTERNS = ("SDL3.dll", "libSDL3*.so*", "libSDL3*.dylib")


class PCSX2(Emulator):
    """PCSX2 (PlayStation 2 emulator)."""

    name = "PCSX2"
    max_players = 8   # two multitaps

    def __init__(self):
        super().__init__()
        self.data_dir = None
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
                "PCSX2 Missing",
                f"Could not find pcsx2-qt.exe in:\n{self.dir}\n\n"
                "Place PCSX2Launcher next to it, or write its folder "
                "in a PCSX2Path.config file.",
                "PCSX2 binary not found", self.dir
            )

        self.data_dir = self._portable_root()
        self.config_path = os.path.join(self.data_dir, "inis", "PCSX2.ini")
        self.cwd = self.dir

    def _portable_root(self):
        """Data root from the portable marker, creating portable.ini if needed."""
        markers = [os.path.join(self.dir, m) for m in PORTABLE_MARKERS]
        if not any(os.path.exists(m) for m in markers):
            try:
                open(markers[0], "a").close()
                log("INFO", "Portable mode enabled", markers[0])
            except OSError as e:
                fatal(
                    "PCSX2 Portable Mode",
                    f"Could not create:\n{markers[0]}\n\n{e}",
                    "Portable marker creation failed", markers[0]
                )

        # portable.txt may name another data folder (relative to the exe)
        txt = markers[1]
        if os.path.exists(txt):
            try:
                with open(txt, "r", encoding="utf-8") as f:
                    custom = f.readline().strip().strip('"')
            except OSError:
                custom = ""
            if custom:
                return os.path.normpath(os.path.join(self.dir, custom))
        return self.dir

    def log_dir(self):
        return os.path.join(self.data_dir, "logs")

    # ------------------------------------------------------------------
    # 2. Runtime setup - runs before the SDL wrapper is imported
    # ------------------------------------------------------------------
    def prepare(self):
        self.lib_dir = self.dir if any(
            glob.glob(os.path.join(self.dir, p)) for p in SDL_PATTERNS) else None
        if not self.lib_dir:
            fatal(
                "SDL3 Missing",
                f"SDL3.dll was not found next to PCSX2:\n{self.dir}\n\n"
                "The launcher must use PCSX2's own SDL3 so controllers get "
                "the same numbers in both programs.",
                "SDL3 not found next to PCSX2", self.dir
            )

        # Snapshot before the hints below and before Core.Sdl's loader vars
        self.env = os.environ.copy()

        for hint, value in self._sdl_hints().items():
            os.environ[hint] = value
            log("INFO", "SDL hint", f"{hint}={value}")

    def _sdl_hints(self):
        """
        The enumeration-affecting hints SDLInputSource::SetHints() applies,
        following [InputSources], then the user's own [SDLHints] last.
        """
        sources = Config.read_section(self.config_path, "InputSources")
        raw = sources.get("SDLRawInput", "false").lower() == "true"
        hints = {
            "SDL_JOYSTICK_RAWINPUT": "1" if raw else "0",
            "SDL_JOYSTICK_HIDAPI_WII": "1",
        }
        if sys.platform == "win32":
            hints["SDL_JOYSTICK_HIDAPI_PS3_SIXAXIS_DRIVER"] = "1"
        else:
            hints["SDL_JOYSTICK_HIDAPI_PS3"] = "1"
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
        return Config.load_profiles(self.config_path, os.path.join(self.data_dir, "inputprofiles"))

    # ------------------------------------------------------------------
    # 4. Writing the launch configuration
    # ------------------------------------------------------------------
    def write_input_config(self, assignments, hardware):
        Config.write_input(self.config_path, assignments, hardware, self.profiles)
