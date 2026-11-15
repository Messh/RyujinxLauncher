"""
Cemu/Cemu.py
The Cemu (Wii U) implementation of the Core.Emulator contract.
Depends on Core only, never on another emulator package.

Data folder (src/gui/wxgui/CemuApp.cpp, DeterminePaths):
    a "portable" folder next to Cemu.exe -> portable, config inside it;
    settings.xml next to Cemu.exe (pre-2.0 layout) -> portable in the exe dir;
    otherwise %APPDATA%\\Cemu. The launcher never lets that happen: it creates
    portable\\ when neither exists.

Input (src/input/InputManager.cpp, api/Controller*, ControllerFactory.cpp):
    <config>/controllerProfiles/controller0.xml .. controller7.xml, one per
    player, and named profiles controllerProfiles/<name>.xml:

    <emulated_controller>
      <type>Wii U GamePad</type>
      <controller>
        <api>XInput</api>         <uuid>0</uuid>          XInput user slot
        <api>SDLController</api>  <uuid>0_0300...</uuid>  <n>_<SDL GUID>, n =
                                                           index among pads
                                                           sharing that GUID
        <display_name>...</display_name>
        <mappings>...</mappings>  (no device inside; API-specific numbers)
      </controller>
    </emulated_controller>

At launch the pad block of each player's file (its own controllerN.xml, or a
chosen named profile) is pointed at the assigned pad: <uuid> and
<display_name> change, the type and mappings stay. An XInput block can only
take an XInput pad; an SDL block takes any pad. Other pad blocks in the same
file are dropped so a second pad does not also drive that player. Files of
players that are not assigned are left alone.

SDL: Cemu links SDL3 statically. The launcher loads an SDL3.dll and applies
Cemu's joystick hints so GUIDs and enumeration order match; GUIDs Cemu
already wrote are learned as a fallback.
"""

import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

from Core.Emulator import Emulator
from Core.Log import log, fatal
from Core.Paths import read_path_override

EXE_NAMES = ("Cemu.exe",) if sys.platform == "win32" else ("Cemu",)
DEFAULT_PROFILE = "RL Default"
MAX_PLAYERS = 8
GAMEPAD_TYPE = "Wii U GamePad"
PAD_APIS = ("SDLController", "XInput", "DirectInput", "WGIGamepad", "WGIRawController")
XINPUT_DRIVER = "78"          # SDL GUID byte 14 = 'x'
GUID_CACHE_FILE = "CemuLauncher-guids.json"

_SLOT_FILE_RE = re.compile(r"^controller\d+$", re.IGNORECASE)
_SDL_PATTERNS = ("SDL3.dll", "libSDL3*.so*", "libSDL3*.dylib")

# SDLControllerProvider::InitSDL()
CEMU_SDL_HINTS = {
    "SDL_JOYSTICK_RAWINPUT": "0",          # not set by Cemu: SDL3 default
    "SDL_JOYSTICK_HIDAPI_PS4": "1",
    "SDL_JOYSTICK_HIDAPI_PS5": "1",
    "SDL_JOYSTICK_HIDAPI_GAMECUBE": "1",
    "SDL_JOYSTICK_HIDAPI_SWITCH": "1",
    "SDL_JOYSTICK_HIDAPI_SWITCH2": "1",
    "SDL_JOYSTICK_HIDAPI_JOY_CONS": "1",
    "SDL_JOYSTICK_HIDAPI_STADIA": "1",
    "SDL_JOYSTICK_HIDAPI_STEAM": "1",
    "SDL_JOYSTICK_HIDAPI_LUNA": "1",
}


# ============================================================================
# GUID learning
# ============================================================================
def _signature(guid):
    guid = guid.lower()
    return guid[:4] + "0000" + guid[8:24] + "00000000"


