"""
Mesen/Mesen.py
The Mesen 2 (MesenCE) implementation of the Core.Emulator contract.
Depends on Core only, never on another emulator package.

Data folder (UI/Config/ConfigManager.cs, HomeFolder):
    settings.json next to Mesen.exe means portable mode. Otherwise Mesen
    uses Documents\\MesenCE. The launcher never lets that happen: it creates
    settings.json ("{}", Mesen fills in defaults) when missing.

Input (UI/Config/*Config.cs, Windows/WindowsKeyManager.cpp):
    settings.json, PascalCase:  "Snes": { "Port1": { "Mapping1": { "A": 4109, ... } } }
    Each key is a UInt16 code. XInput pad buttons are
        0x1000 + slot * 0x100 + button        (slot = XInput user index 0-3)
    so "Pad1 A" = 0x100D and "Pad2 A" = 0x110D. Keyboard codes are below
    0x1000; DirectInput pads use 0x2000+ with an unstable enumeration index
    and cannot be pinned.

Consoles handled: NES, SNES and Game Boy / Game Boy Color (both use the
"Gameboy" config). Other Mesen consoles are left alone.

At launch every XInput code inside a player's ports is moved to the slot of
the pad assigned to that player, keeping the user's own button layout:
    player 1 -> Nes.Port1, Snes.Port1, Gameboy.Controller
    player 2 -> Nes.Port2, Snes.Port2 (Game Boy is single player)
If player 2's port has no XInput mapping yet, player 1's mappings are copied
into it first, and a port whose Type is "None" gets the console's pad.
Ports of players that are not assigned are left as they are.
"""

import glob
import json
import os
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

EXE_NAMES = ("Mesen.exe",) if sys.platform == "win32" else ("Mesen",)
DEFAULT_PROFILE = "Default"

XINPUT_BASE = 0x1000
XINPUT_SLOTS = 4
XINPUT_DRIVER = "78"          # SDL GUID byte 14 = 'x'

# Shortcuts on player 1's pad (EmulatorShortcut):
#   R3      -> FastForward (while held)    L3      -> Rewind (while held)
#   L1 + L3 -> SaveState   (current slot)  R1 + R3 -> LoadState (current slot)
# XInput button numbers (Windows/WindowsKeyManager.cpp buttonNames, 1-based,
# bit order of XINPUT_GAMEPAD_*): L3 = 7 (LEFT_THUMB 0x40), R3 = 8 (RIGHT_THUMB
# 0x80), L1 = 9 (LEFT_SHOULDER 0x100), R1 = 10 (RIGHT_SHOULDER 0x200).
# Preferences.ShortcutKeys holds two alternative combos per shortcut
# (KeyCombination / KeyCombination2), up to three keys each. The first one,
# normally a keyboard key, is kept; the second one becomes the pad combo.
# Mesen ignores a shortcut while a superset combo is held
# (ShortcutKeyHandler.cpp), so L1 + L3 does not rewind, as long as L1 is
# pressed first; pressing L3 first rewinds until L1 joins it.
L1, R1, L3, R3 = 9, 10, 7, 8
PAD_SHORTCUTS = (
    ("FastForward", (R3,), "R3 (hold)"),
    ("Rewind", (L3,), "L3 (hold)"),
    ("SaveState", (L1, L3), "L1 + L3"),
    ("LoadState", (R1, R3), "R1 + R3"),
)

# Config paths (console, port) per player
PLAYER_PORTS = [
    [("Nes", "Port1"), ("Snes", "Port1"), ("Gameboy", "Controller")],
    [("Nes", "Port2"), ("Snes", "Port2")],
]
# Port Type written when player 2's port is empty (UI/Interop ControllerType)
PAD_TYPE = {"Nes": "NesController", "Snes": "SnesController"}
MAPPINGS = ("Mapping1", "Mapping2", "Mapping3", "Mapping4")

_SDL_PATTERNS = ("SDL3.dll", "SDL2.dll", "libSDL3*.so*", "libSDL2*.so*")


def _is_xinput_code(value):
    return isinstance(value, int) and XINPUT_BASE <= value < XINPUT_BASE + XINPUT_SLOTS * 0x100


