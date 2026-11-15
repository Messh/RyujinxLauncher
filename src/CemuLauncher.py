"""
Cemu Launcher
Controller-first launcher for Cemu, built on the shared Core engine:
assign pads to players with a gamepad, then launch. Cemu always runs in
portable mode, never from %APPDATA% or Documents.

Build:  ./build.sh Cemu   |   build.bat Cemu

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from Cemu import Cemu

if __name__ == "__main__":
    run(Cemu())
