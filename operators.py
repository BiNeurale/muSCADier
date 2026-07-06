# SPDX-License-Identifier: GPL-3.0-or-later
import atexit
import os
import tempfile
import threading
import time

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from . import importer_3mf, live
from .preferences import get_prefs
from .utils import (
    compilation_result,
    download_nightly,
    download_supported,
    extract_errors,
    openscad_capabilities,
    output_extension,
    parse_deps,
    prepare_scad_compat,
    read_log,
    resolve_openscad,
    run_openscad,
    start_openscad,
    terminate_process,
)

# Custom property used to tag the objects created by an import, so a re-import
# removes exactly those and never touches the user's own geometry.
SOURCE_TAG = "muscadier_source"

_compiling = False
_download_state = None


def is_compiling():
    return _compiling


def download_state():
    return _download_state


# ---------------------------------------------------------------------------
# Safety net: if Blender quits while a compilation is running, kill the process
# and remove the temp files it left behind.
# ---------------------------------------------------------------------------
_live_procs = set()
_live_tempfiles = set()


def _atexit_cleanup():
    for proc in list(_live_procs):
        terminate_process(proc)
    for path in list(_live_tempfiles):
        try:
            os.unlink(path)
        except OSError:
            pass


atexit.register(_atexit_cleanup)


def _import_stl(stl_path):
    """Import an STL through whichever API this Blender exposes (4.2+ or legacy)."""
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=stl_path)
    else:
        bpy.ops.import_mesh.stl(filepath=stl_path)


