#!/usr/bin/env python3
"""Package complete Google Linux SDK archives with one ABI's native tools."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
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


def load_official_archive_checksums():
    """Read official archive sizes and SHA-1 checksums from Google's SDK manifest."""
    urls = (
        "https://dl.google.com/android/repository/repository2-3.xml",
        "https://dl.google.com/android/repository/repository2-2.xml",
        "https://dl.google.com/android/repository/repository2-1.xml",
    )
    checksums = {}
    loaded = []
    for url in urls:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "android-sdk-tools-integrity/1.0"})
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


def download_first_available(urls, path, checksums, records, label):
    """Download an archive only when its size and SHA-1 match Google's manifest."""
    for url in urls:
        result = subprocess.run(
            ["curl", "-fLsS", "--retry", "0", "-o", str(path), url],
            check=False,
        )
        if result.returncode != 0 or not zipfile.is_zipfile(path):
            path.unlink(missing_ok=True)
            continue
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
        records.append({
            "component": label, "url": url, "filename": filename,
            "size": actual_size, "official_sha1": expected_sha1,
            "downloaded_sha256": sha256_file(path), "official_manifest": manifest_url,
        })
        print("Verified Google archive {} SHA-1={}".format(filename, actual_sha1))
        return url
    raise RuntimeError("No official Google SDK archive found: " + ", ".join(urls))


def update_sdk_package_xml(sdk_root, package_path, version, display_name):
    """Synchronize package.xml path/revision with the repacked SDK package."""
    path = sdk_root / "package.xml"
    major, minor, micro = version.split(".", 2)
    if not path.is_file():
        return
    tree = ET.parse(path)
    package = next((n for n in tree.iter()
                    if n.tag.rsplit("}", 1)[-1] == "localPackage"), None)
    if package is None:
        raise RuntimeError("package.xml localPackage missing: {}".format(path))
    package.set("path", package_path)
    revision = next((n for n in package
                     if n.tag.rsplit("}", 1)[-1] == "revision"), None)
    if revision is None:
        raise RuntimeError("package.xml revision missing: {}".format(path))
    namespace = package.tag.split("}", 1)[0] + "}" if "}" in package.tag else ""
    for name, value in (("major", major), ("minor", minor), ("micro", micro)):
        node = next((n for n in revision if n.tag.rsplit("}", 1)[-1] == name), None)
        if node is None:
            node = ET.SubElement(revision, namespace + name)
        node.text = value
    display = next((n for n in package
                    if n.tag.rsplit("}", 1)[-1] == "display-name"), None)
    if display is not None:
        display.text = display_name
    tree.write(path, encoding="utf-8", xml_declaration=True)
    checked = ET.parse(path)
    checked_package = next((n for n in checked.iter()
                            if n.tag.rsplit("}", 1)[-1] == "localPackage"), None)
    checked_revision = next((n for n in checked_package
                             if n.tag.rsplit("}", 1)[-1] == "revision"), None)
    values = {n.tag.rsplit("}", 1)[-1]: n.text for n in checked_revision}
    if checked_package.get("path") != package_path or (
        values.get("major"), values.get("minor"), values.get("micro")
    ) != (major, minor, micro):
        raise RuntimeError("package.xml version mismatch: {}".format(path))


def verify_tar_gz(path):
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError("Cannot read tar member {} in {}".format(member.name, path))
                while stream.read(1024 * 1024):
                    pass


