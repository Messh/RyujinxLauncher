"""
yuzu emulator package. Depends on Core only.

    Yuzu.py   - the adapter Core talks to (portable-only user/ folder, AppImage)
    Config.py - qt-config.ini [Controls], input profiles, GUID handling
"""

from .Yuzu import Yuzu

__all__ = ["Yuzu"]
