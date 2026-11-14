"""
Azahar Launcher
Controller-first launcher for AzaharPlus (3DS), built on the shared Core
engine: assign the pad for the single player with a gamepad, pick one of
Azahar's input profiles, then launch. Azahar always runs from its own
portable user/ folder.

Build:  ./build.sh Azahar   |   build.bat Azahar

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from Azahar import Azahar

if __name__ == "__main__":
    run(Azahar())
