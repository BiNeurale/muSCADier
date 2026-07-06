"""Headless test suite for muSCADier. Run with:

    blender --background --factory-startup --python tests/test_addon.py -- [repo_dir]

The add-on sources are copied into a temporary `muscadier` package, imported,
registered, and exercised end to end (a trivial cube compiles instantly on any
OpenSCAD backend, so this suite needs only a system OpenSCAD).
"""
import os
import shutil
import sys
import tempfile
import zipfile

import bpy

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
REPO = os.path.abspath(ARGV[0]) if ARGV else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_fail = []
_pass = 0


def check(name, cond, extra=""):
    global _pass
    if cond:
        _pass += 1
        print(f"[PASS] {name}")
    else:
        _fail.append(name)
        print(f"[FAIL] {name} {extra}")


def make_package():
    """Copy the add-on sources into <tmp>/muscadier and put it on sys.path."""
    tmp = tempfile.mkdtemp(prefix="muscadier_test_")
    dest = os.path.join(tmp, "muscadier")
    os.makedirs(dest)
    for name in os.listdir(REPO):
        if name.endswith(".py") or name in ("blender_manifest.toml", "muSCADier.scad"):
            shutil.copy2(os.path.join(REPO, name), os.path.join(dest, name))
    sys.path.insert(0, tmp)
    return tmp


def write_3mf(path):
    """Write a minimal 3MF (colorgroup + 2 triangles) to exercise the importer."""
    model = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter"
       xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
       xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">
 <resources>
  <m:colorgroup id="1">
   <m:color color="#FF0000"/>
   <m:color color="#00FF00"/>
  </m:colorgroup>
  <object id="2" type="model" pid="1" pindex="0">
   <mesh>
    <vertices>
     <vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/>
     <vertex x="0" y="1" z="0"/><vertex x="0" y="0" z="1"/>
    </vertices>
    <triangles>
     <triangle v1="0" v2="1" v3="2" pid="1" p1="0"/>
     <triangle v1="0" v2="1" v3="3" pid="1" p1="1"/>
    </triangles>
   </mesh>
  </object>
 </resources>
 <build><item objectid="2"/></build>
</model>"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("3D/3dmodel.model", model)


