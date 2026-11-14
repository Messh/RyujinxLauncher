"""
Nextendo Launcher
Controller-first launcher for Ryujinx-Nextendo, built on the same Core engine
as RyujinxLauncher: assign pads to Player 1-8 with a gamepad, pick a
controller profile per player, then launch.

Nextendo always runs from its own portable data folder, so its Config.json
never collides with an official Ryujinx install.

Build:  ./build.sh Nextendo   |   build.bat Nextendo

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from Nextendo import Nextendo

if __name__ == "__main__":
    run(Nextendo())
