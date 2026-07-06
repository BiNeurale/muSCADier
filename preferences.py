# SPDX-License-Identifier: GPL-3.0-or-later
import os

import bpy
from bpy.props import StringProperty, IntProperty

from .utils import (
    download_supported,
    invalidate_openscad_cache,
    openscad_capabilities,
    resolve_openscad,
)


def _on_path_changed(self, context):
    invalidate_openscad_cache()


class SCADPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    openscad_path: StringProperty(
        name="OpenSCAD path",
        description="Path to the OpenSCAD executable "
                    "(empty = automatic: downloaded nightly, then system)",
        subtype='FILE_PATH',
        default="",
        update=_on_path_changed,
    )

    compile_timeout: IntProperty(
        name="Timeout (s)",
        description="Maximum time allowed for an OpenSCAD compilation",
        default=300,
        min=5,
        max=3600,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "openscad_path")
        layout.prop(self, "compile_timeout")

        set_path = (self.openscad_path or "").strip()
        if set_path and set_path != "openscad" and not os.path.isfile(set_path):
            layout.label(text="The path above does not exist; using the fallback.",
                         icon='ERROR')

        binary = resolve_openscad(self)
        if binary:
            caps = openscad_capabilities(binary)
            extra = " - Manifold + colors" if caps["color_3mf"] else " - SLOW, no colors"
            layout.label(text=f"In use: {binary} ({caps['version']}){extra}", icon='INFO')
        elif download_supported():
            layout.label(text="No OpenSCAD found: download the nightly below.", icon='ERROR')
        else:
            layout.label(text="No OpenSCAD found: install it and set the path above.",
                         icon='ERROR')
        if download_supported():
            layout.operator("scad.download_nightly", icon='IMPORT')


class _PrefsFallback:
    """Default values used when the add-on is not in the preferences collection."""
    def __init__(self):
        self.openscad_path = ""
        self.compile_timeout = 300


def get_prefs(context):
    addon = context.preferences.addons.get(__package__)
    if addon is not None and addon.preferences is not None:
        return addon.preferences
    return _PrefsFallback()
