"""
Yuzu Launcher
Controller-first launcher for yuzu, built on the shared Core engine: assign
pads to Player 1-8 with a gamepad, pick a controller profile per player, then
launch. yuzu always runs from its own portable user/ folder.

Build:  ./build.sh Yuzu   |   build.bat Yuzu

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from Yuzu import Yuzu

if __name__ == "__main__":
    run(Yuzu())
