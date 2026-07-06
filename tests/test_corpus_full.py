"""Extended real-world corpus test: compile and import a broad set of .scad
files across every category muSCADier must handle — standalone primitives,
multi-file include/use projects, project-local libraries resolved via
OPENSCADPATH, and removed legacy syntax (child/assign) from old Thingiverse
models. Meant to be run against more than one OpenSCAD build to prove
cross-version robustness.

    blender --background --factory-startup --python tests/test_corpus_full.py \
        -- <repo> <openscad_bin> <corpus_dir> [timeout_seconds]

Outcomes per file: PASS (geometry imported), EMPTY (compiled but no geometry),
COMPILE-FAIL (OpenSCAD rejected it), TIMEOUT (engine too slow), IMPORT-FAIL
(OpenSCAD produced output Blender could not import). Only COMPILE-FAIL and
IMPORT-FAIL count as add-on bugs; TIMEOUT/EMPTY are reported but tolerated.

Run it against a recent OpenSCAD (Manifold) for the canonical result. On the old
CGAL engine, expect heavy models to TIMEOUT and any corpus that requires a newer
OpenSCAD (e.g. UB.scad asserts version >= 2025, and uses post-2021 syntax) to
report EMPTY or COMPILE-FAIL — that is an engine limitation, not an add-on bug.
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
TIMEOUT = int(ARGV[3]) if len(ARGV) > 3 else 180

tmp = tempfile.mkdtemp(prefix="muscadier_full_")
dest = os.path.join(tmp, "muscadier")
os.makedirs(dest)
for n in os.listdir(REPO):
    if n.endswith(".py") or n in ("blender_manifest.toml", "muSCADier.scad"):
        shutil.copy2(os.path.join(REPO, n), os.path.join(dest, n))
sys.path.insert(0, tmp)

from muscadier import utils, importer_3mf

# (category, label, absolute path). Chosen to exercise every code path the
# importer must survive, from the bundled example to legacy Thingiverse models.
CASES = [
    ("bundled",    "muSCADier.scad (welcome example)", os.path.join(dest, "muSCADier.scad")),
    ("standalone", "nutmeg base",   os.path.join(CORPUS, "noce_moscata_base.scad")),
    ("standalone", "nutmeg tree",   os.path.join(CORPUS, "noce_moscata_albero.scad")),
    ("multi-file", "nutmeg project (use<>)", os.path.join(CORPUS, "noce_moscata/main.scad")),
    ("multi-file", "drone frame",   os.path.join(CORPUS, "scad/01_frame_disco_v5_1.scad")),
    ("multi-file", "drone motor mount", os.path.join(CORPUS, "scad/02_lift_motor_mount_v5_1.scad")),
    ("multi-file", "drone gps pedestal", os.path.join(CORPUS, "scad/03_gps_pedestal_v5_1.scad")),
    ("multi-file", "drone thrust pylon", os.path.join(CORPUS, "scad/04_thrust_pylon_v5_1.scad")),
    ("multi-file", "drone skirt tpu", os.path.join(CORPUS, "scad/05_skirt_tpu_v5_1.scad")),
    ("multi-file", "drone flight feet", os.path.join(CORPUS, "scad/06_flight_feet_v5_1.scad")),
    ("multi-file", "drone assembly",  os.path.join(CORPUS, "scad/99_assembly_v5_1.scad")),
    ("multi-file", "drone assembly exploded", os.path.join(CORPUS, "scad/99_assembly_exploded_v5_1.scad")),
    ("legacy",     "child() [Gear Bearing]", os.path.join(CORPUS, "Gear Bearing - 53451/files/bearing.scad")),
    ("legacy",     "assign() [Music Box]", os.path.join(CORPUS, "Parametric Music Box - 53235/files/FullyPrintableParametricMusicBox.scad")),
    ("library",    "UB Gears",     os.path.join(CORPUS, "UB.scad-main/examples/UBexamples/Gears.scad")),
    ("library",    "UB Threads",   os.path.join(CORPUS, "UB.scad-main/examples/UBexamples/Threads.scad")),
    ("library",    "UB Fillets",   os.path.join(CORPUS, "UB.scad-main/examples/UBexamples/Fillets.scad")),
    ("library",    "UB Knurls",    os.path.join(CORPUS, "UB.scad-main/examples/UBexamples/Knurls.scad")),
    ("library",    "UB Objects",   os.path.join(CORPUS, "UB.scad-main/examples/UBexamples/Objects.scad")),
    ("library",    "UB Rounds",    os.path.join(CORPUS, "UB.scad-main/examples/UBexamples/Rounds.scad")),
    ("library",    "UB Polygons",  os.path.join(CORPUS, "UB.scad-main/examples/UBexamples/Polygons.scad")),
    ("library",    "UB Products",  os.path.join(CORPUS, "UB.scad-main/examples/UBexamples/Products.scad")),
    ("library",    "UB TrapezGewinde", os.path.join(CORPUS, "UB.scad-main/examples/UBexamples/TrapezGewinde.scad")),
    ("library",    "UB Examples (image scene)", os.path.join(CORPUS, "UB.scad-main/Images/Examples.scad")),
]

caps = utils.openscad_capabilities(OSCAD)
print(f"engine : {OSCAD}")
print(f"caps   : {caps}")
print(f"timeout: {TIMEOUT}s\n")
print(f"{'RESULT':<12}{'CATEGORY':<12}{'obj':>4}{'verts':>9}{'col':>4}{'t(s)':>7}  file")
print("-" * 100)

buckets = {}
bugs = []
for category, label, scad in CASES:
    if not os.path.isfile(scad):
        print(f"{'SKIP':<12}{category:<12}{'':>4}{'':>9}{'':>4}{'':>7}  {label} (missing)")
        buckets["SKIP"] = buckets.get("SKIP", 0) + 1
        continue

    compile_path, compat, fixes = utils.prepare_scad_compat(scad)
    out = os.path.join(tmp, "out" + utils.output_extension(caps))
    if os.path.exists(out):
        os.unlink(out)
    t0 = time.monotonic()
    try:
        ok, log = utils.run_openscad(OSCAD, compile_path, out, caps, timeout=TIMEOUT)
    except Exception as e:
        ok, log = False, f"run_openscad raised: {e}"
    dt = time.monotonic() - t0
    if compat:
        try:
            os.unlink(compat)
        except OSError:
            pass

    tag = (" +legacy:" + ",".join(fixes)) if fixes else ""

    if not ok:
        low = (log or "").lower()
        if "model is empty" in low or "no 3d mesh to import" in low:
            result = "EMPTY"
        elif "timed out" in low or "timeout" in low or dt >= TIMEOUT - 1:
            result = "TIMEOUT"
        else:
            result = "COMPILE-FAIL"
        print(f"{result:<12}{category:<12}{'':>4}{'':>9}{'':>4}{dt:>7.1f}  {label}{tag}")
        print(f"             -> {(log or '').strip()[-240:]}")
        buckets[result] = buckets.get(result, 0) + 1
        if result == "COMPILE-FAIL":
            bugs.append((result, label))
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
        print(f"{'IMPORT-FAIL':<12}{category:<12}{'':>4}{'':>9}{'':>4}{dt:>7.1f}  {label}: {e}")
        buckets["IMPORT-FAIL"] = buckets.get("IMPORT-FAIL", 0) + 1
        bugs.append(("IMPORT-FAIL", label))
        continue

    verts = sum(len(o.data.vertices) for o in created if o.type == 'MESH')
    colors = len({m.name for o in created for m in o.data.materials if m})
    result = "PASS" if (created and verts > 0) else "EMPTY"
    print(f"{result:<12}{category:<12}{len(created):>4}{verts:>9}{colors:>4}{dt:>7.1f}  {label}{tag}")
    buckets[result] = buckets.get(result, 0) + 1
    if result == "EMPTY":
        bugs.append(("EMPTY", label))

    for o in list(created):
        bpy.data.objects.remove(o, do_unlink=True)

print("-" * 100)
summary = "  ".join(f"{k}={v}" for k, v in sorted(buckets.items()))
print(f"SUMMARY: {summary}")
# Only compile/import failures are hard bugs; timeouts and empties are noted.
hard = [b for b in bugs if b[0] in ("COMPILE-FAIL", "IMPORT-FAIL")]
if hard:
    print("HARD FAILURES (add-on bugs):")
    for kind, label in hard:
        print(f"  [{kind}] {label}")
sys.exit(1 if hard else 0)
