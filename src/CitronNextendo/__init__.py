"""
Citron-Nextendo emulator package. Depends on Core only.

    CitronNextendo.py - the adapter Core talks to (portable-only user/ folder)
    Config.py         - qt-config.ini [Controls], input profiles, GUID handling
"""

from .CitronNextendo import CitronNextendo

__all__ = ["CitronNextendo"]
