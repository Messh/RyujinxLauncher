"""
Dolphin emulator package (GameCube). Depends on Core only.

    Dolphin.py - the adapter Core talks to (portable.txt, SDL3 hints)
    Config.py  - GCPadNew.ini [GCPadN], Dolphin.ini SIDevice, Hotkeys.ini
"""

from .Dolphin import Dolphin

__all__ = ["Dolphin"]
