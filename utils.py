# SPDX-License-Identifier: GPL-3.0-or-later
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

SNAPSHOTS_URL = "https://files.openscad.org/snapshots/"


def _no_console_kwargs():
    """On Windows, avoid a console window flashing when OpenSCAD is launched."""
    if sys.platform.startswith("win"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def addon_version():
    """Add-on version. The extension manifest is the single source of truth."""
    manifest = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
    try:
        import tomllib
        with open(manifest, "rb") as f:
            return tomllib.load(f).get("version", "?")
    except Exception:
        pass
    try:
        import addon_utils
        for mod in addon_utils.modules(refresh=False):
            if mod.__name__ == __package__:
                v = addon_utils.module_bl_info(mod).get("version", (0, 0, 0))
                return ".".join(str(x) for x in v)
    except Exception:
        pass
    return "?"


_LINUX_CANDIDATES = [
    "/usr/bin/openscad",
    "/usr/local/bin/openscad",
    "/snap/bin/openscad-nightly",
    "/snap/bin/openscad",
    "/var/lib/flatpak/exports/bin/org.openscad.OpenSCAD",
    os.path.expanduser("~/.local/bin/openscad"),
]

_MACOS_CANDIDATES = [
    "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD",
    "/Applications/OpenSCAD-nightly.app/Contents/MacOS/OpenSCAD",
    "/opt/homebrew/bin/openscad",
    "/usr/local/bin/openscad",
]

_WIN_CANDIDATES = [
    r"C:\Program Files\OpenSCAD\openscad.exe",
    r"C:\Program Files (x86)\OpenSCAD\openscad.exe",
    r"C:\Program Files\OpenSCAD (Nightly)\openscad.exe",
]


def find_openscad():
    """Look for an OpenSCAD executable in PATH and common locations (nightly first)."""
    for name in ("openscad-nightly", "openscad"):
        in_path = shutil.which(name)
        if in_path:
            return in_path

    if sys.platform.startswith("linux"):
        candidates = _LINUX_CANDIDATES
    elif sys.platform == "darwin":
        candidates = _MACOS_CANDIDATES
    elif sys.platform.startswith("win"):
        candidates = _WIN_CANDIDATES
    else:
        candidates = []

    for p in candidates:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def user_bin_dir(create=False):
    """Add-on user-data folder for downloaded binaries."""
    import bpy
    try:
        return bpy.utils.extension_path_user(__package__, path="bin", create=create)
    except Exception:
        return bpy.utils.user_resource('SCRIPTS', path="muscadier_bin", create=create)


def _find_managed_binary(folder):
    """Look inside `folder` for an add-on-managed OpenSCAD. Returns a path or None."""
    # Linux: AppImage (or the extracted AppRun when FUSE is unavailable)
    for name in ("squashfs-root/AppRun", "OpenSCAD-nightly.AppImage"):
        p = os.path.join(folder, name)
        if os.path.isfile(p):
            if not os.access(p, os.X_OK):
                try:
                    os.chmod(p, 0o755)
                except OSError:
                    continue
            return p
    # Windows: openscad.exe inside the extracted portable zip
    win_root = os.path.join(folder, "win")
    if os.path.isdir(win_root):
        for base, _dirs, files in os.walk(win_root):
            for f in files:
                if f.lower() == "openscad.exe":
                    return os.path.join(base, f)
    return None


def downloaded_nightly():
    """Add-on-managed nightly: downloaded (user-data) or shipped with the package."""
    folders = []
    try:
        folders.append(user_bin_dir())
    except Exception:
        pass
    folders.append(os.path.join(os.path.dirname(__file__), "bin"))

    # Backwards compatibility: reuse the nightly downloaded by the old "blender_scad" add-on
    for c in list(folders):
        legacy = c.replace("muscadier", "blender_scad")
        if legacy != c and os.path.isdir(legacy):
            folders.append(legacy)
            backup = os.path.join(legacy, "bin_backup")
            if os.path.isdir(backup):
                folders.append(backup)

    for folder in folders:
        p = _find_managed_binary(folder)
        if p:
            return _migrate_from_legacy(p) if "blender_scad" in p else p
    return None


def _migrate_from_legacy(path):
    """Copy the old add-on's nightly into muSCADier's user-data folder, so it
    survives the uninstall of the old extension."""
    if os.path.basename(path) != "OpenSCAD-nightly.AppImage":
        return path
    try:
        dest = os.path.join(user_bin_dir(create=True), "OpenSCAD-nightly.AppImage")
        if not os.path.isfile(dest):
            shutil.copy2(path, dest)
            os.chmod(dest, 0o755)
        return dest
    except OSError:
        return path


# Resolving the binary walks the filesystem, so its result is cached and reused
# across panel redraws; invalidate_openscad_cache() drops it after a download or a
# preference change.
_resolved_cache = {}


def resolve_openscad(prefs):
    """Resolve the binary to use: explicit pref -> downloaded nightly -> system."""
    key = (prefs.openscad_path or "").strip()
    if key in _resolved_cache:
        return _resolved_cache[key]

    if key and key != "openscad" and os.path.isfile(key):
        resolved = key
    else:
        resolved = downloaded_nightly() or find_openscad()
    _resolved_cache[key] = resolved
    return resolved


def invalidate_openscad_cache():
    """Force re-resolution and re-detection (call after a download or path change)."""
    _resolved_cache.clear()
    _caps_cache.clear()


_caps_cache = {}


def _run_help(openscad_bin, argument):
    try:
        proc = subprocess.run(
            [openscad_bin, argument],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, check=False,
            **_no_console_kwargs(),
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except Exception:
        return ""


def openscad_capabilities(openscad_bin):
    """Detect version and capabilities of the binary. Returns a dict, cached per
    (path, mtime).

    keys: version (str), manifold (bool), color_3mf (bool).
    """
    if not openscad_bin or not os.path.isfile(openscad_bin):
        return {"version": "", "manifold": False, "color_3mf": False,
                "export_format": False}

    key = (openscad_bin, os.path.getmtime(openscad_bin))
    cached = _caps_cache.get(key)
    if cached is not None:
        return cached

    out = _run_help(openscad_bin, "--version")
    m = re.search(r"version\s+([\d.\w]+)", out)
    version = m.group(1) if m else ""

    help_text = _run_help(openscad_bin, "--help")
    manifold = "--backend" in help_text
    # --export-format arrived in 2019.05; older builds infer the format from the
    # output extension, so we must not pass the flag to them.
    export_format = "--export-format" in help_text
    color_3mf = False
    if manifold:
        help_export = _run_help(openscad_bin, "--help-export")
        color_3mf = "export-3mf" in help_export and "color-mode" in help_export

    caps = {"version": version, "manifold": manifold,
            "color_3mf": color_3mf, "export_format": export_format}
    _caps_cache[key] = caps
    return caps


def _library_search_path(scad_path):
    """Project-local OpenSCAD library folders, found by walking up from the file.

    Many downloaded projects `include<lib.scad>` expecting the library to sit in a
    sibling 'libraries'/'lib' folder (or be installed system-wide). Discovering
    those folders lets such projects import without a manual library install.
    """
    dirs, seen = [], set()
    folder = os.path.dirname(os.path.abspath(scad_path))
    for _ in range(6):
        for sub in ("libraries", "lib"):
            cand = os.path.join(folder, sub)
            if cand not in seen and os.path.isdir(cand):
                seen.add(cand)
                dirs.append(cand)
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return dirs


def _openscad_env(scad_path):
    """Subprocess environment with OPENSCADPATH augmented by project-local
    libraries. Returns None (inherit the parent environment) when there is
    nothing to add."""
    extra = _library_search_path(scad_path)
    if not extra:
        return None
    env = os.environ.copy()
    existing = env.get("OPENSCADPATH", "")
    env["OPENSCADPATH"] = os.pathsep.join(extra + ([existing] if existing else []))
    return env


def _command(openscad_bin, scad_path, out_path, caps, deps_path=None):
    cmd = [openscad_bin, "-o", out_path]
    if caps.get("manifold"):
        cmd.append("--backend=manifold")
    if deps_path:
        cmd += ["-d", deps_path]
    if out_path.lower().endswith(".3mf"):
        cmd += ["-O", "export-3mf/material-type=color", "-O", "export-3mf/color-mode=model"]
    elif caps.get("export_format"):
        cmd += ["--export-format", "binstl"]
    cmd.append(scad_path)
    return cmd


# ---------------------------------------------------------------------------
# Legacy SCAD syntax compatibility (pre-2015)
# ---------------------------------------------------------------------------

_LEGACY_SUBSTITUTIONS = (
    (re.compile(r"\bchild\s*\("), "children(", "child()->children()"),
    (re.compile(r"\bassign\s*\("), "let(", "assign()->let()"),
    (re.compile(r"\bimport_(?:stl|dxf|off)\s*\("), "import(", "import_*()->import()"),
    (re.compile(r"\bdxf_linear_extrude\s*\("), "linear_extrude(",
     "dxf_linear_extrude()->linear_extrude()"),
    (re.compile(r"\bdxf_rotate_extrude\s*\("), "rotate_extrude(",
     "dxf_rotate_extrude()->rotate_extrude()"),
)

_COMPAT_PREFIX = ".muscadier_compat_"


def _sweep_compat(folder):
    """Remove stale compat copies left behind by an earlier crash/kill."""
    try:
        for name in os.listdir(folder):
            if name.startswith(_COMPAT_PREFIX):
                try:
                    os.unlink(os.path.join(folder, name))
                except OSError:
                    pass
    except OSError:
        pass


def prepare_scad_compat(scad_path):
    """Transparently auto-fix legacy SCAD syntax (child, assign, import_stl).

    Modern OpenSCAD only warns about the removed modules and produces incomplete
    geometry. The patched copy is written next to the original (so relative
    include/use keep working) and must be deleted once compilation ends. The
    original file is never touched.

    Returns (path_to_compile, temp_path_or_None, detected_fixes: list[str]).
    If the folder is not writable, temp_path is None but detected_fixes is still
    populated: the caller can then warn that geometry will be incomplete.
    """
    try:
        with open(scad_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return scad_path, None, []

    fixes = []
    for pattern, replacement, label in _LEGACY_SUBSTITUTIONS:
        text, n = pattern.subn(replacement, text)
        if n:
            fixes.append(label)
    if not fixes:
        return scad_path, None, []

    folder = os.path.dirname(scad_path) or "."
    name = os.path.basename(scad_path)
    _sweep_compat(folder)
    try:
        f = tempfile.NamedTemporaryFile(
            "w", prefix=_COMPAT_PREFIX, suffix="_" + name,
            dir=folder, delete=False, encoding="utf-8", errors="replace")
        with f:
            f.write(text)
    except OSError:
        return scad_path, None, fixes
    return f.name, f.name, fixes


def parse_deps(deps_path, base_dir):
    """Parse a make-style dependency file. Returns a list of absolute paths."""
    try:
        with open(deps_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    if ":" in text:
        text = text.split(":", 1)[1]
    paths = []
    for token in text.replace("\\\n", " ").split():
        p = token if os.path.isabs(token) else os.path.join(base_dir, token)
        if os.path.isfile(p):
            paths.append(os.path.normpath(p))
    return paths


_ERROR_PREFIXES = ("ERROR", "WARNING", "TRACE", "Can't")


def extract_errors(log):
    """Pull the human-readable error lines out of the OpenSCAD log (short paths)."""
    lines = [r.strip() for r in log.splitlines()
             if r.strip().startswith(_ERROR_PREFIXES)]
    lines = [re.sub(r"(['\"]?)(/[^\s'\"]+/)([^/\s'\"]+)(['\"]?)", r"\1\3\4", r) for r in lines]
    return lines


def output_extension(caps):
    return ".3mf" if caps.get("color_3mf") else ".stl"


def _validate_input(openscad_bin, scad_path):
    """Returns an error message, or None if everything is fine."""
    if not openscad_bin:
        if download_supported():
            return ("OpenSCAD not found. Use 'Download OpenSCAD nightly' in the SCAD "
                    "panel, or set its path in the add-on preferences.")
        return ("OpenSCAD not found. Install OpenSCAD (e.g. from openscad.org or "
                "Homebrew) and set its path in the add-on preferences.")
    if not os.path.isfile(scad_path):
        return f"SCAD file does not exist: {scad_path}"
    return None


def start_openscad(openscad_bin, scad_path, out_path, caps):
    """Start OpenSCAD in the background (non-blocking).

    Returns (proc, log_path, deps_path) on success, or (None, error_msg, None).
    The log (stdout+stderr) is written to a file to avoid deadlocks on full pipes.
    """
    error = _validate_input(openscad_bin, scad_path)
    if error:
        return None, error, None

    log_f = tempfile.NamedTemporaryFile(prefix="muscadier_", suffix=".log", delete=False)
    deps_f = tempfile.NamedTemporaryFile(prefix="muscadier_", suffix=".d", delete=False)
    deps_f.close()
    try:
        proc = subprocess.Popen(
            _command(openscad_bin, scad_path, out_path, caps, deps_f.name),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            cwd=os.path.dirname(scad_path) or None,
            env=_openscad_env(scad_path),
            **_no_console_kwargs(),
        )
    except FileNotFoundError:
        log_f.close()
        os.unlink(log_f.name)
        os.unlink(deps_f.name)
        return None, f"OpenSCAD executable not found: {openscad_bin}", None
    except Exception as e:
        log_f.close()
        os.unlink(log_f.name)
        os.unlink(deps_f.name)
        return None, f"Error while running OpenSCAD: {e}", None
    finally:
        log_f.close()
    return proc, log_f.name, deps_f.name


def terminate_process(proc):
    """Terminate the OpenSCAD process cleanly (SIGTERM, then SIGKILL)."""
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def read_log(log_path, max_char=2000):
    """Read the tail of the compilation log."""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read().strip()
        return text[-max_char:]
    except OSError:
        return ""


def compilation_result(returncode, log, out_path):
    """Evaluate the compilation outcome. Returns (success: bool, message: str)."""
    have_output = os.path.isfile(out_path) and os.path.getsize(out_path) > 0
    if have_output and returncode == 0:
        last = log.splitlines()[-1] if log else "Compilation complete."
        return True, last
    # No usable geometry. OpenSCAD signals an empty or 2D top level either with a
    # warning (exit 0, no file) or a non-zero exit depending on version, so match
    # on the message regardless of the return code.
    low = log.lower()
    if "not a 3d object" in low or "2d object" in low:
        return False, ("The top-level object is 2D, so there is no 3D mesh to "
                       "import. Extrude it (linear_extrude / rotate_extrude) "
                       "and try again.")
    if "top level object is empty" in low:
        return False, ("OpenSCAD produced no geometry: the model is empty. "
                       "Nothing is rendered at the top level (objects may be "
                       "commented out, or gated behind a parameter).")
    if returncode != 0:
        return False, f"OpenSCAD exit {returncode}\n{log}"
    return False, f"No output produced, or empty.\n{log}"


def run_openscad(openscad_bin, scad_path, out_path, caps, timeout=300):
    """Compile a .scad synchronously (used in background mode).

    Returns (success: bool, log: str).
    """
    error = _validate_input(openscad_bin, scad_path)
    if error:
        return False, error

    try:
        proc = subprocess.run(
            _command(openscad_bin, scad_path, out_path, caps),
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
            check=False,
            cwd=os.path.dirname(scad_path) or None,
            env=_openscad_env(scad_path),
            **_no_console_kwargs(),
        )
    except FileNotFoundError:
        return False, f"OpenSCAD executable not found: {openscad_bin}"
    except subprocess.TimeoutExpired:
        return False, f"OpenSCAD compilation timed out ({timeout}s)."
    except Exception as e:
        return False, f"Error while running OpenSCAD: {e}"

    log = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return compilation_result(proc.returncode, log, out_path)


# ---------------------------------------------------------------------------
# Nightly OpenSCAD download (Linux x86_64: AppImage - Windows x86_64: portable zip)
# ---------------------------------------------------------------------------

# regex to extract the version from the file name - template to rebuild it.
_SNAPSHOT = {
    "linux":   (r"OpenSCAD-([\d.]+)-x86_64\.AppImage", "OpenSCAD-{v}-x86_64.AppImage"),
    "windows": (r"OpenSCAD-([\d.]+)-x86-64\.zip",      "OpenSCAD-{v}-x86-64.zip"),
}


def _download_platform():
    """Platform key for auto-download, or None if unsupported."""
    x86_64 = platform.machine().lower() in ("x86_64", "amd64")
    if sys.platform.startswith("linux") and x86_64:
        return "linux"
    if sys.platform.startswith("win") and x86_64:
        return "windows"
    return None


def download_supported():
    return _download_platform() is not None


def _version_key(v):
    """Sort versions like '2026.07.01' numerically."""
    return [int(x) if x.isdigit() else 0 for x in v.split(".")]


def latest_snapshot(platform_key):
    """Returns (url, version) of the latest official snapshot for the platform."""
    regex, template = _SNAPSHOT[platform_key]
    with urllib.request.urlopen(SNAPSHOTS_URL, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    versions = sorted(set(re.findall(regex, html)), key=_version_key)
    if not versions:
        raise RuntimeError("No OpenSCAD snapshot found for this platform.")
    v = versions[-1]
    return SNAPSHOTS_URL + template.format(v=v), v


def _download(url, dest, state):
    """Download `url` to `dest` (via .part), updating state['percent']."""
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            read_bytes = 0
            with open(dest + ".part", "wb") as f:
                while True:
                    chunk = r.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    read_bytes += len(chunk)
                    if total:
                        state["percent"] = int(read_bytes * 100 / total)
        os.replace(dest + ".part", dest)
    finally:
        # Never leave a half-written .part behind on failure.
        if os.path.exists(dest + ".part"):
            try:
                os.unlink(dest + ".part")
            except OSError:
                pass


def download_nightly(state):
    """Download the latest OpenSCAD nightly for the platform. Run in a thread.

    `state` is a shared dict: it reads 'installed_version' (optional), updates
    'percent' and 'phase', and finally writes 'result' (binary path), 'up_to_date'
    (True if it was already the latest version) or 'error'.
    """
    try:
        platform_key = _download_platform()
        if platform_key is None:
            raise RuntimeError("Auto-download is not supported on this platform.")

        state["phase"] = "Looking up latest version..."
        url, version = latest_snapshot(platform_key)

        installed = state.get("installed_version", "")
        already = downloaded_nightly()
        if already and installed and installed == version:
            state["up_to_date"] = True
            state["result"] = already
            return

        state["phase"] = "Downloading OpenSCAD..."
        if platform_key == "linux":
            binary = _download_linux(url, state)
        else:
            binary = _download_windows(url, state)

        state["phase"] = "Verifying binary..."
        if not _binary_runs_ok(binary):
            raise RuntimeError("The downloaded nightly does not start on this system.")
        invalidate_openscad_cache()
        state["result"] = binary
    except Exception as e:
        state["error"] = f"Download failed: {e}"


def _download_linux(url, state):
    """Download the AppImage; without FUSE, extract it and use AppRun."""
    dest = os.path.join(user_bin_dir(create=True), "OpenSCAD-nightly.AppImage")
    _download(url, dest, state)
    os.chmod(dest, 0o755)
    if _binary_runs_ok(dest):
        return dest

    state["phase"] = "Extracting AppImage..."
    folder = os.path.dirname(dest)
    extracted = os.path.join(folder, "squashfs-root")
    shutil.rmtree(extracted, ignore_errors=True)
    subprocess.run(
        [dest, "--appimage-extract"],
        cwd=folder, capture_output=True, timeout=300, check=True,
    )
    return os.path.join(extracted, "AppRun")


def _download_windows(url, state):
    """Download the portable zip, extract it to <data>/win, then find openscad.exe."""
    zip_path = os.path.join(user_bin_dir(create=True), "openscad-win.zip")
    _download(url, zip_path, state)

    state["phase"] = "Extracting..."
    dest = os.path.join(user_bin_dir(create=True), "win")
    shutil.rmtree(dest, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)
    try:
        os.unlink(zip_path)
    except OSError:
        pass

    for base, _dirs, files in os.walk(dest):
        for f in files:
            if f.lower() == "openscad.exe":
                return os.path.join(base, f)
    raise RuntimeError("openscad.exe not found in the downloaded archive.")


def _binary_runs_ok(binary):
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
            **_no_console_kwargs(),
        )
        return proc.returncode == 0 and "OpenSCAD" in (proc.stdout + proc.stderr)
    except Exception:
        return False
