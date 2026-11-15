"""
Gopher64 Launcher
Controller-first launcher for gopher64, built on the shared Core engine:
assign pads to players with a gamepad, then launch. gopher64 always runs in
portable mode, never from %APPDATA% or Documents.

Build:  ./build.sh Gopher64   |   build.bat Gopher64

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from Gopher64 import Gopher64

if __name__ == "__main__":
    run(Gopher64())
