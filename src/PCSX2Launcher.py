"""
PCSX2 Launcher
Controller-first launcher for PCSX2, built on the shared Core engine:
assign pads to players with a gamepad, then launch. PCSX2 always runs in
portable mode, never from %APPDATA% or Documents.

Build:  ./build.sh PCSX2   |   build.bat PCSX2

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from PCSX2 import PCSX2

if __name__ == "__main__":
    run(PCSX2())
