"""
PPSSPP/PPSSPP.py
The PPSSPP (Windows) implementation of the Core.Emulator contract.
Depends on Core only, never on another emulator package.

Data folder (Windows/main.cpp, InitMemstickDirectory):
    Without installed.txt next to the exe, PPSSPP keeps everything in
    <exe dir>/memstick (portable). With installed.txt it uses the folder
    written on its first line as the whole memstick (saves AND PSP/SYSTEM
    config); an empty installed.txt means Documents\\PPSSPP, which the
    launcher refuses instead of touching Documents.

    memstick/PSP/SYSTEM/controls.ini   [ControlMapping]

Input (Common/Input/InputState.*, Core/KeyMap.cpp, Core/ControlMapper.cpp):
    Cross = 20-190,1-52          one "<deviceId>-<keyCode>" per mapping,
                                 ',' between alternatives, ':' inside combos
    deviceId 20..23 = XInput user slot 0..3 (DEVICE_ID_XINPUT_0 + slot),
    10..19 = DirectInput pads in enumeration order. Input from a device only
    counts if a mapping names that device, so moving the XInput mappings to
    the assigned pad's slot makes that pad - and only that XInput pad - play.
    The default Windows mapping uses XInput slot 0 (KeyMapDefaults.cpp).

DirectInput pads have no stable number, so only XInput pads can be pinned.
PSP is single player.
"""

import glob
import os
import re
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

EXE_PATTERNS = ("PPSSPPWindows64.exe", "PPSSPP*.exe") if sys.platform == "win32" else ("PPSSPP*",)
SECTION = "ControlMapping"
XINPUT_BASE = 20
XINPUT_SLOTS = 4
XINPUT_DRIVER = "78"          # SDL GUID byte 14 = 'x'
DEFAULT_PROFILE = "Default"

# Speed hotkeys on player 1's pad (Core/KeyMap.cpp virtual keys):
#   R3 -> "Fast-forward" (VIRTKEY_FASTFORWARD, while held)
#   L3 -> "Rewind"       (VIRTKEY_REWIND, one saved step per press;
#                         needs Settings > System > Rewind snapshot interval)
# NKCODE_BUTTON_THUMBL = 106, NKCODE_BUTTON_THUMBR = 107. The PSP has no stick
# clicks, so neither collides with a game button. ',' separates alternatives.
L3_CODE = 106
R3_CODE = 107
SPEED_HOTKEYS = (("Fast-forward", R3_CODE), ("Rewind", L3_CODE))
# A binding this launcher wrote before: a stick click, or the Select + trigger
# combo (109 + axis 4034/4036) older versions used
_COMBO_RE = re.compile(rf"^2[0-3]-({L3_CODE}|{R3_CODE})$|^2[0-3]-109:2[0-3]-(4034|4036)$")

# "<device>-<code>" tokens whose device is an XInput slot
_XINPUT_TOKEN_RE = re.compile(r"(?<![\d-])(2[0-3])-(\d+)")
_SECTION_RE = re.compile(r"^\s*\[(.+)\]\s*$")
_SDL_PATTERNS = ("SDL3.dll", "SDL2.dll", "libSDL3*.so*", "libSDL2*.so*")


