"""
Eden emulator package.

Implements the Core.Emulator contract for Eden (yuzu fork):
    Eden.py    - the adapter Core talks to (paths, SDL backend, AppImage)
    Config.py  - qt-config.ini [Controls] reader/writer, input profiles, GUID
"""

from .Eden import Eden

__all__ = ["Eden"]
