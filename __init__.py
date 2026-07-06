# SPDX-License-Identifier: GPL-3.0-or-later
bl_info = {
    "name": "muSCADier",
    "author": "Emanuele Lovato",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "File > Import > SCAD (.scad) muSCADier | View3D > N-panel > SCAD",
    "description": "Import OpenSCAD (.scad) files as native Blender geometry, colors included",
    "doc_url": "https://github.com/BiNeurale/muSCADier",
    "tracker_url": "https://github.com/BiNeurale/muSCADier/issues",
    "category": "Import-Export",
}

import bpy

from . import preferences, operators, panels, live


_classes = (
    preferences.SCADPreferences,
    operators.SCAD_OT_import,
    operators.SCAD_OT_reimport,
    operators.SCAD_OT_import_example,
    operators.SCAD_OT_cancel,
    operators.SCAD_OT_download_nightly,
    panels.SCAD_PT_panel,
)


def _menu_import(self, context):
    self.layout.operator(operators.SCAD_OT_import.bl_idname, text="SCAD (.scad) muSCADier")


def register():
    panels.register()
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.types.Scene.scad_last_file = bpy.props.StringProperty(
        name="Last SCAD file",
        subtype='FILE_PATH',
        default="",
    )
    bpy.types.Scene.scad_last_status = bpy.props.StringProperty(
        name="Status",
        default="",
    )
    bpy.types.Scene.scad_last_error = bpy.props.StringProperty(
        name="Last error",
        default="",
    )
    bpy.types.Scene.scad_live = bpy.props.BoolProperty(
        name="Live",
        description="Recompile and re-import whenever the .scad files are saved",
        default=False,
    )
    bpy.types.WindowManager.scad_cancel = bpy.props.BoolProperty(
        name="Cancel SCAD compilation",
        default=False,
        options={'SKIP_SAVE'},
    )
    live.start()


def unregister():
    live.stop()
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.scad_last_file
    del bpy.types.Scene.scad_last_status
    del bpy.types.Scene.scad_last_error
    del bpy.types.Scene.scad_live
    del bpy.types.WindowManager.scad_cancel
    panels.unregister()


if __name__ == "__main__":
    register()
