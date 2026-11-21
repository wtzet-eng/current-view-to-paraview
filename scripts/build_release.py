"""Build a minimal QGIS plugin ZIP with an explicit runtime file allowlist.

Development QA scripts belong in the source repository, not in user installs.
Run: python3 scripts/build_release.py /path/to/output.zip
"""
import argparse
import configparser
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "view_to_paraview"
RUNTIME = (
    "LICENSE",
    "README.md",
    "__init__.py",
    "browser.py",
    "display.py",
    "geometry_display.py",
    "scene_controls.js",
    "export.py",
    "icon.svg",
    "metadata.txt",
    "open_scene.py",
    "plugin.py",
    "spatial.py",
    "terrain.py",
    "vector.py",
    "vtkio.py",
)
GLANCE = (
    "Glance-LICENSE.txt",
    "Icons-LICENSE.txt",
    "glance.770eed52cdd9858b02aa.js",
    "glance.f7f1fce385809ff46cdc.css",
    "icon.woff2",
    "runtime.f5a0ef0d83d36acd666a.js",
    "vendor-notices.txt",
    "vendors.780f8e17575441251ea0.css",
    "vendors.f23ba06c4f37c01cc7ae.js",
)


def main():
    cfg = configparser.ConfigParser()
    if not cfg.read(PACKAGE / "metadata.txt", encoding="utf-8"):
        raise RuntimeError("Missing metadata.txt")
    version = cfg["general"]["version"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "destination",
        nargs="?",
        type=Path,
        default=ROOT / "dist" / f"Current_View_to_ParaView_{version}_QGIS.zip",
    )
    args = parser.parse_args()
    output = args.destination.expanduser().resolve()
    entries = [PACKAGE / item for item in RUNTIME]
    entries += [PACKAGE / "glance" / item for item in GLANCE]
    for path in entries:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Missing, non-file or symlinked release input: {path}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(f"{PACKAGE.name}/", b"")
        archive.writestr(f"{PACKAGE.name}/glance/", b"")
        for path in entries:
            archive.write(path, arcname=f"{PACKAGE.name}/{path.relative_to(PACKAGE).as_posix()}")

    expected = {f"{PACKAGE.name}/{path.relative_to(PACKAGE).as_posix()}" for path in entries}
    expected |= {f"{PACKAGE.name}/", f"{PACKAGE.name}/glance/"}
    with zipfile.ZipFile(output, "r") as archive:
        actual = set(archive.namelist())
        if actual != expected or archive.testzip() is not None:
            raise RuntimeError("Release archive did not match the allowlist or failed ZIP verification")
        if any("/qa/" in name or "__pycache__" in name for name in actual):
            raise RuntimeError("Release unexpectedly includes development-only files")
    print(f"Validated {output} ({len(entries)} release files; version {version}).")


if __name__ == "__main__":
    main()
