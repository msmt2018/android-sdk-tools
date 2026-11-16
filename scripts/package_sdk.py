#!/usr/bin/env python3
"""Package complete Google Linux SDK archives with one ABI's native tools."""
import argparse
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
import xml.etree.ElementTree as ET
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


def normalize_build_tools_metadata(root, version):
    """Make the repacked SDK metadata agree with its output directory version."""
    major, minor, micro = version.split(".", 2)
    source_properties = root / "source.properties"
    if source_properties.is_file():
        lines = source_properties.read_text(encoding="utf-8").splitlines()
        found_revision = False
        for index, line in enumerate(lines):
            if line.startswith("Pkg.Revision="):
                lines[index] = f"Pkg.Revision={version}"
                found_revision = True
        if not found_revision:
            lines.append(f"Pkg.Revision={version}")
        source_properties.write_text("\n".join(lines) + "\n", encoding="utf-8")

    package_xml = root / "package.xml"
    if package_xml.is_file():
        tree = ET.parse(package_xml)
        package = next(
            (node for node in tree.iter()
             if node.tag.rsplit("}", 1)[-1] == "localPackage"),
            None,
        )
        if package is None:
            raise RuntimeError(f"Build Tools package.xml has no localPackage: {package_xml}")
        package.set("path", f"build-tools;{version}")
        revision = next(
            (node for node in package
             if node.tag.rsplit("}", 1)[-1] == "revision"),
            None,
        )
        if revision is None:
            raise RuntimeError(f"Build Tools package.xml has no revision: {package_xml}")
        for component, value in (("major", major), ("minor", minor), ("micro", micro)):
            node = next(
                (child for child in revision
                 if child.tag.rsplit("}", 1)[-1] == component),
                None,
            )
            if node is None:
                namespace = package.tag.split("}", 1)[0] + "}" if "}" in package.tag else ""
                node = ET.SubElement(revision, f"{namespace}{component}")
            node.text = value
        display_name = next(
            (node for node in package
             if node.tag.rsplit("}", 1)[-1] == "display-name"),
            None,
        )
        if display_name is not None:
            display_name.text = f"Android SDK Build-Tools {version}"
        tree.write(package_xml, encoding="utf-8", xml_declaration=True)


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
    parser.add_argument("--version", required=True,
                        help="output Platform Tools and Build Tools version")
    parser.add_argument("--build-tools-base-version",
                        help="Google Build Tools archive version used as the resource base")
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    build_tools_base_version = args.build_tools_base_version or args.version
    args.output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sdk-package-") as temp:
        root = Path(temp)
        pt_zip = root / "platform-tools.zip"
        bt_zip = root / "build-tools.zip"
        download(
            f"https://dl.google.com/android/repository/platform-tools_r{args.version}-linux.zip",
            pt_zip,
        )
        # Google's initial 35.0.0 Build Tools package is named build-tools_r35_linux.zip.
        build_tools_archive_version = build_tools_base_version
        if build_tools_archive_version.endswith(".0.0"):
            build_tools_archive_version = build_tools_archive_version.rsplit(".", 2)[0]
        download(
            f"https://dl.google.com/android/repository/build-tools_r{build_tools_archive_version}_linux.zip",
            bt_zip,
        )

        pt_extract = root / "platform-tools-extracted"
        bt_extract = root / "build-tools-extracted"
        pt_extract.mkdir()
        bt_extract.mkdir()
        extract(pt_zip, pt_extract)
        extract(bt_zip, bt_extract)

        official_pt = pt_extract / "platform-tools"
        if not official_pt.is_dir():
            official_pt = find_parent(pt_extract, "adb")
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

            pt_root = root / f"pt-{abi}"
            bt_root = root / f"bt-{abi}"
            shutil.copytree(official_pt, pt_root)
            shutil.copytree(official_bt, bt_root)
            normalize_build_tools_metadata(bt_root, args.version)

            # Keep the official Java tools/resources intact; adapt only launcher shebangs
            # for Android's shell environment.
            for launcher in ("d8", "apksigner"):
                launcher_path = bt_root / launcher
                if launcher_path.is_file():
                    data = launcher_path.read_bytes()
                    if data.startswith(b"#!"):
                        _, separator, remainder = data.partition(b"\n")
                        if separator:
                            launcher_path.write_bytes(b"#!/system/bin/env sh\n" + remainder)

            for group, names in GROUPS.items():
                destination_root = pt_root if group == "platform-tools" else bt_root
                for name in names:
                    source = built_root / group / name
                    if not source.is_file():
                        raise RuntimeError(f"{abi}: built binary missing: {source}")
                    destination = destination_root / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    destination.chmod(0o755)
                    print(f"[{abi}] replaced {group}/{name} mode=755")

            pt_output = args.output / f"platform-tools-{args.version}-{abi}.tar.gz"
            with tarfile.open(pt_output, "w:gz", compresslevel=9) as archive:
                archive.add(pt_root, arcname="platform-tools")

            bt_output = args.output / f"build-tools-{args.version}-{abi}.zip"
            create_build_tools_zip(bt_root, bt_output, args.version)

            with tarfile.open(pt_output, "r:gz") as archive:
                members = set(archive.getnames())
                missing = {
                    f"platform-tools/{name}" for name in GROUPS["platform-tools"]
                } - members
                if missing:
                    raise RuntimeError(f"{abi}: platform-tools archive missing {sorted(missing)}")

            with zipfile.ZipFile(bt_output) as archive:
                members = set(archive.namelist())
                missing = {
                    f"{args.version}/{name}"
                    for name in GROUPS["build-tools"] + GROUPS["others"]
                } - members
                if missing:
                    raise RuntimeError(f"{abi}: build-tools archive missing {sorted(missing)}")
                metadata = archive.read(f"{args.version}/source.properties").decode("utf-8")
                if f"Pkg.Revision={args.version}" not in metadata:
                    raise RuntimeError(f"{abi}: Build Tools source.properties version mismatch")
                package_xml = ET.fromstring(archive.read(f"{args.version}/package.xml"))
                package = next(
                    (node for node in package_xml.iter()
                     if node.tag.rsplit("}", 1)[-1] == "localPackage"),
                    None,
                )
                if package is None or package.get("path") != f"build-tools;{args.version}":
                    raise RuntimeError(f"{abi}: Build Tools package.xml version mismatch")

            print(f"created {pt_output}")
            print(f"created {bt_output}")


if __name__ == "__main__":
    main()
