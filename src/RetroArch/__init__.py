"""
RetroArch emulator package (FinalBurn Neo). Depends on Core only.

    RetroArch.py - the adapter Core talks to (retroarch.cfg next to the exe,
                   SDL2 joypad driver, per-player joypad index and binds)
"""

from .RetroArch import RetroArch

__all__ = ["RetroArch"]
