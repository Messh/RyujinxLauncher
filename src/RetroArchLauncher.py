"""
RetroArch Launcher
Controller-first launcher for RetroArch (FinalBurn Neo core), built on the
shared Core engine: assign pads to players with a gamepad, then launch.
RetroArch always runs with the retroarch.cfg next to its exe, never from
%APPDATA%.

Build:  ./build.sh RetroArch   |   build.bat RetroArch

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from RetroArch import RetroArch

if __name__ == "__main__":
    run(RetroArch())
