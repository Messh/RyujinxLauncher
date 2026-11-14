"""
CitronNextendo Launcher
Controller-first launcher for CitronNextendo, built on the shared Core engine: assign
pads to Player 1-8 with a gamepad, pick a controller profile per player, then
launch. CitronNextendo always runs from its own portable user/ folder.

Build:  ./build.sh CitronNextendo   |   build.bat CitronNextendo

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from CitronNextendo import CitronNextendo

if __name__ == "__main__":
    run(CitronNextendo())
