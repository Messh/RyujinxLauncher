"""
Mesen Launcher
Controller-first launcher for Mesen 2, built on the shared Core engine:
assign pads to players with a gamepad, then launch. Mesen 2 always runs in
portable mode, never from %APPDATA% or Documents.

Build:  ./build.sh Mesen   |   build.bat Mesen

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from Mesen import Mesen

if __name__ == "__main__":
    run(Mesen())
