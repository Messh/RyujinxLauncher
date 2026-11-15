"""
DuckStation emulator package. Depends on Core only.

    DuckStation.py - the adapter Core talks to (portable.txt, SDL3, hints)
    Config.py      - settings.ini [PadN] sections, multitap, SDL-N ids
"""

from .DuckStation import DuckStation

__all__ = ["DuckStation"]
