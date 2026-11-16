"""
BizHawk emulator package (Sega Mega Drive / Genesis). Depends on Core only.

    BizHawk.py - adapter + config.ini AllTrollers pad bindings (SDL2 device index, 2 players)
"""

from .BizHawk import BizHawk

__all__ = ["BizHawk"]
