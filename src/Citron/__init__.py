"""
Citron (nightly) emulator package. Depends on Core only.

    Citron.py - the adapter Core talks to (portable-only user/ folder)
    Config.py - qt-config.ini [Controls], input profiles, GUID handling
"""

from .Citron import Citron

__all__ = ["Citron"]
