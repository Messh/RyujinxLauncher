"""
Ryujinx-Nextendo emulator package. Depends on Core only, never on Ryujinx/.

Implements the Core.Emulator contract for Nextendo:
    Nextendo.py - the adapter Core talks to (portable-only data folder)
    Config.py   - Config.json template, profiles, GUID format, input writer
"""

from .Nextendo import Nextendo

__all__ = ["Nextendo"]
