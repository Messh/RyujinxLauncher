"""
melonDS emulator package. Depends on Core only.

    MelonDS.py - the adapter Core talks to (portable/ folder, SDL2, 1 player)
    Config.py  - [Instance0] JoystickID
    Toml.py    - line-preserving TOML key editor
"""

from .MelonDS import MelonDS

__all__ = ["MelonDS"]