def main():
    make_package()
    import muscadier
    from muscadier import utils, importer_3mf
    from muscadier.operators import SOURCE_TAG

    # 1. register / operators
    try:
        muscadier.register()
        reg_ok = True
    except Exception as e:
        reg_ok = False
        print("  register error:", e)
    check("register() without exceptions", reg_ok)
    for op in ("import_scad", "reimport", "import_example", "cancel", "download_nightly"):
        check(f"operator scad.{op} registered", hasattr(bpy.ops.scad, op))

    # 2. version from the manifest
    v = utils.addon_version()
    check("addon_version reads the manifest", v not in ("", "?"), f"(v={v})")

    # 3. system OpenSCAD detection + capabilities
    binary = utils.find_openscad()
    check("find_openscad finds a binary", bool(binary), f"(bin={binary})")
    caps = utils.openscad_capabilities(binary)
    check("openscad_capabilities returns a version", bool(caps["version"]), f"(caps={caps})")
    check("capabilities dict has all keys",
          set(caps) == {"version", "manifold", "color_3mf", "export_format"}, f"(caps={caps})")

    # 4. well-formed command line; binstl only when the binary supports --export-format
    cmd = utils._command(binary, "in.scad", "out.stl", {"export_format": True})
    check("STL command uses binstl when supported", "binstl" in cmd and cmd[-1] == "in.scad")
    cmd = utils._command(binary, "in.scad", "out.stl", {"export_format": False})
    check("STL command omits binstl on old OpenSCAD", "binstl" not in cmd and cmd[-1] == "in.scad")
    cmd = utils._command(binary, "in.scad", "out.3mf", {"manifold": True, "color_3mf": True})
    check("3MF command has backend + colors",
          "--backend=manifold" in cmd and any("export-3mf" in c for c in cmd))

    # 5. legacy syntax auto-fix (child/assign + dxf_*_extrude)
    legacy_dir = tempfile.mkdtemp()
    legacy = os.path.join(legacy_dir, "legacy.scad")
    with open(legacy, "w") as f:
        f.write("module m() { child(0); }\nassign(x=1) cube(x);\n"
                "dxf_linear_extrude(height=2) square(1);\n")
    _, compat, fixes = utils.prepare_scad_compat(legacy)
    check("legacy: detects child/assign/dxf", len(fixes) == 3 and compat is not None, f"(fixes={fixes})")
    if compat and os.path.isfile(compat):
        with open(compat) as f:
            patched = f.read()
        check("legacy: patch applied",
              "children(" in patched and "let(" in patched and "linear_extrude(" in patched)
        os.unlink(compat)

    # 6. dependency file parsing
    dtmp = tempfile.mkdtemp()
    a = os.path.join(dtmp, "a.scad")
    open(a, "w").close()
    deps_file = os.path.join(dtmp, "d.d")
    with open(deps_file, "w") as f:
        f.write(f"out.stl: {a} \\\n /does/not/exist.scad\n")
    deps = utils.parse_deps(deps_file, dtmp)
    check("parse_deps keeps only existing files", deps == [os.path.normpath(a)], f"(deps={deps})")

    # 7. error extraction (filter + shorten paths)
    log = "hello\nERROR: Parser error in file /home/x/y/model.scad line 3\nWARNING: foo"
    errors = utils.extract_errors(log)
    check("extract_errors filters and shortens paths",
          any(r.startswith("ERROR") and "/home/" not in r for r in errors), f"(errors={errors})")

    # 8. end-to-end import (trivial cube: instant on every backend)
    scad = os.path.join(tempfile.mkdtemp(), "cube_test.scad")
    with open(scad, "w") as f:
        f.write("cube([10,10,10]);\n")
    before = set(bpy.data.objects)
    res = bpy.ops.scad.import_scad('EXEC_DEFAULT', filepath=scad)
    created = [o for o in bpy.data.objects if o not in before]
    scad_err = bpy.context.scene.scad_last_error
    check("end-to-end import FINISHED", res == {'FINISHED'}, f"(res={res} err={scad_err})")
    check("import produces >=1 object", len(created) >= 1, f"(n={len(created)})")
    if created:
        total_v = sum(len(o.data.vertices) for o in created if o.type == 'MESH')
        check("imported object has geometry", total_v == 8, f"(verts={total_v})")
        check("object renamed after the file", any(o.name.startswith("cube_test") for o in created))
        check("imported objects are tagged with the source",
              all(o.get(SOURCE_TAG) == os.path.normpath(scad) for o in created))

    # 9. 3MF importer with colors
    mf = os.path.join(tempfile.mkdtemp(), "t.3mf")
    write_3mf(mf)
    try:
        created3 = importer_3mf.import_3mf(bpy.context, mf, "sample3mf")
        ok3 = len(created3) >= 1 and any(o.data.materials for o in created3)
        colors = {m.name for o in created3 for m in o.data.materials if m}
    except Exception as e:
        ok3 = False
        colors = set()
        print("  3mf error:", e)
    check("import_3mf creates a colored object", ok3, f"(colors={colors})")

    # 10. re-import removes only tagged objects, never the user's own geometry
    decoy = bpy.data.objects.new("cube_test", bpy.data.meshes.new("cube_test"))
    bpy.context.collection.objects.link(decoy)
    tagged_before = [o for o in bpy.data.objects if o.get(SOURCE_TAG) == os.path.normpath(scad)]
    res2 = bpy.ops.scad.reimport('EXEC_DEFAULT')
    tagged_after = [o for o in bpy.data.objects if o.get(SOURCE_TAG) == os.path.normpath(scad)]
    check("re-import does not duplicate imported objects",
          res2 == {'FINISHED'} and len(tagged_after) == len(tagged_before),
          f"(before={len(tagged_before)} after={len(tagged_after)})")
    check("re-import preserves the user's own object", decoy.name in bpy.data.objects)

    # 11. clean unregister
    try:
        muscadier.unregister()
        unreg_ok = True
    except Exception as e:
        unreg_ok = False
        print("  unregister error:", e)
    check("unregister() without exceptions", unreg_ok)

    print(f"\n=== RESULT: {_pass} PASS, {len(_fail)} FAIL ===")
    if _fail:
        print("FAILED:", ", ".join(_fail))
    sys.exit(1 if _fail else 0)


main()
