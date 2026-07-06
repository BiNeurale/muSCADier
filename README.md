<div align="center">

<img src="icons/muSCADier_logo.png" alt="muSCADier" width="200">

# muSCADier

**Import OpenSCAD (`.scad`) files into Blender as native geometry** — with colors,
fast Manifold rendering, and live reload on save.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Blender 4.2+](https://img.shields.io/badge/Blender-4.2%2B-orange.svg)

</div>

---

## Why this exists

OpenSCAD is a wonderful tool for parametric, code-driven modeling, but bringing
`.scad` models into Blender was painful — almost none of the existing importers
worked reliably. So I wrote one. I've tested it on many `.scad` files, including
awkward, heavy and legacy ones, and it holds up well.

## Why it needs OpenSCAD

`.scad` is not a mesh format — it's a small programming language (booleans, loops,
modules, `include`/`use`, external libraries). Only OpenSCAD's own engine can
evaluate all of it faithfully, so muSCADier drives the real **OpenSCAD CLI** to
compile your model and imports the result into Blender.

Point it at an OpenSCAD you already have, or let it **download one for you**. Prefer
a **recent build**: modern OpenSCAD ships the **Manifold** backend, which is far
faster than the old CGAL renderer and is what brings per-object colors across.

## Features

- **One-click import** — `File > Import > SCAD (.scad)`, or the **SCAD** panel in the
  3D View sidebar (press `N`).
- **Try it instantly** — a bundled example is one **Import Example** click away.
- **Colors** — imports 3MF with per-object colors when a Manifold-capable OpenSCAD is
  available.
- **Fast** — uses OpenSCAD's Manifold backend, up to ~100× faster than legacy CGAL.
- **Live reload** — keep editing your `.scad` in any editor; every save re-imports.
- **Imports `.scad` from any era** — legacy syntax is auto-repaired (`child()` →
  `children()`, `assign()` → `let()`, `import_stl()` → `import()`,
  `dxf_linear_extrude()` → `linear_extrude()`) on a temporary copy, so old models
  import fully instead of coming out empty. Your original file is never touched.
- **Multi-file projects** — relative `include`/`use` and project-local `libraries/`
  folders resolve automatically.
- **Non-blocking** — compilation runs in the background with a progress readout and a
  Cancel button; Blender stays responsive.
- **Bring-your-own or auto-download engine** — use a system OpenSCAD, or fetch a
  recent nightly from within the add-on (Linux and Windows, x86-64).

## Requirements

- **Blender 4.2 or newer** (developed and tested up to 5.1).
- **OpenSCAD** — either installed on your system, or downloaded from inside the add-on
  (Linux / Windows x86-64). A recent build is recommended for colors and speed. On
  **macOS**, install OpenSCAD yourself (e.g. from openscad.org or Homebrew) and, if
  needed, set its path in the add-on preferences.

## Installation

1. Download `muscadier-X.Y.Z.zip` from the
   [Releases page](https://github.com/BiNeurale/muSCADier/releases).
2. In Blender: `Edit > Preferences > Get Extensions`, open the drop-down (top-right)
   and choose **Install from Disk…**, then pick the zip.
3. Open the **SCAD** panel (`N` in the 3D View). If you don't have OpenSCAD yet, click
   **Download nightly**.

## Usage

- **Import:** `File > Import > SCAD (.scad)`, or the **SCAD** sidebar tab (`N`) →
  **Import SCAD…**.
- **Re-import** the current file, or toggle **Live** to re-import on every save. Heavy
  models take as long as OpenSCAD needs to recompile.
- **Example:** with nothing imported yet, the panel offers **Import Example** — a quick
  way to check that your engine works and to see colors come through.

## Compatibility

muSCADier aims to import **any `.scad`, on any OpenSCAD version**:

- **New and old OpenSCAD** — from the fast 2026 Manifold nightlies down to the 2021
  CGAL builds. Capabilities are detected at runtime and the command line is adapted
  accordingly (colored 3MF where possible, plain STL otherwise).
- **Legacy language features** — removed or renamed constructs are auto-repaired so the
  geometry is complete rather than silently empty.
- **Multi-file projects** — relative `include`/`use` and project-local `libraries/`
  folders resolve out of the box.

If you find a `.scad` that doesn't import correctly, that's a bug I want to hear about —
please open an issue.

## Contributing

Issues and pull requests are very welcome: legacy edge cases, packaging for more
platforms, performance, and features like richer material mapping. If muSCADier is
useful to you, try it on your real projects and tell me what breaks.

## License

Released under the **GNU General Public License v3.0 or later** — see
[LICENSE](LICENSE). Blender add-ons build on Blender's GPL Python API, so the GPL is
both the natural and the required choice here.

## Credits

Built on top of the excellent [OpenSCAD](https://openscad.org/) project.
Created by **Emanuele Lovato**.