def write_integrity_manifests(output_dir, manifests, downloads):
    archives = sorted(list(output_dir.glob("platform-tools-*.tar.gz"))
                      + list(output_dir.glob("build-tools-*.zip")))
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
    source_manifest = {
        "schema_version": 1,
        "official_repository_manifests": manifests,
        "downloads": downloads,
    }
    source_path = output_dir / "OFFICIAL-SOURCES.json"
    source_path.write_text(json.dumps(source_manifest, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
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



def update_pkg_revision(sdk_root, version):
    """Set the SDK package metadata revision to the version being packaged."""
    properties = sdk_root / "source.properties"
    if not properties.is_file():
        raise RuntimeError(f"SDK source.properties missing: {properties}")
    content = properties.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"(?m)^Pkg\.Revision\s*=.*$",
        f"Pkg.Revision={version}",
        content,
    )
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one Pkg.Revision in {properties}, found {count}"
        )
    properties.write_text(updated, encoding="utf-8")
    if f"Pkg.Revision={version}" not in properties.read_text(encoding="utf-8"):
        raise RuntimeError(f"Failed to update package revision in {properties}")
    print(f"updated {properties}: Pkg.Revision={version}")

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
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    official_checksums, manifest_urls = load_official_archive_checksums()
    download_records = []

    with tempfile.TemporaryDirectory(prefix="sdk-package-") as temp:
        root = Path(temp)
        pt_zip = root / "platform-tools.zip"
        bt_zip = root / "build-tools.zip"
        # Never substitute another Platform Tools revision; Canary packages
        # are also listed in Google's repository metadata and are checksum-verified.
        platform_tools_urls = [
            f"https://dl.google.com/android/repository/platform-tools_r{args.version}-linux.zip"
        ]
        download_first_available(
            platform_tools_urls, pt_zip, official_checksums, download_records, "platform-tools"
        )
        # Platform Tools and Build Tools have independent release trains.
        # Prefer an exact matching Build Tools archive, then the official major
        # release archive, followed by published preview archives for that major.
        major = args.version.split(".", 1)[0]
        build_tools_versions = []
        exact = args.version
        if exact.endswith(".0.0"):
            exact = exact.rsplit(".", 2)[0]
        build_tools_versions.append(exact)
        build_tools_versions.append(major)
        build_tools_versions.extend([f"{major}-rc2", f"{major}-rc1"])
        # Build Tools and Platform Tools have independent release trains.
        # Build Tools 37.0.0 is the official resource base for custom 37.0.2.
        if int(major) >= 36:
            build_tools_versions.append("36")
        build_tools_versions = list(dict.fromkeys(build_tools_versions))
        build_tools_urls = [
            f"https://dl.google.com/android/repository/build-tools_r{version}_linux.zip"
            for version in build_tools_versions
        ]
        download_first_available(
            build_tools_urls, bt_zip, official_checksums, download_records, "build-tools"
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

            # Keep the official Java tools/resources intact; adapt only launcher shebangs
            # for Android's shell environment.
            for launcher in ("d8", "apksigner"):
                launcher_path = bt_root / launcher
                if launcher_path.is_file():
                    data = launcher_path.read_bytes()
                    if data.startswith(b"#!"):
                        _, separator, remainder = data.partition(b"\\n")
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

            # Rewrite both SDK metadata formats after all native binaries are installed.
            update_pkg_revision(pt_root, args.version)
            update_pkg_revision(bt_root, args.version)
            update_sdk_package_xml(
                pt_root, "platform-tools", args.version, "Android SDK Platform-Tools"
            )
            update_sdk_package_xml(
                bt_root, f"build-tools;{args.version}", args.version,
                f"Android SDK Build-Tools {args.version}"
            )

            pt_output = args.output / f"platform-tools-{args.version}-{abi}.tar.gz"
            with tarfile.open(pt_output, "w:gz", compresslevel=9) as archive:
                archive.add(pt_root, arcname="platform-tools")

            bt_output = args.output / f"build-tools-{args.version}-{abi}.zip"
            create_build_tools_zip(bt_root, bt_output, args.version)

            with tarfile.open(pt_output, "r:gz") as archive:
                pt_metadata = archive.extractfile("platform-tools/source.properties")
                if pt_metadata is None or f"Pkg.Revision={args.version}".encode() not in pt_metadata.read():
                    raise RuntimeError(f"{abi}: platform-tools source.properties has the wrong Pkg.Revision")
                members = set(archive.getnames())
                missing = {
                    f"platform-tools/{name}" for name in GROUPS["platform-tools"]
                } - members
                if missing:
                    raise RuntimeError(f"{abi}: platform-tools archive missing {sorted(missing)}")

            with zipfile.ZipFile(bt_output) as archive:
                bt_metadata = archive.read(f"{args.version}/source.properties")
                if f"Pkg.Revision={args.version}".encode() not in bt_metadata:
                    raise RuntimeError(f"{abi}: build-tools source.properties has the wrong Pkg.Revision")
                members = set(archive.namelist())
                missing = {
                    f"{args.version}/{name}"
                    for name in GROUPS["build-tools"] + GROUPS["others"]
                } - members
                if missing:
                    raise RuntimeError(f"{abi}: build-tools archive missing {sorted(missing)}")

            # Validate complete compressed streams after writing the release files.
            verify_tar_gz(pt_output)
            with zipfile.ZipFile(bt_output) as archive:
                bad = archive.testzip()
                if bad:
                    raise RuntimeError(f"{abi}: corrupt final Build Tools ZIP member: {bad}")

            print(f"created {pt_output}")
            print(f"created {bt_output}")

    write_integrity_manifests(args.output, manifest_urls, download_records)


if __name__ == "__main__":
    main()
