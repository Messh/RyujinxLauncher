"""
BizHawk Launcher
Controller-first launcher for BizHawk (EmuHawk), used for Sega Mega Drive /
Genesis, built on the shared Core engine: assign pads to players with a
gamepad, then launch. BizHawk always keeps its config next to EmuHawk.exe.

Build:  ./build.sh BizHawk   |   build.bat BizHawk

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from BizHawk import BizHawk

if __name__ == "__main__":
    run(BizHawk())
