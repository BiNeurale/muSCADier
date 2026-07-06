# SPDX-License-Identifier: GPL-3.0-or-later
import zipfile
import xml.etree.ElementTree as ET

import bpy
from mathutils import Matrix

_DEFAULT_COLOR = "#CCCCCC"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _parse_color(hex_str):
    """'#RRGGBB[AA]' -> linear RGBA for Blender; falls back to grey if malformed."""
    s = hex_str.lstrip("#")
    try:
        r, g, b = (int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        a = int(s[6:8], 16) / 255.0 if len(s) >= 8 else 1.0
    except (ValueError, IndexError):
        r = g = b = 0.8
        a = 1.0
    return (_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b), a)


def _parse_matrix(text):
    """3MF transform (12 values, row-major with translation on the last row) -> Matrix."""
    v = [float(x) for x in text.split()]
    return Matrix((
        (v[0], v[3], v[6], v[9]),
        (v[1], v[4], v[7], v[10]),
        (v[2], v[5], v[8], v[11]),
        (0.0, 0.0, 0.0, 1.0),
    ))


def _read_model(path_3mf):
    """Extract and parse the main 3D document from the 3MF."""
    with zipfile.ZipFile(path_3mf) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".model")]
        if not names:
            raise ValueError("3MF without a .model document")
        main = next((n for n in names if "3dmodel" in n.lower()), names[0])
        return ET.fromstring(z.read(main))


def _parse_resources(root):
    """Returns (color_groups: {pid: [hex, ...]}, objects: {id: dict})."""
    groups, objects = {}, {}
    resources = next((el for el in root if _local(el.tag) == "resources"), None)
    if resources is None:
        return groups, objects

    for el in resources:
        name = _local(el.tag)
        if name == "basematerials":
            groups[el.get("id")] = [
                b.get("displaycolor", _DEFAULT_COLOR)
                for b in el if _local(b.tag) == "base"
            ]
        elif name == "colorgroup":
            groups[el.get("id")] = [
                c.get("color", _DEFAULT_COLOR)
                for c in el if _local(c.tag) == "color"
            ]
        elif name == "object":
            objects[el.get("id")] = _parse_object(el)
    return groups, objects


def _parse_object(el):
    data = {"pid": el.get("pid"), "pindex": int(el.get("pindex") or 0),
            "mesh": None, "components": []}
    for child in el:
        name = _local(child.tag)
        if name == "mesh":
            data["mesh"] = _parse_mesh(child, data["pid"], data["pindex"])
        elif name == "components":
            for comp in child:
                if _local(comp.tag) == "component":
                    transform = comp.get("transform")
                    data["components"].append(
                        (comp.get("objectid"),
                         _parse_matrix(transform) if transform else Matrix.Identity(4)))
    return data


def _parse_mesh(el_mesh, pid_default, pindex_default):
    verts, tris, props = [], [], []
    for section in el_mesh:
        name = _local(section.tag)
        if name == "vertices":
            for v in section:
                verts.append((float(v.get("x")), float(v.get("y")), float(v.get("z"))))
        elif name == "triangles":
            for t in section:
                tris.append((int(t.get("v1")), int(t.get("v2")), int(t.get("v3"))))
                pid = t.get("pid") or pid_default
                p1 = t.get("p1")
                props.append((pid, int(p1) if p1 is not None else pindex_default))
    return verts, tris, props


def _material(color_hex):
    name = "SCAD_" + color_hex.lstrip("#").upper()
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat

    rgba = _parse_color(color_hex)
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat.use_nodes = True
    principled = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if principled is not None:
        principled.inputs["Base Color"].default_value = (*rgba[:3], 1.0)
        principled.inputs["Alpha"].default_value = rgba[3]
    if rgba[3] < 1.0:
        for attr, value in (("blend_method", 'BLEND'), ("surface_render_method", 'BLENDED')):
            try:
                setattr(mat, attr, value)
            except (AttributeError, TypeError):
                pass
    return mat


def _build_mesh(name, mesh_data, color_groups):
    verts, tris, props = mesh_data
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], tris)

    used_colors, slot_by_prop, indices = [], {}, []
    for prop in props:
        slot = slot_by_prop.get(prop)
        if slot is None:
            pid, p1 = prop
            palette = color_groups.get(pid, [])
            color = palette[p1] if p1 < len(palette) else _DEFAULT_COLOR
            slot = len(used_colors)
            used_colors.append(color)
            slot_by_prop[prop] = slot
        indices.append(slot)

    for color in used_colors:
        mesh.materials.append(_material(color))
    if indices and len(indices) == len(mesh.polygons):
        mesh.polygons.foreach_set("material_index", indices)
    mesh.validate()
    mesh.update()
    return mesh


def _instantiate(obj_id, objects, color_groups, name, collection, matrix, created):
    data = objects.get(obj_id)
    if data is None:
        return
    if data["mesh"]:
        mesh = _build_mesh(name, data["mesh"], color_groups)
        obj = bpy.data.objects.new(name, mesh)
        obj.matrix_world = matrix
        collection.objects.link(obj)
        created.append(obj)
    for i, (comp_id, transform) in enumerate(data["components"]):
        suffix = f"{name}_{i}" if len(data["components"]) > 1 else name
        _instantiate(comp_id, objects, color_groups, suffix,
                     collection, matrix @ transform, created)


def import_3mf(context, path_3mf, base_name):
    """Import a 3MF (geometry + OpenSCAD colors) as Blender objects.

    Returns the list of created objects.
    """
    root = _read_model(path_3mf)
    color_groups, objects = _parse_resources(root)

    build = next((el for el in root if _local(el.tag) == "build"), None)
    items = []
    if build is not None:
        for item in build:
            if _local(item.tag) == "item":
                transform = item.get("transform")
                items.append((item.get("objectid"),
                              _parse_matrix(transform) if transform else Matrix.Identity(4)))
    if not items:
        items = [(oid, Matrix.Identity(4)) for oid in objects]

    created = []
    collection = context.collection
    for i, (obj_id, matrix) in enumerate(items):
        name = base_name if len(items) == 1 else f"{base_name}_{i}"
        _instantiate(obj_id, objects, color_groups, name, collection, matrix, created)

    for obj in created:
        obj.select_set(True)
    if created:
        context.view_layer.objects.active = created[0]
    return created