def _redraw_view3d(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def _remove_previous(scad_path):
    """Clean re-import: remove only the objects a previous import of this file created."""
    source = os.path.normpath(scad_path)
    for obj in list(bpy.data.objects):
        if obj.get(SOURCE_TAG) != source:
            continue
        mesh = obj.data if obj.type == 'MESH' else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def _report_error(context, report, message, details=""):
    """Surface an error everywhere: popup, panel (red box) and status line."""
    context.scene.scad_last_error = (details or message)[:1000]
    context.scene.scad_last_status = message[:500]
    report({'ERROR'}, message)
    return {'CANCELLED'}


def _errors_from_log(log):
    """First readable error line + a few lines of detail from the OpenSCAD log."""
    lines = extract_errors(log)
    if lines:
        first = next((r for r in lines if r.startswith("ERROR")), lines[0])
        return first, "\n".join(lines[:8])
    tail = log.splitlines()[-3:] if log else []
    return (tail[0] if tail else "unknown error"), "\n".join(tail)


def _import_output(context, scad_path, out_path, report):
    """Import the compiled file (3MF with colors, or STL) and rename it after the source."""
    base_name = os.path.splitext(os.path.basename(scad_path))[0]
    _remove_previous(scad_path)

    if out_path.lower().endswith(".3mf"):
        try:
            created = importer_3mf.import_3mf(context, out_path, base_name)
        except Exception as e:
            return _report_error(context, report, f"3MF import failed: {e}")
    else:
        before = set(bpy.data.objects)
        _import_stl(out_path)
        created = [o for o in bpy.data.objects if o not in before]
        if len(created) == 1:
            created[0].name = base_name
            if created[0].data:
                created[0].data.name = base_name

    if not created:
        return _report_error(
            context, report,
            "No object generated: the SCAD file produces no geometry.")

    source = os.path.normpath(scad_path)
    for obj in created:
        obj[SOURCE_TAG] = source

    color_count = len({m.name for o in created for m in o.data.materials if m})
    context.scene.scad_last_file = scad_path
    context.scene.scad_last_error = ""
    report({'INFO'}, f"Imported: {base_name} ({len(created)} objects, {color_count} colors)")
    return {'FINISHED'}


def _legacy_note(compat_path, legacy_fixes):
    """Info (or warning) message describing the legacy-syntax fixes that were applied."""
    if not legacy_fixes:
        return None, None
    if compat_path:
        return 'INFO', "Legacy syntax auto-fixed: " + ", ".join(legacy_fixes)
    return 'WARNING', ("Legacy syntax detected but the folder is not writable: "
                       "geometry is likely incomplete "
                       "(" + ", ".join(legacy_fixes) + ")")


def _compile_and_import_sync(context, scad_path, report):
    """Synchronous path, used only in background mode (no UI)."""
    prefs = get_prefs(context)
    binary = resolve_openscad(prefs)
    caps = openscad_capabilities(binary)

    compile_path, compat_path, legacy_fixes = prepare_scad_compat(scad_path)
    with tempfile.NamedTemporaryFile(
            prefix="muscadier_", suffix=output_extension(caps), delete=False) as tf:
        out_path = tf.name
    try:
        ok, log = run_openscad(binary, compile_path, out_path, caps, prefs.compile_timeout)
        context.scene.scad_last_status = log[:500]
        if not ok:
            first, details = _errors_from_log(log)
            return _report_error(context, report, f"OpenSCAD: {first}", details)
        level, note = _legacy_note(compat_path, legacy_fixes)
        if note:
            report({level}, note)
        return _import_output(context, scad_path, out_path, report)
    finally:
        for path in (out_path, compat_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


class _CompileModalMixin:
    """Non-blocking OpenSCAD compilation: Popen + modal timer, cancellable with ESC."""

    _timer = None
    _proc = None
    _log_path = None
    _deps_path = None
    _out_path = None
    _scad_path = None
    _compat_path = None
    _legacy_fixes = ()
    _t0 = 0.0
    _timeout = 300

    def _start(self, context, scad_path):
        global _compiling
        if _compiling:
            self.report({'WARNING'}, "A compilation is already running: wait or cancel it.")
            return {'CANCELLED'}

        if bpy.app.background:
            return _compile_and_import_sync(context, scad_path, self.report)

        prefs = get_prefs(context)
        binary = resolve_openscad(prefs)
        caps = openscad_capabilities(binary)

        with tempfile.NamedTemporaryFile(
                prefix="muscadier_", suffix=output_extension(caps), delete=False) as tf:
            self._out_path = tf.name

        compile_path, self._compat_path, self._legacy_fixes = prepare_scad_compat(scad_path)
        proc, log_or_error, deps_path = start_openscad(binary, compile_path, self._out_path, caps)
        if proc is None:
            self._cleanup_files()
            return _report_error(context, self.report, log_or_error)

        self._proc = proc
        self._log_path = log_or_error
        self._deps_path = deps_path
        self._scad_path = scad_path
        self._timeout = prefs.compile_timeout
        self._t0 = time.monotonic()

        _live_procs.add(proc)
        for path in (self._out_path, self._log_path, self._deps_path, self._compat_path):
            if path:
                _live_tempfiles.add(path)

        _compiling = True
        context.window_manager.scad_cancel = False
        context.window_manager.progress_begin(0, 100)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        self._update_status(context, 0)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC' or context.window_manager.scad_cancel:
            self._close(context)
            context.scene.scad_last_status = "Compilation cancelled."
            self.report({'WARNING'}, "Compilation cancelled.")
            return {'CANCELLED'}

        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        elapsed = time.monotonic() - self._t0
        rc = self._proc.poll()

        if rc is None:
            if elapsed > self._timeout:
                self._close(context)
                return _report_error(
                    context, self.report,
                    f"OpenSCAD compilation timed out ({self._timeout}s). "
                    "Raise the timeout in the add-on preferences.")
            self._update_status(context, elapsed)
            return {'RUNNING_MODAL'}

        log = read_log(self._log_path)
        ok, message = compilation_result(rc, log, self._out_path)
        context.scene.scad_last_status = message[:500]

        if not ok:
            self._close(context)
            first, details = _errors_from_log(log)
            return _report_error(context, self.report, f"OpenSCAD: {first}", details)

        level, note = _legacy_note(self._compat_path, self._legacy_fixes)
        if note:
            context.scene.scad_last_status = (note + "\n" + message)[:500]
            self.report({level}, note)

        deps = parse_deps(self._deps_path, os.path.dirname(self._scad_path))
        if self._compat_path:
            compat = os.path.normpath(self._compat_path)
            deps = [self._scad_path if p == compat else p for p in deps]
        result = _import_output(context, self._scad_path, self._out_path, self.report)
        if 'FINISHED' in result:
            live.register_deps(self._scad_path, deps)
        self._close(context)
        return result

    def cancel(self, context):
        self._close(context)

    def _update_status(self, context, elapsed):
        msg = f"Compiling with OpenSCAD... {int(elapsed)}s"
        context.scene.scad_last_status = msg
        context.workspace.status_text_set(f"muSCADier: {msg} — press ESC to cancel")
        context.window_manager.progress_update(min(99, int(elapsed * 100 / self._timeout)))
        _redraw_view3d(context)

    def _close(self, context):
        global _compiling
        _compiling = False
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.window_manager.progress_end()
        context.workspace.status_text_set(None)
        _live_procs.discard(self._proc)
        terminate_process(self._proc)
        self._proc = None
        self._cleanup_files()
        _redraw_view3d(context)

    def _cleanup_files(self):
        for path in (self._out_path, self._log_path, self._deps_path, self._compat_path):
            if path:
                _live_tempfiles.discard(path)
                try:
                    os.unlink(path)
                except OSError:
                    pass
        self._out_path = None
        self._log_path = None
        self._deps_path = None
        self._compat_path = None


class SCAD_OT_import(_CompileModalMixin, bpy.types.Operator, ImportHelper):
    """Import a SCAD file (.scad), compiling it through the OpenSCAD CLI"""
    bl_idname = "scad.import_scad"
    bl_label = "Import SCAD"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".scad"
    filter_glob: StringProperty(default="*.scad", options={'HIDDEN'})

    def execute(self, context):
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "No file selected.")
            return {'CANCELLED'}
        return self._start(context, self.filepath)


class SCAD_OT_reimport(_CompileModalMixin, bpy.types.Operator):
    """Recompile and re-import the last loaded .scad file"""
    bl_idname = "scad.reimport"
    bl_label = "Re-import SCAD"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.scad_last_file) and os.path.isfile(context.scene.scad_last_file)

    def execute(self, context):
        return self._start(context, context.scene.scad_last_file)


