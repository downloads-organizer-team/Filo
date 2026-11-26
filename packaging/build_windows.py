"""Build the Windows installer from a Git checkout, official runtime ZIPs and Inno Setup 6.

    python packaging/build_windows.py --electron electron-v45.3.3-win32-x64.zip \
        --python-embed python-3.13.14-embed-amd64.zip --iscc ISCC.exe --output dist

The version comes from desktop/package.json. Stage new application files before building.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
ELECTRON_SHA256 = "49dd2d3875944f08de03d34595cd30093c588b9edcabb41a0ac481028a3a5a8a"
PYTHON_SHA256 = "90b4e5b9898b72d744650524bff92377c367f44bd5fbd09e3148656c080ad907"


def unpack_runtime(archive, expected_hash, destination):
    with archive.open("rb") as source:
        checksum = hashlib.file_digest(source, "sha256").hexdigest()
    if checksum != expected_hash:
        raise ValueError(f"Unexpected SHA-256 for {archive.name}: {checksum}")
    with ZipFile(archive) as source:
        source.extractall(destination)


def stage_application(stage):
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    for name in tracked.decode("utf-8").split("\0"):
        if not name:
            continue
        path = Path(name)
        module = (len(path.parts) == 1 and path.suffix == ".py"
                  and not name.startswith("test_") and name not in {"desktop_smoke.py", "ui_theme.py"})
        asset = path.parts[0] in {"desktop", "browser_extension", "vendor"} or name in {
            "terms.json", "demo.zip", "icons/brand.png",
        }
        if module or asset:
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--electron", required=True, type=Path, help="Official Electron 45.3.3 Windows x64 ZIP")
    parser.add_argument("--python-embed", required=True, type=Path, help="Official Python 3.13.14 AMD64 embeddable ZIP")
    parser.add_argument("--iscc", default="ISCC.exe", help="Inno Setup 6 compiler path or command on PATH")
    parser.add_argument("--output", required=True, type=Path, help="Directory for the setup executable")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output, prefix="installer-build-") as temporary:
        stage = Path(temporary)
        stage_application(stage)
        package = json.loads((stage / "desktop/package.json").read_bytes())
        version = package["version"]
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError(f"Expected a numeric release version, got {version}")
        runtime = stage / "runtime"
        unpack_runtime(args.electron, ELECTRON_SHA256, runtime)
        (runtime / "electron.exe").rename(runtime / "organizer.exe")
        (runtime / "resources/default_app.asar").unlink()
        launcher = runtime / "resources/app"
        launcher.mkdir()
        package["main"] = "launch.cjs"
        (launcher / "package.json").write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
        (launcher / "launch.cjs").write_text('require("../../../desktop/main.cjs");\n', encoding="ascii")
        embedded = stage / "python"
        unpack_runtime(args.python_embed, PYTHON_SHA256, embedded)
        (embedded / "python313._pth").write_text("python313.zip\n.\n..\n", encoding="ascii")
        subprocess.run([args.iscc, "/Qp", f"/DAppVersion={version}", f"/DStage={stage}", f"/O{output}",
                        str(ROOT / "packaging/windows.iss")], check=True)
    installer = output / f"Downloads-Organizer-{version}-Setup-x64.exe"
    with installer.open("rb") as stream:
        print(f"{installer}\nSHA-256 {hashlib.file_digest(stream, 'sha256').hexdigest()}")


if __name__ == "__main__":
    main()
