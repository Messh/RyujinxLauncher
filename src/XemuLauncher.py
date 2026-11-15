"""
Xemu Launcher
Controller-first launcher for xemu, built on the shared Core engine:
assign pads to players with a gamepad, then launch. xemu always runs in
portable mode, never from %APPDATA% or Documents.

Build:  ./build.sh Xemu   |   build.bat Xemu

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from Xemu import Xemu

if __name__ == "__main__":
    run(Xemu())
