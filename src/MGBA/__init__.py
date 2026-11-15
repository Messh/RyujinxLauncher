"""
mGBA emulator package. Depends on Core only.

    MGBA.py - adapter + config.ini [gba.input.SDLC] device0 GUID (portable.ini, 1 player)
"""

from .MGBA import MGBA

__all__ = ["MGBA"]