def _read_lines(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        return f.read().splitlines()


def _write_lines(path, lines):
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def _section_range(lines, section):
    start = None
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if start is None:
            if m and m.group(1).strip() == section:
                start = i + 1
        elif m:
            return start, i
    return (start, len(lines)) if start is not None else None


class PPSSPP(Emulator):
    """PPSSPP (PSP emulator)."""

    name = "PPSSPP"
    max_players = 1

    def __init__(self):
        super().__init__()
        self.base = None
        self.backend = "SDL3"
        self.lib_dir = None
        self.memstick = None

    def locate(self, base):
        self.base = base
        self.dir = read_path_override(base, self.name) or base

        self.exe = next((m for p in EXE_PATTERNS
                         for m in sorted(glob.glob(os.path.join(self.dir, p)))
                         if "launcher" not in os.path.basename(m).lower()), None)
        if not self.exe:
            fatal(
                "PPSSPP Missing",
                f"Could not find PPSSPPWindows64.exe in:\n{self.dir}\n\n"
                "Place PPSSPPLauncher next to it, or write its folder "
                "in a PPSSPPPath.config file.",
                "PPSSPP binary not found", self.dir
            )

        installed = os.path.join(self.dir, "installed.txt")
        self.memstick = os.path.join(self.dir, "memstick")
        if os.path.exists(installed):
            custom = self._read_installed(installed)
            if not custom:
                fatal(
                    "PPSSPP Is Not Portable",
                    f"This file exists but is empty:\n{installed}\n\n"
                    "An empty installed.txt makes PPSSPP keep its data in "
                    "Documents. Write your memstick folder in it, or delete it "
                    "to use the memstick folder next to PPSSPP.",
                    "installed.txt empty", installed
                )
            self.memstick = custom
            log("INFO", "Memstick folder from installed.txt", custom)

        self.config_path = os.path.join(self.memstick, "PSP", "SYSTEM", "controls.ini")
        self.cwd = self.dir

    @staticmethod
    def _read_installed(path):
        """The memstick folder written in installed.txt (first line), or None."""
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                line = f.readline().strip().strip('"')
        except OSError as e:
            log("EXCEPTION", "installed.txt read failed", e)
            return None
        return os.path.normpath(line) if line else None

    def log_dir(self):
        return os.path.join(self.dir, "logs")

    def prepare(self):
        self.lib_dir = next((d for d in (self.dir, self.base) if d and any(
            glob.glob(os.path.join(d, p)) for p in _SDL_PATTERNS)), None)
        if not self.lib_dir:
            fatal(
                "SDL Library Missing",
                "The launcher needs SDL to find each controller's XInput slot.\n\n"
                f"Place SDL3.dll next to PPSSPP:\n{self.dir}\n\n"
                "(SDL3.dll comes in the SDL3-<version>-win32-x64.zip release "
                "at github.com/libsdl-org/SDL/releases.)",
                "No SDL library found", self.dir
            )
        self.backend = "SDL3" if glob.glob(os.path.join(self.lib_dir, "*SDL3*")) else "SDL2"
        log("INFO", f"{self.backend} library found in", self.lib_dir)

        self.env = os.environ.copy()
        # PPSSPP reads pads through XInput itself; SDL must open them through
        # its XInput driver to report the XInput slot as the player index
        for hint, value in (("SDL_JOYSTICK_RAWINPUT", "0"), ("SDL_XINPUT_ENABLED", "1"),
                            ("SDL_JOYSTICK_HIDAPI_XBOX", "0")):
            os.environ[hint] = value
            log("INFO", "SDL hint", f"{hint}={value}")

    def sdl_backend(self):
        return self.backend

    def sdl_dir(self):
        return self.lib_dir

    def load_profiles(self):
        return {DEFAULT_PROFILE: None}

    @staticmethod
    def _set_combo(lines, key, combo):
        """Add `combo` to `key` in [ControlMapping], keeping the user's own."""
        start, end = _section_range(lines, SECTION)
        for i in range(start, end):
            if "=" in lines[i] and lines[i].split("=", 1)[0].strip() == key:
                values = [v.strip() for v in lines[i].split("=", 1)[1].split(",") if v.strip()]
                values = [v for v in values if not _COMBO_RE.match(v)] + [combo]
                lines[i] = f"{key} = {','.join(values)}"
                return
        insert_at = end
        while insert_at > start and not lines[insert_at - 1].strip():
            insert_at -= 1
        lines.insert(insert_at, f"{key} = {combo}")

    def write_input_config(self, assignments, hardware):
        if not assignments:
            return
        hw = next((h for h in hardware if h["path"] == assignments[0]["path"]), None)
        if not hw:
            return
        slot = hw.get("player_index", -1)
        if hw["guid"].lower()[28:30] != XINPUT_DRIVER or not 0 <= slot < XINPUT_SLOTS:
            log("WARNING", "Not an XInput pad, PPSSPP's mapping left unchanged", hw["name"])
            return

        device = XINPUT_BASE + slot
        log("INFO", f"Saving -> Player 1 | {hw['name']} | XInput slot {slot} | device {device}")

        if not os.path.exists(self.config_path):
            # Without controls.ini PPSSPP uses its defaults (XInput slot 0).
            # Creating it with only a few keys would drop the other defaults.
            log("WARNING", "controls.ini missing; open PPSSPP > Settings > Controls and "
                           "change any mapping once so the launcher can set the pad and "
                           "the R3 / L3 speed hotkeys", self.config_path)
            return

        try:
            lines = _read_lines(self.config_path)
        except Exception as e:
            log("EXCEPTION", "controls.ini read failed", e)
            return
        bounds = _section_range(lines, SECTION)
        if not bounds:
            log("WARNING", "No [ControlMapping] in controls.ini", self.config_path)
            return

        changed = 0
        for i in range(*bounds):
            new = _XINPUT_TOKEN_RE.sub(lambda m: f"{device}-{m.group(2)}", lines[i])
            if new != lines[i]:
                lines[i] = new
                changed += 1
        log("INFO", "XInput mappings moved to device", f"{device} ({changed} lines)")

        for key, code in SPEED_HOTKEYS:
            binding = f"{device}-{code}"
            self._set_combo(lines, key, binding)
            log("INFO", "Speed hotkey", f"{key} += {binding}")

        try:
            _write_lines(self.config_path, lines)
        except Exception as e:
            log("EXCEPTION", "controls.ini write failed, PPSSPP will use the old mapping", e)
