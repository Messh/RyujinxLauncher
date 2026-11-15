"""
MelonDS Launcher
Controller-first launcher for melonDS, built on the shared Core engine:
assign pads to players with a gamepad, then launch. melonDS always runs in
portable mode, never from %APPDATA% or Documents.

Build:  ./build.sh MelonDS   |   build.bat MelonDS

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from MelonDS import MelonDS

if __name__ == "__main__":
    run(MelonDS())
