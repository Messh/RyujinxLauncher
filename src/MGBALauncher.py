"""
MGBA Launcher
Controller-first launcher for mGBA, built on the shared Core engine:
assign pads to players with a gamepad, then launch. mGBA always runs in
portable mode, never from %APPDATA% or Documents.

Build:  ./build.sh MGBA   |   build.bat MGBA

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from MGBA import MGBA

if __name__ == "__main__":
    run(MGBA())
