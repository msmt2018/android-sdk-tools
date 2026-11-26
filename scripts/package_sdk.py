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
    # Immutable historical snapshots of Google's repository2-1.xml, mirrored by
    # the F-Droid Android SDK transparency log. These preserve Google's original
    # SHA-1 and archive size after old entries disappear from the live manifests.
    archived_google_checksums = {
        "platform-tools_r30.0.0-linux.zip": ("d124084d621a8cb4b3eb1113d9c90be641d40494", 9337646, "https://github.com/f-droid/android-sdk-transparency-log/blob/a6a62c6d2540fa7ae36064d37030801901675a17/android/repository/repository2-1.xml"),
        "platform-tools_r30.0.1-linux.zip": ("58393eac83fdc9a1030d81a49731c7c518e043c0", 9397456, "https://github.com/f-droid/android-sdk-transparency-log/blob/2ec704185dbf10e2ce3a0b48909d2b098a2d9d3e/android/repository/repository2-1.xml"),
        "platform-tools_r30.0.3-linux.zip": ("3aa611654e163fae7e3dbd73b5c04e12dfe1e07b", 9238434, "https://github.com/f-droid/android-sdk-transparency-log/blob/fa2904871715fe8d91cbc1461a7616c13a6ae3a4/android/repository/repository2-1.xml"),
        "platform-tools_r30.0.4-linux.zip": ("ec00457e833806f08ccdf6661273f0696966d947", 9542280, "https://github.com/f-droid/android-sdk-transparency-log/blob/875ca2b6e2c5ad16e9e47c6bee47fa0e3894285b/android/repository/repository2-1.xml"),
        "platform-tools_r30.0.5-linux.zip": ("ba07433b8e34c2a51c250033abcd1442a28d0863", 13338136, "https://github.com/f-droid/android-sdk-transparency-log/blob/3e49f12669961bde2df149743bf90131ff5d822d/android/repository/repository2-1.xml"),
        "platform-tools_r31.0.0-linux.zip": ("9da77a435aa3ab2ca63703f90c3c760921dd1d0c", 13435024, "https://github.com/f-droid/android-sdk-transparency-log/blob/1cd14482b3d30a221bfc4d2740d19e8eeceda105/android/repository/repository2-1.xml"),
        "platform-tools_r31.0.1-linux.zip": ("35ed511710c1cb613947d429da028e80bcb10dcf", 13476900, "https://github.com/f-droid/android-sdk-transparency-log/blob/d5d6c5711635a3d93f59a38c0ecb7695dfc61859/android/repository/repository2-1.xml"),
        "platform-tools_r31.0.2-linux.zip": ("ff02a9d8c6fa9687e1207fc0c4b84033925d452d", 13876419, "https://github.com/f-droid/android-sdk-transparency-log/blob/c033068318b185d7d5124d80cae91d682c68e2c1/android/repository/repository2-1.xml"),
        "platform-tools_r31.0.3-linux.zip": ("f09581347ed39978abb3a99c6bb286de6adc98ef", 13302579, "https://github.com/f-droid/android-sdk-transparency-log/blob/b812bc7b55eeb887698cee52e59a61a33f50e4da/android/repository/repository2-1.xml"),
        "platform-tools_r32.0.0-linux.zip": ("67ad18f3a2a6716d957b9ce630ea5e564171838a", 13544738, "https://github.com/f-droid/android-sdk-transparency-log/blob/623c85004e565e24dc940c643976f9c9e791f300/android/repository/repository2-1.xml"),
        "platform-tools_r33.0.0-linux.zip": ("fe07ebd9eb60646f0651e120d69303f2e9969904", 13600680, "https://github.com/f-droid/android-sdk-transparency-log/blob/bb82f9e55786da6ce2e7b9fc92c700b6e975281b/android/repository/repository2-1.xml"),
        "platform-tools_r33.0.1-linux.zip": ("4792ee4593e8e2395ddb87a3e82d60629eb0e977", 7449306, "https://github.com/f-droid/android-sdk-transparency-log/blob/2ee7dfd7328f1a1bc51a77f2697c60a6dcf676aa/android/repository/repository2-1.xml"),
        "platform-tools_r33.0.2-linux.zip": ("6bf4f747ad929b02378b44ce083b4502d26109c7", 7406632, "https://github.com/f-droid/android-sdk-transparency-log/blob/0a9f32327df1025fbc9bead15f711eda6e50593d/android/repository/repository2-1.xml"),
        "platform-tools_r33.0.3-linux.zip": ("deb43a0f9eaccd16a47937367ef3b53db3db8d10", 7505569, "https://github.com/f-droid/android-sdk-transparency-log/blob/7643ac590756210ed124780d19ec146c960a68ea/android/repository/repository2-1.xml"),
        "platform-tools_r34.0.0-linux.zip": ("86bb6c1ff4ad8af8c5bb93acabd76926b6388826", 6384379, "https://github.com/f-droid/android-sdk-transparency-log/blob/e2a7e0093516da0290d8ef8d7e035b7ae0f805df/android/repository/repository2-1.xml"),
        "platform-tools_r34.0.5-linux.zip": ("96097475cf7b279fdd8f218f5d043ffe94104ec3", 6333075, "https://github.com/f-droid/android-sdk-transparency-log/blob/50fcb2cb510daf48c73341118c3180ddecbbc595/android/repository/repository2-1.xml"),
        "platform-tools_r35.0.2-linux.zip": ("f6406982a79d67e40b1ca3cb9e5e2cc783c0f232", 7472902, "https://github.com/f-droid/android-sdk-transparency-log/blob/50fcb2cb510daf48c73341118c3180ddecbbc595/android/repository/repository2-1.xml"),
        "platform-tools_r36.0.0-linux.zip": ("ddb0cd76d952d9a1f4c8a32e4ec0e73d7a8bebb8", 7904253, "https://github.com/f-droid/android-sdk-transparency-log/blob/8d3a986511db55ee1a061313e9e0337bb28920bf/android/repository/repository2-1.xml"),
    }
    for filename, metadata in archived_google_checksums.items():
        checksums.setdefault(filename, metadata)
    # The 36.0.2 Linux archive has an independently published SHA-256 lock
    # (and exact byte size) even though Google's historical SHA-1 manifest
    # entry is no longer present in the live repository manifests.
    checksums.setdefault(
        "platform-tools_r36.0.2-linux.zip",
        ("sha256:3afdea91441815ab41254193df0343d92c1b1c0d0237165c3a345c8af8891c31",
         8785200,
         "https://github.com/Uotan-Dev/UotanStudio/blob/3216649858740ea649d22d37c61f009157cd5f17/UotanStudio.Pipeline/Delivery/Tools/Tools.cs"),
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


def download_verified_from_file(url, path, checksums, records, label):
    if not zipfile.is_zipfile(path):
        path.unlink(missing_ok=True)
        raise RuntimeError("Invalid Google SDK ZIP for {}: {}".format(label, url))
    filename = url.split("?", 1)[0].rsplit("/", 1)[-1]
    official = checksums.get(filename)
    if official is None:
        path.unlink(missing_ok=True)
        raise RuntimeError("No Google-published checksum for {}".format(filename))
    expected_digest, expected_size, checksum_source = official
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        path.unlink(missing_ok=True)
        raise RuntimeError("{} size mismatch: expected {}, got {}".format(
            filename, expected_size, actual_size
        ))
    if expected_digest.startswith("sha256:"):
        expected_sha256 = expected_digest.split(":", 1)[1]
        actual_sha256 = sha256_file(path)
        if actual_sha256 != expected_sha256:
            path.unlink(missing_ok=True)
            raise RuntimeError("{} SHA-256 mismatch: expected {}, got {}".format(
                filename, expected_sha256, actual_sha256
            ))
        checksum_algorithm, checksum_value = "sha256", expected_sha256
    else:
        digest = hashlib.sha1()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_sha1 = digest.hexdigest()
        if actual_sha1 != expected_digest:
            path.unlink(missing_ok=True)
            raise RuntimeError("{} SHA-1 mismatch: expected {}, got {}".format(
                filename, expected_digest, actual_sha1
            ))
        checksum_algorithm, checksum_value = "sha1", expected_digest
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            path.unlink(missing_ok=True)
            raise RuntimeError("{} contains corrupt ZIP member {}".format(filename, bad))
    records.append({
        "component": label, "url": url, "filename": filename,
        "size": actual_size,
        "verified_checksum": {"algorithm": checksum_algorithm, "value": checksum_value},
        "downloaded_sha256": sha256_file(path), "checksum_source": checksum_source,
    })
    print("Verified Google archive {} {}={}".format(
        filename, checksum_algorithm.upper(), checksum_value
    ))
    return url


def download(url, path, checksums, records, label):
    result = subprocess.run(
        ["curl", "-fLsS", "--retry", "0", "-o", str(path), url], check=False
    )
    if result.returncode != 0:
        path.unlink(missing_ok=True)
        raise RuntimeError("Download failed for {}: {}".format(label, url))
    return download_verified_from_file(url, path, checksums, records, label)


def download_first_available(urls, path, checksums, records, label):
    for url in urls:
        result = subprocess.run(
            ["curl", "-fLsS", "--retry", "0", "-o", str(path), url], check=False
        )
        if result.returncode != 0:
            path.unlink(missing_ok=True)
            continue
        return download_verified_from_file(url, path, checksums, records, label)
    raise RuntimeError("No published official {} archive found: {}".format(
        label, ", ".join(urls)
    ))


def update_sdk_package_xml(sdk_root, package_path, version, display_name):
    path = sdk_root / "package.xml"
    if not path.is_file():
        print("No package.xml in {}; source.properties remains authoritative".format(sdk_root))
        return
    major, minor, micro = version.split(".", 2)
    tree = ET.parse(path)
    package = next((node for node in tree.iter()
                    if node.tag.rsplit("}", 1)[-1] == "localPackage"), None)
    if package is None:
        raise RuntimeError("package.xml localPackage missing: {}".format(path))
    package.set("path", package_path)
    revision = next((node for node in package
                     if node.tag.rsplit("}", 1)[-1] == "revision"), None)
    if revision is None:
        raise RuntimeError("package.xml revision missing: {}".format(path))
    namespace = package.tag.split("}", 1)[0] + "}" if "}" in package.tag else ""
    for name, value in (("major", major), ("minor", minor), ("micro", micro)):
        node = next((item for item in revision
                     if item.tag.rsplit("}", 1)[-1] == name), None)
        if node is None:
            node = ET.SubElement(revision, namespace + name)
        node.text = value
    tree.write(path, encoding="utf-8", xml_declaration=True)
    check = ET.parse(path)
    checked_package = next((node for node in check.iter()
                            if node.tag.rsplit("}", 1)[-1] == "localPackage"), None)
    checked_revision = next((node for node in checked_package
                             if node.tag.rsplit("}", 1)[-1] == "revision"), None)
    values = {node.tag.rsplit("}", 1)[-1]: node.text for node in checked_revision}
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
    parser.add_argument("--version", required=True, help="Build Tools package revision")
    parser.add_argument("--platform-tools-version", help="Platform Tools archive/revision; defaults to --version")
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    platform_tools_version = args.platform_tools_version or args.version
    build_tools_version = args.version
    args.output.mkdir(parents=True, exist_ok=True)
    official_checksums, manifest_urls = load_official_archive_checksums()
    download_records = []

    with tempfile.TemporaryDirectory(prefix="sdk-package-") as temp:
        root = Path(temp)
        pt_zip = root / "platform-tools.zip"
        bt_zip = root / "build-tools.zip"
        download(
            f"https://dl.google.com/android/repository/platform-tools_r{platform_tools_version}-linux.zip",
            pt_zip, official_checksums, download_records, "platform-tools",
        )
        # Platform Tools and Build Tools have independent release trains.
        # Prefer an exact matching Build Tools archive, then the official major
        # release archive, followed by published preview archives for that major.
        major = build_tools_version.split(".", 1)[0]
        build_tools_versions = []
        exact = build_tools_version
        parts = exact.split(".")
        if len(parts) == 3 and parts[2] == "0":
            exact = ".".join(parts[:2]) if parts[1] != "0" else parts[0]
        build_tools_versions.append(exact)
        build_tools_versions.append(major)
        build_tools_versions.extend([f"{major}-rc2", f"{major}-rc1"])
        # Keep order while removing duplicate candidates.
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

            # Rewrite metadata only after all custom native binaries are installed.
            update_pkg_revision(pt_root, platform_tools_version)
            update_pkg_revision(bt_root, build_tools_version)
            update_sdk_package_xml(
                pt_root, "platform-tools", platform_tools_version,
                "Android SDK Platform-Tools"
            )
            update_sdk_package_xml(
                bt_root, "build-tools;{}".format(build_tools_version), build_tools_version,
                "Android SDK Build-Tools {}".format(build_tools_version)
            )

            pt_output = args.output / f"platform-tools-{platform_tools_version}-{abi}.tar.gz"
            with tarfile.open(pt_output, "w:gz", compresslevel=9) as archive:
                archive.add(pt_root, arcname="platform-tools")

            bt_output = args.output / f"build-tools-{build_tools_version}-{abi}.zip"
            create_build_tools_zip(bt_root, bt_output, build_tools_version)

            with tarfile.open(pt_output, "r:gz") as archive:
                pt_metadata = archive.extractfile("platform-tools/source.properties")
                if pt_metadata is None or f"Pkg.Revision={platform_tools_version}".encode() not in pt_metadata.read():
                    raise RuntimeError(f"{abi}: platform-tools source.properties has the wrong Pkg.Revision")
                members = set(archive.getnames())
                missing = {
                    f"platform-tools/{name}" for name in GROUPS["platform-tools"]
                } - members
                if missing:
                    raise RuntimeError(f"{abi}: platform-tools archive missing {sorted(missing)}")

            with zipfile.ZipFile(bt_output) as archive:
                bt_metadata = archive.read(f"{build_tools_version}/source.properties")
                if f"Pkg.Revision={build_tools_version}".encode() not in bt_metadata:
                    raise RuntimeError(f"{abi}: build-tools source.properties has the wrong Pkg.Revision")
                members = set(archive.namelist())
                missing = {
                    f"{build_tools_version}/{name}"
                    for name in GROUPS["build-tools"] + GROUPS["others"]
                } - members
                if missing:
                    raise RuntimeError(f"{abi}: build-tools archive missing {sorted(missing)}")

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