def _mappings(config, player):
    """Every KeyMapping dict of one player's ports."""
    for console, port in PLAYER_PORTS[player]:
        cfg = (config.get(console) or {}).get(port)
        if isinstance(cfg, dict):
            for name in MAPPINGS:
                if isinstance(cfg.get(name), dict):
                    yield cfg[name]


def _has_xinput(cfg):
    return any(_is_xinput_code(v) for name in MAPPINGS
               if isinstance(cfg.get(name), dict) for v in cfg[name].values())


def _fill_from_player1(config, player):
    """
    Give each of `player`'s ports that has no XInput mapping a copy of the
    XInput mappings of the same console's player 1 port. Returns the
    consoles filled.
    """
    source = dict(PLAYER_PORTS[0])
    filled = []
    for console, port in PLAYER_PORTS[player]:
        section = config.get(console)
        if not isinstance(section, dict) or not isinstance(section.get(source.get(console)), dict):
            continue
        src = section[source[console]]
        if not _has_xinput(src):
            continue
        cfg = section.setdefault(port, {})
        if not isinstance(cfg, dict):
            continue
        if cfg.get("Type") in (None, "None") and console in PAD_TYPE:
            cfg["Type"] = PAD_TYPE[console]
        if _has_xinput(cfg):
            continue
        for name in MAPPINGS:
            if isinstance(src.get(name), dict) and any(_is_xinput_code(v) for v in src[name].values()):
                cfg[name] = json.loads(json.dumps(src[name]))
        filled.append(console)
    return filled


def _retarget(config, player, slot_for):
    """
    Rewrite the XInput codes of one player's ports. `slot_for(old_slot)`
    returns the new slot, or None to keep the code. Returns the count.
    """
    changed = 0
    for mapping in _mappings(config, player):
        for key, value in mapping.items():
            if _is_xinput_code(value):
                new = slot_for((value - XINPUT_BASE) >> 8)
                if new is not None:
                    mapping[key] = XINPUT_BASE + new * 0x100 + (value & 0xFF)
                    changed += 1
    return changed


