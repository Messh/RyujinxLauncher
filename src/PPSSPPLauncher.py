"""
PPSSPP Launcher
Controller-first launcher for PPSSPP, built on the shared Core engine:
assign pads to players with a gamepad, then launch. PPSSPP always runs in
portable mode, never from %APPDATA% or Documents.

Build:  ./build.sh PPSSPP   |   build.bat PPSSPP

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from PPSSPP import PPSSPP

if __name__ == "__main__":
    run(PPSSPP())
