"""
DuckStation Launcher
Controller-first launcher for DuckStation, built on the shared Core engine:
assign pads to players with a gamepad, then launch. DuckStation always runs in
portable mode, never from %APPDATA% or Documents.

Build:  ./build.sh DuckStation   |   build.bat DuckStation

Author: Artomos
License: CC BY-NC 4.0 (Attribution-NonCommercial)
"""

from Core.Bootstrap import run
from DuckStation import DuckStation

if __name__ == "__main__":
    run(DuckStation())
