"""
Core/Sdl.py
Late-binding loader for the SDL wrapper.

The wrapper module MUST NOT be imported at module scope anywhere: the SDL
python bindings resolve their shared library at import time, so the emulator
directory has to be published through environment variables first. The
emulator also decides which SDL major version to use, and that decision may
depend on the emulator's own version.

Ordering enforced by Core/Bootstrap.py:

    emulator.locate()   ->  emulator directory known
    emulator.prepare()  ->  emulator version known, child env snapshotted
    load_sdl()          ->  env published, wrapper imported     <- here
"""

import os

from .Log import log, fatal


def load_sdl(backend, lib_dir):
    """
    Publish the SDL search path and import the matching wrapper.

    Args:
        backend (str): "SDL2" or "SDL3".
        lib_dir (str | None): Directory holding the SDL shared library (normally
                       the emulator directory, which ships its own copy).
                       None lets the bindings search the system paths.

    Returns:
        type: The SDLManager class - the only SDL surface the rest of the
              launcher ever touches.

    Note:
        Both imports below are deliberately literal (not importlib) so
        PyInstaller can see them and bundle both wrappers.
    """
    if backend == "SDL2":
        log("INFO", "SDL backend", "SDL2")
        log("INFO", "SDL2 path", lib_dir)
        if lib_dir:
            os.environ["PYSDL2_DLL_PATH"] = lib_dir
        from .ControllerManagerSDL2 import SDLManager
    else:
        log("INFO", "SDL backend", "SDL3")
        log("INFO", "SDL3 path", lib_dir)
        if lib_dir:
            os.environ["SDL_BINARY_PATH"] = lib_dir
        os.environ["SDL_DOWNLOAD_BINARIES"] = "0"       # Disable SDL Lib Download, "1" by default.
        os.environ["SDL_DISABLE_METADATA"] = "1"        # Disable metadata method, "0" by default.
        os.environ["SDL_CHECK_BINARY_VERSION"] = "0"    # Disable binary version checking, "1" by default.
        os.environ["SDL_IGNORE_MISSING_FUNCTIONS"] = "1" # Disable missing function warnings, "1" by default.
        os.environ["SDL_FIND_BINARIES"] = "1"           # Search system libraries, "1" by default.
        from .ControllerManagerSDL3 import SDLManager

        # With SDL_IGNORE_MISSING_FUNCTIONS, PySDL3 replaces every function of
        # a library it could not load with a stub, so a missing SDL3 would only
        # surface later as a cryptic "unimplemented function" - catch it here
        import sdl3
        if sdl3.SDL_GET_BINARY("SDL3") is None:
            fatal(
                "SDL3 Not Found",
                "Could not load the SDL3 library.\n\n"
                f"Searched in: {lib_dir or 'system paths'}\n\n"
                "Place SDL3.dll (libSDL3.so / libSDL3.dylib) next to the "
                "emulator, or install SDL3 on the system.",
                "SDL3 library not found", lib_dir
            )

    return SDLManager