class Cemu(Emulator):
    """Cemu (Wii U emulator)."""

    name = "Cemu"
    max_players = MAX_PLAYERS

    def __init__(self):
        super().__init__()
        self.base = None
        self.config_dir = None
        self.profiles_dir = None
        self.lib_dir = None

    # ------------------------------------------------------------------
    # 1. Where everything lives
    # ------------------------------------------------------------------
    def locate(self, base):
        self.base = base
        self.dir = read_path_override(base, self.name) or base

        candidates = [os.path.join(self.dir, n) for n in EXE_NAMES]
        self.exe = next((c for c in candidates if os.path.exists(c)), None)
        if not self.exe:
            fatal(
                "Cemu Missing",
                f"Could not find {EXE_NAMES[0]} in:\n{self.dir}\n\n"
                "Place CemuLauncher next to it, or write its folder "
                "in a CemuPath.config file.",
                "Cemu binary not found", self.dir
            )

        portable = os.path.join(self.dir, "portable")
        if os.path.isdir(portable):
            self.config_dir = portable
        elif os.path.exists(os.path.join(self.dir, "settings.xml")):
            self.config_dir = self.dir
        else:
            try:
                os.makedirs(portable, exist_ok=True)
                log("INFO", "Portable mode enabled", portable)
            except OSError as e:
                fatal("Cemu Portable Mode", f"Could not create:\n{portable}\n\n{e}",
                      "Portable folder creation failed", portable)
            self.config_dir = portable

        self.profiles_dir = os.path.join(self.config_dir, "controllerProfiles")
        self.config_path = os.path.join(self.profiles_dir, "controller0.xml")
        self.cwd = self.dir

    def log_dir(self):
        return os.path.join(self.config_dir, "logs")

    # ------------------------------------------------------------------
    # 2. Runtime setup
    # ------------------------------------------------------------------
    def prepare(self):
        self.lib_dir = next((d for d in (self.dir, self.base) if d and any(
            glob.glob(os.path.join(d, p)) for p in _SDL_PATTERNS)), None)
        if not self.lib_dir:
            fatal(
                "SDL3 Missing",
                "Cemu has SDL3 built in, so the launcher needs its own copy "
                "to read the controllers.\n\n"
                f"Place SDL3.dll next to Cemu.exe:\n{self.dir}\n\n"
                "(SDL3.dll comes in the SDL3-<version>-win32-x64.zip release "
                "at github.com/libsdl-org/SDL/releases.)",
                "SDL3 not found", self.dir
            )
        log("INFO", "SDL3 library found in", self.lib_dir)

        self.env = os.environ.copy()
        for hint, value in CEMU_SDL_HINTS.items():
            os.environ[hint] = value
            log("INFO", "SDL hint", f"{hint}={value}")

    def sdl_backend(self):
        return "SDL3"

    def sdl_dir(self):
        return self.lib_dir

    # ------------------------------------------------------------------
    # 3. Controller profiles
    # ------------------------------------------------------------------
    def load_profiles(self):
        """
        "RL Default" = each player's own controllerN.xml. Named profiles
        (controllerProfiles/<name>.xml) replace it for the chosen player.
        """
        if not os.path.exists(self.config_path) or not self._pad_block(self._parse(self.config_path)):
            fatal(
                "Controller Setup Required",
                "No controller mapping was found in Cemu.\n\n"
                "Open Cemu, go to Options > Input settings, set Controller 1 "
                "to a gamepad (SDLController or XInput API) and close it.\n"
                "The launcher moves that mapping to the pad you assign.",
                "No pad in controller0.xml", self.config_path
            )
        profiles = {DEFAULT_PROFILE: None}
        for path in sorted(glob.glob(os.path.join(self.profiles_dir, "*.xml"))):
            name = os.path.splitext(os.path.basename(path))[0]
            if not _SLOT_FILE_RE.match(name) and self._pad_block(self._parse(path)) is not None:
                profiles[name] = path
        log("INFO", "Profiles loaded", str(len(profiles)))
        return profiles

    @staticmethod
    def _parse(path):
        try:
            return ET.parse(path)
        except Exception as e:
            log("WARNING", "Unreadable controller XML", f"{path}: {e}")
            return None

    @staticmethod
    def _pad_blocks(tree):
        if tree is None:
            return []
        return [c for c in tree.getroot().findall("controller")
                if (c.findtext("api") or "").strip() in PAD_APIS]

    def _pad_block(self, tree):
        blocks = self._pad_blocks(tree)
        return blocks[0] if blocks else None

    # ------------------------------------------------------------------
    # 4. Writing the launch configuration
    # ------------------------------------------------------------------
    def write_input_config(self, assignments, hardware):
        pads = {h["path"]: h for h in hardware}
        known = self._known_guids()

        # Cemu's <n> counts pads sharing a GUID in SDL_GetGamepads order
        cemu_ids = {}
        counters = {}
        for hw in hardware:
            guid = self._cemu_guid(hw["guid"], known)
            cemu_ids[hw["path"]] = f"{counters.get(guid, 0)}_{guid}"
            counters[guid] = counters.get(guid, 0) + 1

        player = 0
        for a in assignments:
            hw = pads.get(a["path"])
            if not hw or player >= MAX_PLAYERS:
                continue
            self._write_player(player, a["profile_key"], hw, cemu_ids[hw["path"]])
            player += 1

    def _write_player(self, player, profile_key, hw, sdl_uuid):
        target = os.path.join(self.profiles_dir, f"controller{player}.xml")
        source = self.profiles[profile_key] or target
        if not os.path.exists(source):
            first = os.path.join(self.profiles_dir, "controller0.xml")
            tree = self._parse(first)
            if tree is None or (tree.getroot().findtext("type") or "").strip() == GAMEPAD_TYPE:
                log("WARNING", f"Player {player+1}: controller{player}.xml does not exist. "
                               f"Set up Controller {player+1} once in Cemu", target)
                return
            source = first

        tree = self._parse(source)
        blocks = self._pad_blocks(tree)
        if not blocks:
            log("WARNING", f"Player {player+1}: no gamepad block in", source)
            return
        block = blocks[0]
        api = (block.findtext("api") or "").strip()
        slot = hw.get("player_index", -1)

        if api == "XInput":
            if hw["guid"].lower()[28:30] != XINPUT_DRIVER or not 0 <= slot < 4:
                log("WARNING", f"Player {player+1}: the mapping uses the XInput API but "
                               f"{hw['name']} is not an XInput pad - left unchanged", source)
                return
            uuid, display = str(slot), f"Controller {slot + 1}"
        elif api == "SDLController":
            uuid, display = sdl_uuid, hw["name"]
        else:
            log("WARNING", f"Player {player+1}: API {api} cannot be pinned - left unchanged", source)
            return

        _set_text(block, "uuid", uuid)
        _set_text(block, "display_name", display)
        root = tree.getroot()
        for extra in blocks[1:]:
            root.remove(extra)

        log("INFO", f"Saving -> Player {player+1} | {hw['name']} | Profile: {profile_key} | "
                    f"{os.path.basename(target)} | {api} {uuid}")
        try:
            ET.indent(tree, space="\t")
        except AttributeError:
            pass
        try:
            tree.write(target, encoding="UTF-8", xml_declaration=True)
        except Exception as e:
            log("EXCEPTION", f"Could not write {target}", e)

    # ------------------------------------------------------------------
    # GUID learning (fallback when Cemu's SDL3 and the launcher's disagree)
    # ------------------------------------------------------------------
    def _cache_path(self):
        return os.path.join(self.profiles_dir, GUID_CACHE_FILE)

    def _known_guids(self):
        known = {}
        try:
            with open(self._cache_path(), "r", encoding="utf-8") as f:
                for guid in json.load(f).values():
                    known.setdefault(_signature(guid), []).append(guid.lower())
        except FileNotFoundError:
            pass
        except Exception as e:
            log("WARNING", "Ignoring unreadable GUID cache", e)
        for path in glob.glob(os.path.join(self.profiles_dir, "*.xml")):
            for block in self._pad_blocks(self._parse(path)):
                if (block.findtext("api") or "").strip() != "SDLController":
                    continue
                uuid = (block.findtext("uuid") or "").strip()
                guid = uuid.split("_", 1)[1].lower() if "_" in uuid else ""
                if len(guid) == 32 and guid not in known.setdefault(_signature(guid), []):
                    known[_signature(guid)].append(guid)
        return known

    def _cemu_guid(self, guid, known):
        guid = guid.lower()
        candidates = known.get(_signature(guid), [])
        if not candidates or guid in candidates:
            return guid
        learned = candidates[0]
        log("INFO", "Using Cemu's GUID", f"{guid} -> {learned}")
        try:
            with open(self._cache_path(), "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}
        cache[_signature(learned)] = learned
        try:
            with open(self._cache_path(), "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
        except Exception as e:
            log("WARNING", "Could not save GUID cache", e)
        return learned


def _set_text(parent, tag, text):
    node = parent.find(tag)
    if node is None:
        node = ET.SubElement(parent, tag)
    node.text = text