class SCAD_OT_import_example(_CompileModalMixin, bpy.types.Operator):
    """Import the bundled example: a parametric nutmeg tree (Myristica fragrans)"""
    bl_idname = "scad.import_example"
    bl_label = "Import Example"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        example = os.path.join(os.path.dirname(__file__), "muSCADier.scad")
        if not os.path.isfile(example):
            self.report({'ERROR'}, "Bundled example not found.")
            return {'CANCELLED'}
        return self._start(context, example)


class SCAD_OT_cancel(bpy.types.Operator):
    """Cancel the running OpenSCAD compilation"""
    bl_idname = "scad.cancel"
    bl_label = "Cancel compilation"

    @classmethod
    def poll(cls, context):
        return _compiling

    def execute(self, context):
        context.window_manager.scad_cancel = True
        return {'FINISHED'}


class SCAD_OT_download_nightly(bpy.types.Operator):
    """Download or update the OpenSCAD nightly (fast Manifold backend + colors).
Nothing is re-downloaded when the latest version is already installed"""
    bl_idname = "scad.download_nightly"
    bl_label = "Download/update OpenSCAD nightly"

    _timer = None
    _thread = None

    @classmethod
    def poll(cls, context):
        return download_supported() and _download_state is None

    def execute(self, context):
        global _download_state
        binary = resolve_openscad(get_prefs(context))
        version = openscad_capabilities(binary)["version"] if binary else ""
        _download_state = {"percent": 0, "phase": "Starting...",
                           "installed_version": version}
        self._thread = threading.Thread(
            target=download_nightly, args=(_download_state,), daemon=True)
        self._thread.start()
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        global _download_state
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        state = _download_state
        error, result = state.get("error"), state.get("result")

        if error is None and result is None:
            percent = state.get("percent", 0)
            msg = f"{state.get('phase', '')} {percent}%" if percent else state.get("phase", "")
            context.scene.scad_last_status = msg
            context.workspace.status_text_set(f"muSCADier: {msg}")
            _redraw_view3d(context)
            return {'RUNNING_MODAL'}

        up_to_date = state.get("up_to_date", False)
        self._close(context)
        _download_state = None
        if error:
            return _report_error(context, self.report, error)

        caps = openscad_capabilities(result)
        if up_to_date:
            msg = f"OpenSCAD nightly {caps['version']}: already up to date."
        else:
            prefs = get_prefs(context)
            if hasattr(prefs, "bl_idname"):
                prefs.openscad_path = result
            msg = f"OpenSCAD nightly {caps['version']} ready (Manifold + colors)."
        context.scene.scad_last_status = msg
        self.report({'INFO'}, msg)
        return {'FINISHED'}

    def cancel(self, context):
        self._close(context)
        global _download_state
        _download_state = None

    def _close(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.workspace.status_text_set(None)
        _redraw_view3d(context)
