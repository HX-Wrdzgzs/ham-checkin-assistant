"""PyInstaller runtime hook for relocatable PySide6 single-file builds.

PySide6's Python extension modules are collected below ``PySide6`` while
some Qt/ICU dependencies can be collected at the one-file extraction root.
Windows' safe DLL search rules do not always search both locations when a
dependent DLL is loaded from a nested directory.  Register both directories
before the application imports PySide6.
"""
from __future__ import annotations

import os
import sys


_DLL_DIRECTORY_HANDLES = []

if sys.platform == "win32" and getattr(sys, "frozen", False):
    _MEIPASS = os.fspath(getattr(sys, "_MEIPASS", ""))
    if _MEIPASS:
        _DLL_DIRECTORIES = (
            os.path.join(_MEIPASS, "PySide6"),
            _MEIPASS,
        )
        for _directory in _DLL_DIRECTORIES:
            if not os.path.isdir(_directory):
                continue
            try:
                # Keep the returned handles alive for the whole process.  If
                # they are discarded, Windows removes the registered path.
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(_directory))
            except (OSError, AttributeError):
                # PATH below is still useful on older/minimal Windows setups.
                pass

        _old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = os.pathsep.join(
            [*(_directory for _directory in _DLL_DIRECTORIES if os.path.isdir(_directory)), _old_path]
        )
