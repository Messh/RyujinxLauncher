"""
Gopher64/Gopher64.py
The gopher64 implementation of the Core.Emulator contract.
Depends on Core only, never on another emulator package.

Data folder (src/ui.rs, get_dirs):
    portable.txt next to the exe means portable mode, with config in
    <exe dir>/portable_data/config/config.json. Otherwise gopher64 uses the
    per-user folders. The launcher never lets that happen: it creates
    portable.txt when missing.

Input (src/ui/config.rs, src/ui/input.rs):
    "input": {
        "input_profiles": {"default": {...}, ...},     # no device inside
        "input_profile_binding": ["default", ...],     # port -> profile
        "controller_assignment": ["XInput#0", null, ...],  # port -> SDL path
        "controller_enabled": [true, false, false, false],
        ...
    }
    At game start gopher64 binds each enabled port to the connected pad whose
    SDL joystick path (SDL_GetJoystickPathForID) equals the stored string.
    The launcher writes the same path Core reads from SDL, so a specific pad
    lands on a specific port. Profiles are gopher64's own input profiles.

SDL: gopher64 links SDL3 statically and sets no enumeration hints. The
launcher looks for SDL3.dll next to the exe or next to itself, and keeps
SDL3's defaults (RawInput off) so the paths it reads match gopher64's.
"""

import glob
import json
import os
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

PORTS = 4
EXE_PATTERNS = ("gopher64*.exe",) if sys.platform == "win32" else ("gopher64*",)
_SDL_PATTERNS = {
    "SDL3": ("SDL3.dll", "libSDL3*.so*", "libSDL3*.dylib"),
    "SDL2": ("SDL2.dll", "libSDL2*.so*", "libSDL2*.dylib"),
}


class Gopher64(Emulator):
    """gopher64 (Nintendo 64 emulator)."""

    name = "Gopher64"
    max_players = PORTS

    def __init__(self):
        super().__init__()
        self.base = None
        self.data_dir = None
        self.backend = "SDL3"
        self.lib_dir = None

    # ------------------------------------------------------------------
    # 1. Where everything lives
    # ------------------------------------------------------------------
    def locate(self, base):
        self.base = base
        self.dir = read_path_override(base, self.name) or base

        self.exe = next((m for p in EXE_PATTERNS
                         for m in sorted(glob.glob(os.path.join(self.dir, p)))
                         if not os.path.basename(m).lower().startswith("gopher64launcher")), None)
        if not self.exe:
            fatal(
                "gopher64 Missing",
                f"Could not find gopher64-windows-x86_64.exe in:\n{self.dir}\n\n"
                "Place Gopher64Launcher next to it, or write its folder "
                "in a Gopher64Path.config file.",
                "gopher64 binary not found", self.dir
            )

        marker = os.path.join(self.dir, "portable.txt")
        if not os.path.exists(marker):
            try:
                open(marker, "a").close()
                log("INFO", "Portable mode enabled", marker)
            except OSError as e:
                fatal("gopher64 Portable Mode", f"Could not create:\n{marker}\n\n{e}",
                      "Portable marker creation failed", marker)

        self.data_dir = os.path.join(self.dir, "portable_data")
        self.config_path = os.path.join(self.data_dir, "config", "config.json")
        self.cwd = self.dir

    def log_dir(self):
        return os.path.join(self.data_dir, "logs")

    # ------------------------------------------------------------------
    # 2. Runtime setup
    # ------------------------------------------------------------------
    def prepare(self):
        self.backend, self.lib_dir = self._find_sdl()
        if not self.lib_dir:
            fatal(
                "SDL Library Missing",
                "gopher64 has SDL built in, so the launcher needs its own copy "
                "to read the controllers.\n\n"
                f"Place SDL3.dll next to gopher64:\n{self.dir}\n\n"
                "(SDL3.dll comes in the SDL3-<version>-win32-x64.zip release "
                "at github.com/libsdl-org/SDL/releases.)",
                "No SDL library found", self.dir
            )
        log("INFO", f"{self.backend} library found in", self.lib_dir)

        self.env = os.environ.copy()
        # gopher64's SDL3 runs with RawInput off (SDL3 default); pin it so an
        # SDL2 library, whose default is on, reports the same device paths
        os.environ["SDL_JOYSTICK_RAWINPUT"] = "0"
        log("INFO", "SDL hint", "SDL_JOYSTICK_RAWINPUT=0")

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

    # ------------------------------------------------------------------
    # 3. Controller profiles - gopher64's own input profiles
    # ------------------------------------------------------------------
    def _load_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            fatal(
                "gopher64 Setup Required",
                "gopher64 has not created its configuration yet.\n\n"
                "Open gopher64 once (portable mode is already enabled) and "
                "close it, then try again.",
                "config.json not found", self.config_path
            )
        except Exception as e:
            log("EXCEPTION", "Config read exception", e)
            fatal("Configuration Error",
                  f"Could not read gopher64's config.json:\n{self.config_path}",
                  "config.json unreadable", self.config_path)

    def load_profiles(self):
        config = self._load_config()
        names = list(config.get("input", {}).get("input_profiles", {}) or ["default"])
        if "default" in names:
            names.remove("default")
            names.insert(0, "default")
        log("INFO", "Profiles loaded", str(len(names)))
        return {name: name for name in names}

    # ------------------------------------------------------------------
    # 4. Writing the launch configuration
    # ------------------------------------------------------------------
    def write_input_config(self, assignments, hardware):
        config = self._load_config()
        inp = config.setdefault("input", {})
        paths = {hw["path"]: hw for hw in hardware}

        assignment = [None] * PORTS
        enabled = [False] * PORTS
        binding = list(inp.get("input_profile_binding") or ["default"] * PORTS)
        binding += ["default"] * (PORTS - len(binding))

        port = 0
        for a in assignments:
            hw = paths.get(a["path"])
            if not hw or port >= PORTS:
                continue
            if not hw["path"] or hw["path"].startswith("GUID_"):
                log("WARNING", "Pad has no SDL path, cannot pin it", hw["name"])
                continue
            assignment[port] = hw["path"]
            enabled[port] = True
            binding[port] = self.profiles[a["profile_key"]]
            log("INFO", f"Saving -> Player {port+1} | {hw['name']} | Profile: {binding[port]} | path {hw['path']}")
            port += 1

        inp["controller_assignment"] = assignment
        inp["controller_enabled"] = enabled
        inp["input_profile_binding"] = binding[:PORTS]

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log("EXCEPTION", "Config write failed, gopher64 will use the old config", e)
