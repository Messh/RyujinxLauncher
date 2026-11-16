"""
Dolphin Launcher
Controller-first launcher for Dolphin (GameCube), built on the shared Core
engine: assign pads to players with a gamepad, then launch. Dolphin always
runs in portable mode (portable.txt), never from Documents or %APPDATA%.

Build:  ./build.sh Dolphin   |   build.bat Dolphin

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from Dolphin import Dolphin

if __name__ == "__main__":
    run(Dolphin())
