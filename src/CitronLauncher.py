"""
Citron Launcher
Controller-first launcher for Citron, built on the shared Core engine: assign
pads to Player 1-8 with a gamepad, pick a controller profile per player, then
launch. Citron always runs from its own portable user/ folder.

Build:  ./build.sh Citron   |   build.bat Citron

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from Citron import Citron

if __name__ == "__main__":
    run(Citron())
