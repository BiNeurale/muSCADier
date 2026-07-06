# SPDX-License-Identifier: GPL-3.0-or-later
import os

import bpy
import bpy.utils.previews

from . import operators
from .preferences import get_prefs
from .utils import addon_version, download_supported, openscad_capabilities, resolve_openscad

# Custom-icon collection for the welcome logo. Loaded lazily; the panel falls
# back to a built-in icon when the image is missing.
_previews = None


def _logo_icon():
    """icon_value for the bundled logo, or 0 (use the default icon parameter)."""
    global _previews
    if _previews is None:
        return 0
    if "logo" not in _previews:
        path = os.path.join(os.path.dirname(__file__), "icons", "muSCADier_logo.png")
        if not os.path.isfile(path):
            return 0
        _previews.load("logo", path, 'IMAGE')
    return _previews["logo"].icon_id


class SCAD_PT_panel(bpy.types.Panel):
    bl_idname = "SCAD_PT_panel"
    bl_label = "SCAD"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "SCAD"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text=f"muSCADier v{addon_version()}", icon='PLUGIN')

        self._engine_section(layout, context)
        layout.separator()

        if operators.is_compiling():
            box = layout.box()
            box.alert = True
            box.label(text=scene.scad_last_status or "Compiling...", icon='TIME')
            row = box.row()
            row.scale_y = 1.3
            row.operator("scad.cancel", text="Cancel", icon='CANCEL')
            return

        download = operators.download_state()
        if download is not None:
            box = layout.box()
            percent = download.get("percent", 0)
            text = download.get("phase", "Downloading...")
            box.label(text=f"{text} {percent}%" if percent else text, icon='IMPORT')
            return

        if not scene.scad_last_file:
            self._welcome(layout)

        self._current_file(layout, scene)
        layout.separator()

        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("scad.import_scad", text="Import SCAD...", icon='IMPORT')

        row = layout.row(align=True)
        row.scale_y = 1.1
        row.operator("scad.reimport", text="Re-import", icon='FILE_REFRESH')

        row = layout.row()
        row.enabled = bool(scene.scad_last_file)
        row.prop(scene, "scad_live", text="Live (recompile on save)",
                 icon='FILE_REFRESH' if scene.scad_live else 'PLAY')

        layout.separator()
        self._status(layout, scene)

    def _welcome(self, layout):
        box = layout.box()
        icon_id = _logo_icon()
        if icon_id:
            box.label(text="Welcome to muSCADier", icon_value=icon_id)
        else:
            box.label(text="Welcome to muSCADier", icon='PLUGIN')
        col = box.column(align=True)
        col.scale_y = 0.85
        col.label(text="Import OpenSCAD models as native")
        col.label(text="Blender geometry, colors included.")
        row = box.row()
        row.scale_y = 1.3
        row.operator("scad.import_example", text="Import Example", icon='MESH_MONKEY')

    def _current_file(self, layout, scene):
        col = layout.column(align=True)
        col.label(text="Current file:", icon='FILE')
        if scene.scad_last_file:
            box = col.box()
            box.label(text=os.path.basename(scene.scad_last_file))
        else:
            col.label(text="(none)")

    def _status(self, layout, scene):
        if scene.scad_last_error:
            box = layout.box()
            box.alert = True
            box.label(text="Error:", icon='CANCEL')
            for line in scene.scad_last_error.splitlines()[:8]:
                box.label(text=line[:80])
        else:
            col = layout.column(align=True)
            col.label(text="Status:", icon='INFO')
            if scene.scad_last_status:
                box = col.box()
                for line in scene.scad_last_status.splitlines()[:4]:
                    box.label(text=line[:80])
            else:
                col.label(text="(idle)")

    def _engine_section(self, layout, context):
        binary = resolve_openscad(get_prefs(context))
        caps = openscad_capabilities(binary)

        box = layout.box()
        if not binary:
            box.label(text="OpenSCAD not found", icon='ERROR')
        elif caps["color_3mf"]:
            box.label(text=f"Engine: nightly {caps['version']}", icon='CHECKMARK')
            box.label(text="Fast Manifold + colors", icon='COLOR')
        else:
            box.label(text=f"Engine: {caps['version'] or os.path.basename(binary)}", icon='ERROR')
            box.label(text="Slow, no colors")

        if not caps["color_3mf"] and download_supported():
            row = box.row()
            row.scale_y = 1.2
            row.operator("scad.download_nightly", text="Download nightly (100x)", icon='IMPORT')


def register():
    global _previews
    _previews = bpy.utils.previews.new()


def unregister():
    global _previews
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
