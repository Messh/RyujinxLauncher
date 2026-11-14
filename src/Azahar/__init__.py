"""
AzaharPlus emulator package. Depends on Core only.

    Azahar.py - the adapter Core talks to (portable-only user/ folder, 1 player)
    Config.py - qt-config.ini [Controls] profiles, GUID handling
"""

from .Azahar import Azahar

__all__ = ["Azahar"]