class Mesen(Emulator):
    """Mesen 2, used for NES, SNES, Game Boy and Game Boy Color."""

    name = "Mesen"
    max_players = 2

    def __init__(self):
        super().__init__()
        self.base = None
        self.backend = "SDL3"
        self.lib_dir = None

    def locate(self, base):
        self.base = base
        self.dir = read_path_override(base, self.name) or base

        candidates = [os.path.join(self.dir, n) for n in EXE_NAMES]
        self.exe = next((c for c in candidates if os.path.exists(c)), None)
        if not self.exe:
            fatal(
                "Mesen Missing",
                f"Could not find {EXE_NAMES[0]} in:\n{self.dir}\n\n"
                "Place MesenLauncher next to it, or write its folder "
                "in a MesenPath.config file.",
                "Mesen binary not found", self.dir
            )

        self.config_path = os.path.join(self.dir, "settings.json")
        if not os.path.exists(self.config_path):
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    f.write("{}\n")
                log("INFO", "Portable mode enabled", self.config_path)
            except OSError as e:
                fatal("Mesen Portable Mode", f"Could not create:\n{self.config_path}\n\n{e}",
                      "Portable config creation failed", self.config_path)
        self.cwd = self.dir

    def log_dir(self):
        return os.path.join(self.dir, "logs")

    def prepare(self):
        self.lib_dir = next((d for d in (self.dir, self.base) if d and any(
            glob.glob(os.path.join(d, p)) for p in _SDL_PATTERNS)), None)
        if not self.lib_dir:
            fatal(
                "SDL Library Missing",
                "The launcher needs SDL to find each controller's XInput slot.\n\n"
                f"Place SDL3.dll next to Mesen:\n{self.dir}\n\n"
                "(SDL3.dll comes in the SDL3-<version>-win32-x64.zip release "
                "at github.com/libsdl-org/SDL/releases.)",
                "No SDL library found", self.dir
            )
        self.backend = "SDL3" if glob.glob(os.path.join(self.lib_dir, "*SDL3*")) else "SDL2"
        log("INFO", f"{self.backend} library found in", self.lib_dir)

        self.env = os.environ.copy()
        # Mesen reads pads through XInput itself; SDL must open them through
        # its XInput driver to report the XInput slot as the player index
        for hint, value in (("SDL_JOYSTICK_RAWINPUT", "0"), ("SDL_XINPUT_ENABLED", "1"),
                            ("SDL_JOYSTICK_HIDAPI_XBOX", "0")):
            os.environ[hint] = value
            log("INFO", "SDL hint", f"{hint}={value}")

    def sdl_backend(self):
        return self.backend

    def sdl_dir(self):
        return self.lib_dir

    def _load(self):
        try:
            with open(self.config_path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception as e:
            log("EXCEPTION", "settings.json read failed", e)
            return None

    def load_profiles(self):
        config = self._load() or {}
        if not any(_is_xinput_code(v) for m in _mappings(config, 0) for v in m.values()):
            fatal(
                "Controller Setup Required",
                "No XInput controller mapping was found in Mesen.\n\n"
                "Open Mesen, go to Settings > Input, and on Player 1 of each "
                "console you use pick a preset such as \"Xbox Controller\" (or "
                "map an Xbox-style pad), then close Mesen.\n"
                "The launcher moves that mapping to the pad you assign.",
                "No XInput mapping found", self.config_path
            )
        return {DEFAULT_PROFILE: None}

    @staticmethod
    def _set_pad_shortcuts(config, slot):
        """Second combo of each PAD_SHORTCUTS entry, on player 1's pad."""
        shortcuts = (config.get("Preferences") or {}).get("ShortcutKeys")
        if not isinstance(shortcuts, list):
            log("WARNING", "No Preferences.ShortcutKeys in settings.json yet; "
                           "start Mesen once to create it", "pad shortcuts not set")
            return
        base = XINPUT_BASE + slot * 0x100
        for name, buttons, label in PAD_SHORTCUTS:
            entry = next((e for e in shortcuts
                          if isinstance(e, dict) and e.get("Shortcut") == name), None)
            if entry is None:
                entry = {"Shortcut": name, "KeyCombination": {"Key1": 0, "Key2": 0, "Key3": 0}}
                shortcuts.append(entry)
            keys = [base + b for b in buttons] + [0, 0, 0]
            entry["KeyCombination2"] = {"Key1": keys[0], "Key2": keys[1], "Key3": keys[2]}
            log("INFO", f"Shortcut: {name} = {label} on XInput slot", str(slot))

    def write_input_config(self, assignments, hardware):
        config = self._load()
        if config is None:
            return
        pads = {h["path"]: h for h in hardware}

        slots = {}   # player -> XInput slot
        player = 0
        for a in assignments:
            hw = pads.get(a["path"])
            if not hw or player >= len(PLAYER_PORTS):
                continue
            slot = hw.get("player_index", -1)
            if hw["guid"].lower()[28:30] != XINPUT_DRIVER or not 0 <= slot < XINPUT_SLOTS:
                log("WARNING", f"Player {player+1}: not an XInput pad, Mesen cannot be "
                               "told which one it is - mapping left unchanged", hw["name"])
            else:
                slots[player] = slot
                if player > 0:
                    filled = _fill_from_player1(config, player)
                    if filled:
                        log("INFO", f"Player {player+1}: no XInput mapping, copied Player 1's for",
                            ", ".join(filled))
                changed = _retarget(config, player, lambda old, s=slot: s)
                log("INFO", f"Saving -> Player {player+1} | {hw['name']} | XInput slot {slot} | {changed} keys")
            player += 1

        # A player left unassigned must not keep pointing at a pad that now
        # belongs to someone else: move it to a slot nobody was given
        taken = set(slots.values())
        free = [s for s in range(XINPUT_SLOTS) if s not in taken]
        for p in range(len(PLAYER_PORTS)):
            if p in slots or not free:
                continue
            spare = free[0]
            moved = _retarget(config, p, lambda old: spare if old in taken else None)
            if moved:
                log("INFO", f"Player {p+1} unassigned: moved off assigned pads to slot", str(spare))

        if 0 in slots:
            self._set_pad_shortcuts(config, slots[0])

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log("EXCEPTION", "settings.json write failed, Mesen will use the old config", e)
