#!/usr/bin/env python3
"""Package complete Google Linux SDK archives with one ABI's native tools."""
import argparse
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

ARCHES = {
    "aarch64": "arm64-v8a",
    "arm": "armeabi-v7a",
    "x86_64": "x86_64",
    "i686": "x86",
}
GROUPS = {
    "platform-tools": ["adb", "e2fsdroid", "etc1tool", "fastboot", "hprof-conv",
                       "make_f2fs", "make_f2fs_casefold", "mke2fs", "sload_f2fs", "sqlite3"],
    "build-tools": ["aapt", "aapt2", "aidl", "dexdump", "split-select", "zipalign"],
    "others": ["veridex"],
}


def download(url, path):
    subprocess.run(
        ["curl", "-fL", "--retry", "3", "--retry-all-errors", "-o", str(path), url],
        check=True,
    )
    if not zipfile.is_zipfile(path):
        raise RuntimeError("Invalid Google SDK ZIP: " + url)


def extract(path, dest):
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError("Corrupt ZIP member: " + bad)
        archive.extractall(dest)


def find_parent(root, filename):
    found = [p.parent for p in root.rglob(filename) if p.is_file()]
    if not found:
        raise RuntimeError(f"Official archive does not contain {filename}")
    return min(found, key=lambda p: len(p.parts))


def normalize_source_properties(root, version):
    """Set SDK package revision metadata to the version of this repacked branch."""
    source_properties = root / "source.properties"
    if not source_properties.is_file():
        raise RuntimeError(f"SDK package is missing source.properties: {source_properties}")
    lines = source_properties.read_text(encoding="utf-8").splitlines()
    revision_lines = [i for i, line in enumerate(lines) if line.startswith("Pkg.Revision=")]
    if revision_lines:
        first = revision_lines[0]
        lines[first] = f"Pkg.Revision={version}"
        for index in reversed(revision_lines[1:]):
            del lines[index]
    else:
        lines.append(f"Pkg.Revision={version}")
    source_properties.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_build_tools_zip(source, output, version):
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9, allowZip64=True) as archive:
        for path in sorted(source.rglob("*")):
            name = (Path(version) / path.relative_to(source)).as_posix()
            if path.is_dir():
                archive.writestr(name + "/", b"")
            else:
                info = zipfile.ZipInfo.from_file(path, name)
                archive.writestr(info, path.read_bytes(),
                                 compress_type=zipfile.ZIP_DEFLATED,
                                 compresslevel=9)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--build-tools-version")
    parser.add_argument("--components", choices=("all", "build-tools", "platform-tools"),
                        default="all")
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()

    build_tools_version = args.build_tools_version or args.version
    want_platform = args.components in ("all", "platform-tools")
    want_build = args.components in ("all", "build-tools")
    args.output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sdk-package-") as temp:
        root = Path(temp)
        official_pt = None
        official_bt = None

        if want_platform:
            pt_zip = root / "platform-tools.zip"
            pt_extract = root / "platform-tools-extracted"
            pt_extract.mkdir()
            download(
                f"https://dl.google.com/android/repository/platform-tools_r{args.version}-linux.zip",
                pt_zip,
            )
            extract(pt_zip, pt_extract)
            official_pt = pt_extract / "platform-tools"
            if not official_pt.is_dir():
                official_pt = find_parent(pt_extract, "adb")

        if want_build:
            bt_zip = root / "build-tools.zip"
            bt_extract = root / "build-tools-extracted"
            bt_extract.mkdir()
            archive_version = build_tools_version
            if archive_version.endswith(".0.0"):
                archive_version = archive_version.rsplit(".", 2)[0]
            download(
                f"https://dl.google.com/android/repository/build-tools_r{archive_version}-linux.zip",
                bt_zip,
            )
            extract(bt_zip, bt_extract)
            official_bt = find_parent(bt_extract, "aapt")

        for build_arch, abi in ARCHES.items():
            artifact = next(
                args.artifacts.rglob(f"android-sdk-tools-static-{build_arch}.zip"),
                None,
            )
            if artifact is None:
                raise RuntimeError(f"Build artifact missing for {build_arch}: {abi}")

            built_root = root / f"built-{build_arch}"
            extract(artifact, built_root)

            if want_platform:
                pt_root = root / f"pt-{abi}"
                shutil.copytree(official_pt, pt_root)
                for name in GROUPS["platform-tools"]:
                    source = built_root / "platform-tools" / name
                    if not source.is_file():
                        raise RuntimeError(f"{abi}: built binary missing: {source}")
                    destination = pt_root / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    destination.chmod(0o755)
                normalize_source_properties(pt_root, args.version)

                pt_output = args.output / f"platform-tools-{args.version}-{abi}.tar.gz"
                with tarfile.open(pt_output, "w:gz", compresslevel=9) as archive:
                    archive.add(pt_root, arcname="platform-tools")
                with tarfile.open(pt_output, "r:gz") as archive:
                    members = set(archive.getnames())
                    missing = {f"platform-tools/{name}" for name in GROUPS["platform-tools"]} - members
                    if missing:
                        raise RuntimeError(f"{abi}: Platform Tools archive missing {sorted(missing)}")
                    metadata = archive.extractfile("platform-tools/source.properties")
                    if metadata is None or f"Pkg.Revision={args.version}" not in metadata.read().decode("utf-8").splitlines():
                        raise RuntimeError(f"{abi}: Platform Tools revision mismatch")
                print(f"created {pt_output}")

            if want_build:
                bt_root = root / f"bt-{abi}"
                shutil.copytree(official_bt, bt_root)
                # Keep official Java tools/resources; adapt launcher shebangs for Android shells.
                for launcher in ("d8", "apksigner"):
                    launcher_path = bt_root / launcher
                    if launcher_path.is_file():
                        data = launcher_path.read_bytes()
                        if data.startswith(b"#!"):
                            _, separator, remainder = data.partition(b"\n")
                            if separator:
                                launcher_path.write_bytes(b"#!/system/bin/env sh\n" + remainder)

                for group in ("build-tools", "others"):
                    for name in GROUPS[group]:
                        source = built_root / group / name
                        if not source.is_file():
                            raise RuntimeError(f"{abi}: built binary missing: {source}")
                        destination = bt_root / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)
                        destination.chmod(0o755)
                normalize_source_properties(bt_root, build_tools_version)

                bt_output = args.output / f"build-tools-{build_tools_version}-{abi}.zip"
                create_build_tools_zip(bt_root, bt_output, build_tools_version)
                with zipfile.ZipFile(bt_output) as archive:
                    members = set(archive.namelist())
                    missing = {
                        f"{build_tools_version}/{name}"
                        for name in GROUPS["build-tools"] + GROUPS["others"]
                    } - members
                    if missing:
                        raise RuntimeError(f"{abi}: Build Tools archive missing {sorted(missing)}")
                    metadata = archive.read(f"{build_tools_version}/source.properties").decode("utf-8").splitlines()
                    if f"Pkg.Revision={build_tools_version}" not in metadata:
                        raise RuntimeError(f"{abi}: Build Tools revision mismatch")
                print(f"created {bt_output}")


if __name__ == "__main__":
    main()
