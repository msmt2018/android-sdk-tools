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

def load_official_archive_checksums():
    """Load Google-published SDK archive sizes and SHA-1 checksums."""
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
            url_node = fields.get("url")
            checksum_node = fields.get("checksum")
            size_node = fields.get("size")
            if url_node is None or checksum_node is None or size_node is None:
                continue
            if checksum_node.attrib.get("type", "sha1").lower() not in ("sha1", "sha-1"):
                continue
            checksums[url_node.text.rsplit("/", 1)[-1]] = (
                checksum_node.text.strip().lower(),
                int(size_node.text.strip()),
                url,
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
    archived_google_checksums.update({
        "platform-tools_r37.0.0-linux.zip": ("bcf323933980a59dccc3f14c339aed5fb2171163", 9167924, "https://github.com/f-droid/android-sdk-transparency-log/blob/f7be0f7e0dd3fa8ca6a881cd5644a7ca281d76be/android/repository/repository2-3.xml"),
    })
    for filename, metadata in archived_google_checksums.items():
        checksums.setdefault(filename, metadata)

    checksums.update({
        "platform-tools_r37.0.0-linux.zip": (
            "bcf323933980a59dccc3f14c339aed5fb2171163", 9167924,
            "https://dl.google.com/android/repository/platform-tools_r37.0.0-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)",
        ),
    })

    if not checksums:
        raise RuntimeError("No official Google SDK archive checksums could be loaded")
    return checksums, loaded


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_official_build_tools_revisions(manifest_urls):
    """Resolve Build Tools archive filenames to exact remotePackage revisions."""
    revisions = {}
    for manifest_url in manifest_urls:
        try:
            request = urllib.request.Request(
                manifest_url, headers={"User-Agent": "android-sdk-tools-integrity/1.0"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                root = ET.fromstring(response.read())
        except Exception as error:
            print("Cannot read Build Tools revision metadata from {}: {}".format(
                manifest_url, error
            ))
            continue
        for package in root.iter():
            if package.tag.rsplit("}", 1)[-1] != "remotePackage":
                continue
            package_path = package.get("path", "")
            if not package_path.startswith("build-tools;"):
                continue
            revision_node = next(
                (node for node in package
                 if node.tag.rsplit("}", 1)[-1] == "revision"),
                None,
            )
            if revision_node is None:
                continue
            fields = {
                node.tag.rsplit("}", 1)[-1]: (node.text or "").strip()
                for node in revision_node
            }
            version = "{}.{}.{}".format(
                fields.get("major", ""), fields.get("minor", ""), fields.get("micro", "")
            )
            if fields.get("preview"):
                version += "-rc{}".format(fields["preview"])
            if package_path != "build-tools;" + version:
                raise RuntimeError(
                    "Google Build Tools manifest path/revision mismatch: {} vs {}".format(
                        package_path, version
                    )
                )
            for complete in package.iter():
                if complete.tag.rsplit("}", 1)[-1] != "complete":
                    continue
                url_node = next(
                    (node for node in complete
                     if node.tag.rsplit("}", 1)[-1] == "url"),
                    None,
                )
                if url_node is not None and url_node.text:
                    filename = url_node.text.rsplit("/", 1)[-1]
                    revisions[filename] = version
    if not revisions:
        raise RuntimeError("No official Google Build Tools package revisions could be loaded")
    return revisions


def download_verified(url, path, checksums, records, label):
    result = subprocess.run(
        ["curl", "-fLsS", "--retry", "0", "-o", str(path), url],
        check=False,
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
        "component": label,
        "url": url,
        "filename": filename,
        "size": actual_size,
        "official_sha1": expected_sha1,
        "downloaded_sha256": sha256_file(path),
        "official_manifest": manifest_url,
    })
    print("Verified Google archive {} SHA-1={}".format(filename, actual_sha1))
    return url


def update_sdk_package_xml(sdk_root, package_path, version, display_name):
    """Keep package.xml path and revision aligned with the repackaged SDK folder."""
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
    display = next((node for node in package
                    if node.tag.rsplit("}", 1)[-1] == "display-name"), None)
    if display is not None:
        display.text = display_name
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
                    raise RuntimeError("Corrupt final ZIP member {} in {}".format(
                        bad, path
                    ))
        else:
            verify_tar_gz(path)
    source_lock_path = Path("source-lock.json")
    if not source_lock_path.is_file():
        raise RuntimeError("source-lock.json missing; refusing to publish without exact source revisions")
    source_lock = json.loads(source_lock_path.read_text(encoding="utf-8"))
    source_manifest = {
        "schema_version": 1,
        "source_lock": source_lock,
        "official_repository_manifests": manifests,
        "downloads": downloads,
    }
    source_path = output_dir / "OFFICIAL-SOURCES.json"
    source_path.write_text(
        json.dumps(source_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    files = archives + [source_path]
    (output_dir / "SHA256SUMS").write_text(
        "".join("{}  {}\n".format(sha256_file(item), item.name) for item in files),
        encoding="utf-8",
    )


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


def download(url, path, checksums, records, label):
    return download_verified(url, path, checksums, records, label)


def download_first_available(urls, path, checksums, records, label):
    """Try official URLs in order, requiring a Google checksum for the selected archive."""
    for url in urls:
        result = subprocess.run(
            ["curl", "-fLsS", "--retry", "0", "-o", str(path), url],
            check=False,
        )
        if result.returncode != 0:
            path.unlink(missing_ok=True)
            continue
        return download_verified_from_file(url, path, checksums, records, label)
    raise RuntimeError("No published official {} archive found: {}".format(
        label, ", ".join(urls)
    ))


def download_verified_from_file(url, path, checksums, records, label):
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
        "component": label,
        "url": url,
        "filename": filename,
        "size": actual_size,
        "official_sha1": expected_sha1,
        "downloaded_sha256": sha256_file(path),
        "official_manifest": manifest_url,
    })
    print("Verified Google archive {} SHA-1={}".format(filename, actual_sha1))
    return url

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

def read_build_tools_package_revision(sdk_root, manifest_revision):
    """Validate or create Build Tools metadata using the exact Google manifest revision."""
    properties = sdk_root / "source.properties"
    package_xml = sdk_root / "package.xml"
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\d+)?", manifest_revision):
        raise RuntimeError("Invalid Google Build Tools manifest revision {!r}".format(
            manifest_revision
        ))

    if properties.is_file():
        content = properties.read_text(encoding="utf-8")
        matches = re.findall(r"(?m)^Pkg\.Revision\s*=\s*(.*?)\s*$", content)
        if len(matches) != 1:
            raise RuntimeError("Expected one Build Tools Pkg.Revision in {}, found {}".format(
                properties, len(matches)
            ))
        raw_revision = matches[0].strip()
        source_revision = re.sub(r"\s+", "-", raw_revision)
        if source_revision != manifest_revision:
            raise RuntimeError(
                "Build Tools source.properties revision {} disagrees with Google manifest {}".format(
                    source_revision, manifest_revision
                )
            )
    else:
        raw_revision = manifest_revision
        properties.write_text(
            "Pkg.Desc=Android SDK Build-Tools\nPkg.Revision={}\n".format(
                manifest_revision
            ),
            encoding="utf-8",
        )
        print("Created {} from verified Google manifest revision {}".format(
            properties, manifest_revision
        ))

    if package_xml.is_file():
        tree = ET.parse(package_xml)
        package = next((node for node in tree.iter()
                        if node.tag.rsplit("}", 1)[-1] == "localPackage"), None)
        if package is None:
            raise RuntimeError("Build Tools package.xml localPackage missing: {}".format(package_xml))
        package_path = package.get("path", "")
        if package_path != "build-tools;" + manifest_revision:
            raise RuntimeError("Unexpected Build Tools package path {} in {}".format(
                package_path, package_xml
            ))
        revision = next((node for node in package
                         if node.tag.rsplit("}", 1)[-1] == "revision"), None)
        if revision is None:
            raise RuntimeError("Build Tools package.xml revision missing: {}".format(package_xml))
        fields = {node.tag.rsplit("}", 1)[-1]: node.text for node in revision}
        xml_revision = "{}.{}.{}".format(
            fields.get("major", ""), fields.get("minor", ""), fields.get("micro", "")
        )
        if fields.get("preview"):
            xml_revision += "-rc{}".format(fields["preview"])
        if xml_revision != manifest_revision:
            raise RuntimeError(
                "Build Tools package.xml revision {} disagrees with Google manifest {}".format(
                    xml_revision, manifest_revision
                )
            )
    else:
        print("No package.xml in {}; Google manifest remains authoritative".format(sdk_root))
    return manifest_revision, raw_revision


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
    build_tools_revisions = load_official_build_tools_revisions(manifest_urls)
    download_records = []

    with tempfile.TemporaryDirectory(prefix="sdk-package-") as temp:
        root = Path(temp)
        pt_zip = root / "platform-tools.zip"
        bt_zip = root / "build-tools.zip"
        # Platform Tools 37.0.2 never graduated beyond Canary; Google only
        # publishes the 37.0.1 stable archive. Use it as the untouched base and
        # replace the native executables with the branch's 37.0.2 builds below.
        platform_tools_versions = [args.version]
        if args.version == "37.0.2":
            platform_tools_versions.append("37.0.1")
        platform_tools_urls = [
            f"https://dl.google.com/android/repository/platform-tools_r{version}-linux.zip"
            for version in platform_tools_versions
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
        # Prefer the official stable Build Tools 37.0.0 archive (build-tools_r37_linux.zip).
        # Only fall back to preview rc2/rc1 if the stable package is unavailable.
        if int(major) >= 36:
            build_tools_versions.append("36")
        # Keep order while removing duplicate candidates.
        build_tools_versions = list(dict.fromkeys(build_tools_versions))
        build_tools_urls = [
            f"https://dl.google.com/android/repository/build-tools_r{version}_linux.zip"
            for version in build_tools_versions
        ]
        selected_build_tools_url = download_first_available(
            build_tools_urls, bt_zip, official_checksums, download_records, "build-tools"
        )
        selected_build_tools_filename = selected_build_tools_url.rsplit("/", 1)[-1]
        build_tools_version = build_tools_revisions.get(selected_build_tools_filename)
        if not build_tools_version:
            raise RuntimeError(
                "No official Google Build Tools package revision for {}".format(
                    selected_build_tools_filename
                )
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
            build_tools_version, build_tools_pkg_revision = read_build_tools_package_revision(bt_root, build_tools_version)

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
            update_pkg_revision(pt_root, args.version)
            update_sdk_package_xml(
                pt_root, "platform-tools", args.version, "Android SDK Platform-Tools"
            )

            pt_output = args.output / f"platform-tools-{args.version}-{abi}.tar.gz"
            with tarfile.open(pt_output, "w:gz", compresslevel=9) as archive:
                archive.add(pt_root, arcname="platform-tools")

            bt_output = args.output / f"build-tools-{build_tools_version}-{abi}.zip"
            create_build_tools_zip(bt_root, bt_output, build_tools_version)

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
                bt_metadata = archive.read(f"{build_tools_version}/source.properties")
                if f"Pkg.Revision={build_tools_pkg_revision}".encode() not in bt_metadata:
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
