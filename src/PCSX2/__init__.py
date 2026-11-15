"""
PCSX2 emulator package. Depends on Core only.

    PCSX2.py  - the adapter Core talks to (portable.ini, SDL3, hints)
    Config.py - inis/PCSX2.ini [PadN] sections, multitap, SDL-N ids
"""

from .PCSX2 import PCSX2

__all__ = ["PCSX2"]
