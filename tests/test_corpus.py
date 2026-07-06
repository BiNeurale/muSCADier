"""Real-world corpus test: compile and import a range of .scad files, including
legacy syntax (child/assign) and multi-file include/use projects. Needs a
capable OpenSCAD (nightly with Manifold recommended). Run with:

    blender --background --factory-startup --python tests/test_corpus.py -- <repo> <openscad_bin> <corpus_dir>
"""
import os
import shutil
import sys
import tempfile
import time

import bpy

ARGV = sys.argv[sys.argv.index("--") + 1:]
REPO = os.path.abspath(ARGV[0])
OSCAD = ARGV[1]
CORPUS = os.path.abspath(ARGV[2])

tmp = tempfile.mkdtemp(prefix="muscadier_corpus_")
dest = os.path.join(tmp, "muscadier")
os.makedirs(dest)
for n in os.listdir(REPO):
    if n.endswith(".py") or n in ("blender_manifest.toml", "muSCADier.scad"):
        shutil.copy2(os.path.join(REPO, n), os.path.join(dest, n))
sys.path.insert(0, tmp)

from muscadier import utils, importer_3mf

# label -> path, relative to the corpus dir. Chosen to cover: standalone
# primitives, multi-file include/use, and removed legacy syntax (child/assign).
CASES = [
    ("standalone (nutmeg tree)", "noce_moscata_albero.scad"),
    ("multi-file include/use", "noce_moscata/main.scad"),
    ("legacy child() [Gear Bearing]", "Gear Bearing - 53451/files/bearing.scad"),
    ("legacy assign() [Music Box]", "Parametric Music Box - 53235/files/FullyPrintableParametricMusicBox.scad"),
    ("library use() [UB.scad Gears]", "UB.scad-main/examples/UBexamples/Gears.scad"),
    ("assembly include [drone v5_1]", "scad/99_assembly_v5_1.scad"),
]

caps = utils.openscad_capabilities(OSCAD)
print(f"OpenSCAD caps: {caps}\n")

fail = []
for label, rel in CASES:
    scad = os.path.join(CORPUS, rel)
    if not os.path.isfile(scad):
        print(f"[SKIP] {label} (missing: {rel})")
        continue

    compile_path, compat, fixes = utils.prepare_scad_compat(scad)
    out = os.path.join(tmp, "out" + utils.output_extension(caps))
    t0 = time.monotonic()
    ok, log = utils.run_openscad(OSCAD, compile_path, out, caps, timeout=180)
    dt = time.monotonic() - t0
    if compat:
        try:
            os.unlink(compat)
        except OSError:
            pass

    if not ok:
        print(f"[FAIL] {label}: compile failed ({dt:.1f}s)\n       {log[-200:]}")
        fail.append(label)
        continue

    try:
        if out.lower().endswith(".3mf"):
            created = importer_3mf.import_3mf(bpy.context, out, "corpus")
        else:
            before = set(bpy.data.objects)
            if hasattr(bpy.ops.wm, "stl_import"):
                bpy.ops.wm.stl_import(filepath=out)
            else:
                bpy.ops.import_mesh.stl(filepath=out)
            created = [o for o in bpy.data.objects if o not in before]
    except Exception as e:
        print(f"[FAIL] {label}: import raised {e}")
        fail.append(label)
        continue

    verts = sum(len(o.data.vertices) for o in created if o.type == 'MESH')
    colors = len({m.name for o in created for m in o.data.materials if m})
    tag = (" +legacy:" + ",".join(fixes)) if fixes else ""
    if created and verts > 0:
        print(f"[PASS] {label}: {len(created)} obj, {verts} verts, {colors} colors, {dt:.1f}s{tag}")
    else:
        print(f"[FAIL] {label}: no geometry ({dt:.1f}s){tag}")
        fail.append(label)

    for o in list(created):
        bpy.data.objects.remove(o, do_unlink=True)

print(f"\n=== CORPUS: {len(CASES) - len(fail)}/{len(CASES)} OK ===")
if fail:
    print("FAILED:", ", ".join(fail))
sys.exit(1 if fail else 0)
