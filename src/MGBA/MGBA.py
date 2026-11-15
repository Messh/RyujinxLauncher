"""
MGBA/MGBA.py
The mGBA (Qt) implementation of the Core.Emulator contract.
Depends on Core only, never on another emulator package.

Data folder (src/core/config.c):
    portable.ini next to mGBA.exe means portable mode: config.ini lives next
    to the exe. Otherwise mGBA uses %APPDATA%\\mGBA. The launcher never lets
    that happen: it creates portable.ini when missing.

Input (src/platform/sdl/sdl-events.c, mSDLEventsLoadConfig / mSDLAttachPlayer):
    [gba.input.SDLC]
    device0=03000000...      preferred pad of player 1, as SDL's GUID string
    deviceSerial0=...        optional; compared only when both sides have one
    At start mGBA attaches the connected pad whose GUID string equals device0
    (falling back to the first unclaimed pad). Button bindings do not name a
    pad, so the launcher only writes device0 and drops deviceSerial0.

GBA is single player. Two identical pads share a GUID and cannot be told
apart.

SDL: mGBA uses SDL2 and sets no enumeration hints, so the launcher loads the
SDL2.dll shipped next to mGBA.exe with the same defaults. GUIDs mGBA already
wrote are learned as a fallback, in case the libraries still disagree.
"""

import glob
import json
import os
import re
import sys

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

EXE_NAMES = ("mGBA.exe",) if sys.platform == "win32" else ("mgba-qt", "mGBA")
SECTION = "gba.input.SDLC"
DEFAULT_PROFILE = "Default"
GUID_CACHE_FILE = "MGBALauncher-guids.json"

_SECTION_RE = re.compile(r"^\s*\[(.+)\]\s*$")
_GUID_RE = re.compile(r"\b([0-9A-Fa-f]{32})\b")
_SDL_PATTERNS = {
    "SDL2": ("SDL2.dll", "libSDL2*.so*", "libSDL2*.dylib"),
    "SDL3": ("SDL3.dll", "libSDL3*.so*", "libSDL3*.dylib"),
}


# ============================================================================
# INI (key=value) - line preserving
# ============================================================================
def _read_lines(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        return f.read().splitlines()


def _write_lines(path, lines):
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def _bounds(lines, section):
    start = None
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if start is None:
            if m and m.group(1).strip() == section:
                start = i + 1
        elif m:
            return start, i
    return (start, len(lines)) if start is not None else None


def _set(lines, section, key, value):
    """Set key=value in section (None removes the key)."""
    b = _bounds(lines, section)
    if not b:
        if value is None:
            return
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]", f"{key}={value}"]
        return
    for i in range(*b):
        if "=" in lines[i] and lines[i].split("=", 1)[0].strip() == key:
            if value is None:
                del lines[i]
            else:
                lines[i] = f"{key}={value}"
            return
    if value is not None:
        end = b[1]
        while end > b[0] and not lines[end - 1].strip():
            end -= 1
        lines.insert(end, f"{key}={value}")


# ============================================================================
# GUID learning (fallback when mGBA's SDL and the launcher's disagree)
# ============================================================================
def _signature(guid):
    guid = guid.lower()
    return guid[:4] + "0000" + guid[8:24] + "00000000"


def _known_guids(cache_path, lines):
    known = {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            for guid in json.load(f).values():
                known.setdefault(_signature(guid), []).append(guid.lower())
    except FileNotFoundError:
        pass
    except Exception as e:
        log("WARNING", "Ignoring unreadable GUID cache", e)
    for line in lines:
        for guid in _GUID_RE.findall(line):
            guid = guid.lower()
            if guid not in known.setdefault(_signature(guid), []):
                known[_signature(guid)].append(guid)
    return known


def _remember(cache_path, guid):
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    if cache.get(_signature(guid)) != guid:
        cache[_signature(guid)] = guid
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
        except Exception as e:
            log("WARNING", "Could not save GUID cache", e)


class MGBA(Emulator):
    """mGBA (Game Boy Advance emulator)."""

    name = "MGBA"
    max_players = 1

    def __init__(self):
        super().__init__()
        self.base = None
        self.backend = "SDL2"
        self.lib_dir = None

    def locate(self, base):
        self.base = base
        self.dir = read_path_override(base, self.name) or base

        candidates = [os.path.join(self.dir, n) for n in EXE_NAMES]
        self.exe = next((c for c in candidates if os.path.exists(c)), None)
        if not self.exe:
            fatal(
                "mGBA Missing",
                f"Could not find {EXE_NAMES[0]} in:\n{self.dir}\n\n"
                "Place MGBALauncher next to it, or write its folder "
                "in a MGBAPath.config file.",
                "mGBA binary not found", self.dir
            )

        marker = os.path.join(self.dir, "portable.ini")
        if not os.path.exists(marker):
            try:
                open(marker, "a").close()
                log("INFO", "Portable mode enabled", marker)
            except OSError as e:
                fatal("mGBA Portable Mode", f"Could not create:\n{marker}\n\n{e}",
                      "Portable marker creation failed", marker)

        self.config_path = os.path.join(self.dir, "config.ini")
        self.cwd = self.dir

    def log_dir(self):
        return os.path.join(self.dir, "logs")

    def prepare(self):
        self.backend, self.lib_dir = next(
            ((b, d) for b in ("SDL2", "SDL3") for d in (self.dir, self.base)
             if d and any(glob.glob(os.path.join(d, p)) for p in _SDL_PATTERNS[b])),
            ("SDL2", None))
        if not self.lib_dir:
            fatal(
                "SDL2 Missing",
                f"SDL2.dll was not found next to mGBA:\n{self.dir}\n\n"
                "The launcher needs SDL2 to read controller GUIDs the same "
                "way mGBA does. mGBA's release normally includes it.",
                "SDL2 not found", self.dir
            )
        log("INFO", f"{self.backend} library found in", self.lib_dir)
        # mGBA sets no enumeration hints; SDL's defaults apply to both
        self.env = os.environ.copy()

    def sdl_backend(self):
        return self.backend

    def sdl_dir(self):
        return self.lib_dir

    def load_profiles(self):
        return {DEFAULT_PROFILE: None}

    def write_input_config(self, assignments, hardware):
        if not assignments:
            return
        hw = next((h for h in hardware if h["path"] == assignments[0]["path"]), None)
        if not hw:
            return

        try:
            lines = _read_lines(self.config_path) if os.path.exists(self.config_path) else []
        except Exception as e:
            log("EXCEPTION", "Config read failed, mGBA will use the old config", e)
            return

        cache = os.path.join(self.dir, GUID_CACHE_FILE)
        guid = hw["guid"].lower()
        # With mGBA's own SDL2.dll the GUID is already mGBA's; learning could
        # only pick up a stale one. Learn only when another library was used.
        candidates = []
        if os.path.normcase(self.lib_dir) != os.path.normcase(self.dir):
            candidates = [g for g in _known_guids(cache, lines).get(_signature(guid), []) if g != guid]
        if candidates:
            log("INFO", "Using mGBA's GUID", f"{guid} -> {candidates[0]}")
            guid = candidates[0]
            _remember(cache, guid)

        log("INFO", f"Saving -> Player 1 | {hw['name']} | device0={guid}")
        _set(lines, SECTION, "device0", guid)
        _set(lines, SECTION, "deviceSerial0", None)

        try:
            _write_lines(self.config_path, lines)
        except Exception as e:
            log("EXCEPTION", "Config write failed, mGBA will use the old config", e)
