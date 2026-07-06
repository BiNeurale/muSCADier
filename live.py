# SPDX-License-Identifier: GPL-3.0-or-later
import os
import time

import bpy

INTERVAL = 1.0
DEBOUNCE = 1.0

_deps = {}
_imported_signature = {}
_pending = None


def register_deps(scad_path, paths):
    """Store the file's dependencies (from OpenSCAD -d) and the imported signature."""
    key = os.path.normpath(scad_path)
    if paths:
        _deps[key] = paths
    _imported_signature[key] = _signature(key)


def _watched_files(scad_path):
    """Known dependencies, otherwise every .scad in the file's folder."""
    known = _deps.get(scad_path)
    if known:
        return known
    folder = os.path.dirname(scad_path)
    try:
        return [os.path.join(folder, n) for n in os.listdir(folder)
                if n.lower().endswith(".scad")]
    except OSError:
        return [scad_path]


def _signature(scad_path):
    """Signature of the watched files' state (max mtime + file count)."""
    mtimes = []
    for p in _watched_files(scad_path):
        try:
            mtimes.append(os.stat(p).st_mtime)
        except OSError:
            pass
    return (max(mtimes) if mtimes else 0.0, len(mtimes))


def _trigger_reimport():
    windows = bpy.context.window_manager.windows
    if not windows:
        return False
    with bpy.context.temp_override(window=windows[0]):
        try:
            bpy.ops.scad.reimport('EXEC_DEFAULT')
        except RuntimeError:
            return False
    return True


def live_timer():
    """Persistent timer: when Live is on, recompile whenever the .scad files are saved."""
    global _pending
    from . import operators

    scene = getattr(bpy.context, "scene", None)
    if (scene is None or not scene.scad_live or not scene.scad_last_file
            or operators.is_compiling()):
        _pending = None
        return INTERVAL

    key = os.path.normpath(bpy.path.abspath(scene.scad_last_file))
    if not os.path.isfile(key):
        return INTERVAL

    signature = _signature(key)
    if signature == _imported_signature.get(key):
        _pending = None
        return INTERVAL

    now = time.monotonic()
    if _pending is None or _pending[0] != signature:
        _pending = (signature, now)
        return INTERVAL

    if now - _pending[1] < DEBOUNCE:
        return INTERVAL

    _imported_signature[key] = signature
    _pending = None
    _trigger_reimport()
    return INTERVAL


def start():
    if not bpy.app.background and not bpy.app.timers.is_registered(live_timer):
        bpy.app.timers.register(live_timer, first_interval=INTERVAL, persistent=True)


def stop():
    if bpy.app.timers.is_registered(live_timer):
        bpy.app.timers.unregister(live_timer)
    _deps.clear()
    _imported_signature.clear()
