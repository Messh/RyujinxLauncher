"""
xemu emulator package. Depends on Core only.

    Xemu.py   - the adapter Core talks to (portable xemu.toml, 4 ports)
    Config.py - [input.bindings] GUID per port, GUID learning
    Toml.py   - line-preserving TOML key editor
"""

from .Xemu import Xemu

__all__ = ["Xemu"]
