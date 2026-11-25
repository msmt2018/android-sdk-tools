#!/usr/bin/env python3
"""Package complete Google Linux SDK archives with one ABI's native tools."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
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




def load_official_archive_checksums():
    urls = (
        "https://dl.google.com/android/repository/repository2-3.xml",
        "https://dl.google.com/android/repository/repository2-2.xml",
        "https://dl.google.com/android/repository/repository2-1.xml",
    )
    checksums = {}
    loaded = []
    for url in urls:
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "android-sdk-tools-integrity/1.0"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                root = ET.fromstring(response.read())
        except Exception as error:
            print("Google SDK manifest unavailable {}: {}".format(url, error))
            continue
        loaded.append(url)
        for complete in root.iter():
            if complete.tag.rsplit("}", 1)[-1] != "complete":
                continue
            fields = {node.tag.rsplit("}", 1)[-1]: node for node in complete}
            url_node, checksum_node, size_node = (
                fields.get("url"), fields.get("checksum"), fields.get("size")
            )
            if url_node is None or checksum_node is None or size_node is None:
                continue
            if checksum_node.attrib.get("type", "sha1").lower() not in ("sha1", "sha-1"):
                continue
            checksums[url_node.text.rsplit("/", 1)[-1]] = (
                checksum_node.text.strip().lower(), int(size_node.text.strip()), url
            )
    if not checksums:
        raise RuntimeError("No official Google SDK archive checksums could be loaded")
    return checksums, loaded


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, path, checksums, records, label):
    result = subprocess.run(
        ["curl", "-fLsS", "--retry", "0", "-o", str(path), url], check=False
    )
    if result.returncode != 0 or not zipfile.is_zipfile(path):
        path.unlink(missing_ok=True)
        raise RuntimeError("Download failed or invalid ZIP for {}: {}".format(label, url))
    filename = url.split("?", 1)[0].rsplit("/", 1)[-1]
    official = checksums.get(filename)
    if official is None:
        path.unlink(missing_ok=True)
        raise RuntimeError("No Google-published checksum for {}".format(filename))
    expected_sha1, expected_size, manifest_url = official
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        path.unlink(missing_ok=True)
        raise RuntimeError("{} size mismatch: expected {}, got {}".format(
            filename, expected_size, actual_size
        ))
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha1 = digest.hexdigest()
    if actual_sha1 != expected_sha1:
        path.unlink(missing_ok=True)
        raise RuntimeError("{} SHA-1 mismatch: expected {}, got {}".format(
            filename, expected_sha1, actual_sha1
        ))
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            path.unlink(missing_ok=True)
            raise RuntimeError("{} contains corrupt ZIP member {}".format(filename, bad))
    records.append({
        "component": label, "url": url, "filename": filename,
        "size": actual_size, "official_sha1": expected_sha1,
        "downloaded_sha256": sha256_file(path), "official_manifest": manifest_url,
    })
    print("Verified Google archive {} SHA-1={}".format(filename, actual_sha1))


def verify_tar_gz(path):
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError("Cannot read tar member {} in {}".format(
                        member.name, path
                    ))
                while stream.read(1024 * 1024):
                    pass


def write_integrity_manifests(output_dir, manifests, downloads):
    archives = sorted(
        list(output_dir.glob("platform-tools-*.tar.gz"))
        + list(output_dir.glob("build-tools-*.zip"))
    )
    if len(archives) != 8:
        raise RuntimeError("Expected 8 final SDK archives, found {}".format(len(archives)))
    for path in archives:
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                bad = archive.testzip()
                if bad:
                    raise RuntimeError("Corrupt final ZIP member {} in {}".format(bad, path))
        else:
            verify_tar_gz(path)
    source_lock_path = Path("source-lock.json")
    if not source_lock_path.is_file():
        raise RuntimeError("source-lock.json missing; refusing to publish without exact source revisions")
    source_lock = json.loads(source_lock_path.read_text(encoding="utf-8"))
    source_path = output_dir / "OFFICIAL-SOURCES.json"
    source_path.write_text(json.dumps({
        "schema_version": 1,
        "source_lock": source_lock,
        "official_repository_manifests": manifests,
        "downloads": downloads,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = archives + [source_path]
    (output_dir / "SHA256SUMS").write_text(
        "".join("{}  {}\n".format(sha256_file(item), item.name) for item in files),
        encoding="utf-8",
    )


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
    else:
        # Some official Linux Build Tools ZIPs contain source.properties but omit
        # package.xml. Generate SDK Manager metadata for the repacked package.
        common_ns = "http://schemas.android.com/repository/android/common/02"
        generic_ns = "http://schemas.android.com/repository/android/generic/02"
        xsi_ns = "http://www.w3.org/2001/XMLSchema-instance"
        ET.register_namespace("common", common_ns)
        ET.register_namespace("generic", generic_ns)
        ET.register_namespace("xsi", xsi_ns)
        q = lambda name: f"{{{common_ns}}}{name}"
        tree = ET.ElementTree(ET.Element(q("repository")))
        package = ET.SubElement(tree.getroot(), q("localPackage"),
                                {"path": f"build-tools;{version}"})
        ET.SubElement(package, q("type-details"),
                      {f"{{{xsi_ns}}}type": "generic:genericDetailsType"})
        revision = ET.SubElement(package, q("revision"))
        for component, value in (("major", major), ("minor", minor), ("micro", micro)):
            ET.SubElement(revision, q(component)).text = value
        ET.SubElement(package, q("display-name")).text = (
            f"Android SDK Build-Tools {version}"
        )
    tree.write(package_xml, encoding="utf-8", xml_declaration=True)


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
    parser.add_argument("--version", required=True,
                        help="output Platform Tools and Build Tools version")
    parser.add_argument("--build-tools-base-version",
                        help="Google Build Tools archive version used as the resource base")
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    build_tools_base_version = args.build_tools_base_version or args.version
    args.output.mkdir(parents=True, exist_ok=True)
    official_checksums, manifest_urls = load_official_archive_checksums()
    download_records = []

    with tempfile.TemporaryDirectory(prefix="sdk-package-") as temp:
        root = Path(temp)
        pt_zip = root / "platform-tools.zip"
        bt_zip = root / "build-tools.zip"
        download(
            f"https://dl.google.com/android/repository/platform-tools_r{args.version}-linux.zip",
            pt_zip, official_checksums, download_records, "platform-tools",
        )
        # Google's initial 35.0.0 Build Tools package is named build-tools_r35_linux.zip.
        build_tools_archive_version = build_tools_base_version
        if build_tools_archive_version.endswith(".0.0"):
            build_tools_archive_version = build_tools_archive_version.rsplit(".", 2)[0]
        download(
            f"https://dl.google.com/android/repository/build-tools_r{build_tools_archive_version}_linux.zip",
            bt_zip, official_checksums, download_records, "build-tools",
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
            normalize_build_tools_metadata(bt_root, build_tools_base_version)

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

            # Normalize Google package metadata only after all native binaries are replaced.
            normalize_source_properties(pt_root, args.version)
            normalize_source_properties(bt_root, args.version)

            pt_output = args.output / f"platform-tools-{args.version}-{abi}.tar.gz"
            with tarfile.open(pt_output, "w:gz", compresslevel=9) as archive:
                archive.add(pt_root, arcname="platform-tools")

            bt_output = args.output / f"build-tools-{build_tools_base_version}-{abi}.zip"
            create_build_tools_zip(bt_root, bt_output, build_tools_base_version)

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
                    f"{build_tools_base_version}/{name}"
                    for name in GROUPS["build-tools"] + GROUPS["others"]
                } - members
                if missing:
                    raise RuntimeError(f"{abi}: build-tools archive missing {sorted(missing)}")
                metadata = archive.read(f"{build_tools_base_version}/source.properties").decode("utf-8")
                if f"Pkg.Revision={build_tools_base_version}" not in metadata:
                    raise RuntimeError(f"{abi}: Build Tools source.properties version mismatch")
                package_xml = ET.fromstring(archive.read(f"{build_tools_base_version}/package.xml"))
                package = next(
                    (node for node in package_xml.iter()
                     if node.tag.rsplit("}", 1)[-1] == "localPackage"),
                    None,
                )
                if package is None or package.get("path") != f"build-tools;{build_tools_base_version}":
                    raise RuntimeError(f"{abi}: Build Tools package.xml version mismatch")

            with tarfile.open(pt_output, "r:gz") as archive:
                metadata = archive.extractfile("platform-tools/source.properties")
                if metadata is None or f"Pkg.Revision={args.version}" not in metadata.read().decode("utf-8").splitlines():
                    raise RuntimeError(f"{abi}: Platform Tools source.properties version mismatch")

            with zipfile.ZipFile(bt_output) as archive:
                metadata = archive.read(f"{build_tools_base_version}/source.properties").decode("utf-8").splitlines()
                if f"Pkg.Revision={build_tools_base_version}" not in metadata:
                    raise RuntimeError(f"{abi}: Build Tools source.properties version mismatch")

            verify_tar_gz(pt_output)
            with zipfile.ZipFile(bt_output) as archive:
                bad = archive.testzip()
                if bad:
                    raise RuntimeError("{}: corrupt final Build Tools ZIP member: {}".format(
                        abi, bad
                    ))

            print(f"created {pt_output}")
            print(f"created {bt_output}")


    write_integrity_manifests(args.output, manifest_urls, download_records)

if __name__ == "__main__":
    main()
