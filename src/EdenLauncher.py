"""
Eden Launcher
Controller-first launcher for the Eden Switch emulator, built on the same
Core engine as RyujinxLauncher: assign pads to Player 1-8 with a gamepad,
pick a controller profile per player, then launch.

Build:  ./build.sh Eden   |   build.bat Eden

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from Eden import Eden

if __name__ == "__main__":
    run(Eden())
