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
        # Legacy repository manifests retain checksums for historical archives.
        "https://dl.google.com/android/repository/repository-12.xml",
        "https://dl.google.com/android/repository/repository-11.xml",
        "https://dl.google.com/android/repository/repository2-3.xml",
        "https://dl.google.com/android/repository/repository2-2.xml",
        "https://dl.google.com/android/repository/repository2-1.xml",
    )
    checksums, loaded = {}, []
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
    # Exact bytes observed from Google's official HTTPS archive endpoint on
    # 2026-11-26. SHA-1/SHA-256 were computed locally and ZIP CRC passed.
    # These are observed-download pins, not hashes claimed to be published by Google.
    observed_google_download_checksums = {
        "platform-tools_r28.0.0-linux.zip": ("f944e69bc96ad2984a7e19febb3f3569b216699f", 5469856, "https://dl.google.com/android/repository/platform-tools_r28.0.0-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
        "platform-tools_r28.0.1-linux.zip": ("74ff83bc203f01c4f04bd9316ab5a2573f023fd1", 6843966, "https://dl.google.com/android/repository/platform-tools_r28.0.1-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
        "platform-tools_r28.0.2-linux.zip": ("46a4c02a9b8e4e2121eddf6025da3c979bf02e28", 11850727, "https://dl.google.com/android/repository/platform-tools_r28.0.2-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
        "platform-tools_r28.0.3-linux.zip": ("3d39beebda1ee919520077ebc8f7694e1c6d6e41", 11825449, "https://dl.google.com/android/repository/platform-tools_r28.0.3-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
        "platform-tools_r29.0.0-linux.zip": ("0561e28beb79b93cb46babeccf42be41ee2b4553", 12343021, "https://dl.google.com/android/repository/platform-tools_r29.0.0-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
        "platform-tools_r29.0.1-linux.zip": ("698e43552531f92f7662f7cb1a47d0fd89adfb21", 12343049, "https://dl.google.com/android/repository/platform-tools_r29.0.1-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
        "platform-tools_r29.0.2-linux.zip": ("d9ec5649a286a5af8220eea495572a5c4c49cb03", 12385966, "https://dl.google.com/android/repository/platform-tools_r29.0.2-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
        "platform-tools_r29.0.3-linux.zip": ("9a4ca208b5ddfdfc542922f0ce21063a9e4af595", 8737802, "https://dl.google.com/android/repository/platform-tools_r29.0.3-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
        "platform-tools_r29.0.4-linux.zip": ("a266af09893d9005d887e5f788ddb68f006ccd3e", 8738007, "https://dl.google.com/android/repository/platform-tools_r29.0.4-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
        "platform-tools_r29.0.5-linux.zip": ("2016a7e8f3f696583c0069881f4270365e247cd7", 8116675, "https://dl.google.com/android/repository/platform-tools_r29.0.5-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
        "platform-tools_r29.0.6-linux.zip": ("e95ed28330406705d47fe96bafb589be6c1f2f23", 8254604, "https://dl.google.com/android/repository/platform-tools_r29.0.6-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
        "platform-tools_r30.0.2-linux.zip": ("8f54b7c1abeed2599d418bb623773e4fb3c0697b", 9238635, "https://dl.google.com/android/repository/platform-tools_r30.0.2-linux.zip (observed 2026-11-26; local SHA-1/SHA-256; ZIP CRC passed)"),
    }
    checksums.update(observed_google_download_checksums)

    if not checksums:
        raise RuntimeError("No official Google SDK archive checksums could be loaded")
    return checksums, loaded


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_download(url, path, checksums, downloads, label):
    filename = url.split("?", 1)[0].rsplit("/", 1)[-1]
    official = checksums.get(filename)
    if official is None:
        path.unlink(missing_ok=True)
        raise RuntimeError("No Google-published checksum for {}".format(filename))
    expected_sha1, expected_size, manifest_url = official
    if path.stat().st_size != expected_size:
        raise RuntimeError("{} size mismatch: expected {}, got {}".format(
            filename, expected_size, path.stat().st_size
        ))
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha1 = digest.hexdigest()
    if actual_sha1 != expected_sha1:
        raise RuntimeError("{} SHA-1 mismatch: expected {}, got {}".format(
            filename, expected_sha1, actual_sha1
        ))
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError("{} contains corrupt ZIP member {}".format(filename, bad))
    downloads.append({
        "component": label, "url": url, "filename": filename,
        "size": path.stat().st_size, "verified_sha1": expected_sha1,
        "downloaded_sha256": sha256_file(path), "checksum_source": manifest_url,
        "checksum_provenance": (
            "locally_computed_from_official_google_https_download"
            if "observed 2026-11-26" in manifest_url
            else "google_repository_manifest"
        ),
    })
    print("Verified Google archive {} SHA-1={}".format(filename, actual_sha1))


def download(url, path, checksums, downloads, label):
    subprocess.run(
        ["curl", "-fL", "--retry", "3", "--retry-all-errors", "-o", str(path), url],
        check=True,
    )
    if not zipfile.is_zipfile(path):
        path.unlink(missing_ok=True)
        raise RuntimeError("Invalid Google SDK ZIP: " + url)
    verify_download(url, path, checksums, downloads, label)


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
    lock_path = Path("source-lock.json")
    if not lock_path.is_file():
        raise RuntimeError("source-lock.json missing; refusing to publish without exact source revisions")
    source_path = output_dir / "OFFICIAL-SOURCES.json"
    source_path.write_text(json.dumps({
        "schema_version": 1,
        "source_lock": json.loads(lock_path.read_text(encoding="utf-8")),
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
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    # Platform Tools and Build Tools have independent release trains.
    # Google published Build Tools 34.0.0, but not 34.0.1/34.0.3/34.0.4/34.0.5.
    build_tools_version = args.build_tools_version
    if build_tools_version is None:
        if args.version.startswith("31.0."):
            # Platform Tools 31.0.0-31.0.3 share the single official
            # Android SDK Build Tools 31.0.0 package.
            build_tools_version = "31.0.0"
        elif args.version.startswith("34.0."):
            build_tools_version = "34.0.0"
        elif args.version in ("29.0.4", "29.0.5", "29.0.6"):
            # Google published Build Tools through 29.0.3; Platform Tools
            # 29.0.4-29.0.6 must reuse that official package baseline.
            build_tools_version = "29.0.3"
        elif args.version == "33.0.4":
            # Google published Platform Tools 33.0.3 and Build Tools 33.0.3,
            # but no 33.0.4 binary packages. Repack the latest official 33.0.3
            # base while retaining this branch's native binaries and metadata.
            build_tools_version = "33.0.3"
        else:
            build_tools_version = args.version
    args.output.mkdir(parents=True, exist_ok=True)
    official_checksums, manifest_urls = load_official_archive_checksums()
    download_records = []

    with tempfile.TemporaryDirectory(prefix="sdk-package-") as temp:
        root = Path(temp)
        pt_zip = root / "platform-tools.zip"
        bt_zip = root / "build-tools.zip"
        # Platform Tools 33.0.4 is a source-branch version only; Google's
        # last official binary package in this release line is 33.0.3.
        platform_tools_archive_version = (
            "33.0.3" if args.version == "33.0.4" else args.version
        )
        download(
            f"https://dl.google.com/android/repository/platform-tools_r{platform_tools_archive_version}-linux.zip",
            pt_zip, official_checksums, download_records, "platform-tools",
        )
        # Google omits the trailing .0.0 in the archive filename for
        # the initial major Build Tools release (for example, 35.0.0 is
        # published as build-tools_r35_linux.zip). Patch releases retain
        # their full version in the filename (35.0.1 -> build-tools_r35.0.1_linux.zip).
        build_tools_archive_version = build_tools_version
        if build_tools_version.endswith(".0.0"):
            build_tools_archive_version = build_tools_version.rsplit(".", 2)[0]
        download(
            f"https://dl.google.com/android/repository/build-tools_r{build_tools_archive_version}-linux.zip",
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
            normalize_source_properties(bt_root, build_tools_version)

            pt_output = args.output / f"platform-tools-{args.version}-{abi}.tar.gz"
            with tarfile.open(pt_output, "w:gz", compresslevel=9) as archive:
                archive.add(pt_root, arcname="platform-tools")

            bt_output = args.output / f"build-tools-{build_tools_version}-{abi}.zip"
            create_build_tools_zip(bt_root, bt_output, build_tools_version)

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
                    f"{build_tools_version}/{name}"
                    for name in GROUPS["build-tools"] + GROUPS["others"]
                } - members
                if missing:
                    raise RuntimeError(f"{abi}: build-tools archive missing {sorted(missing)}")

            with tarfile.open(pt_output, "r:gz") as archive:
                metadata = archive.extractfile("platform-tools/source.properties")
                if metadata is None or f"Pkg.Revision={args.version}" not in metadata.read().decode("utf-8").splitlines():
                    raise RuntimeError(f"{abi}: Platform Tools source.properties version mismatch")

            with zipfile.ZipFile(bt_output) as archive:
                metadata = archive.read(f"{build_tools_version}/source.properties").decode("utf-8").splitlines()
                if f"Pkg.Revision={build_tools_version}" not in metadata:
                    raise RuntimeError(f"{abi}: Build Tools source.properties version mismatch")

            verify_tar_gz(pt_output)
            with zipfile.ZipFile(bt_output) as archive:
                bad = archive.testzip()
                if bad:
                    raise RuntimeError("{}: corrupt final Build Tools ZIP member: {}".format(abi, bad))

            print(f"created {pt_output}")
            print(f"created {bt_output}")


    write_integrity_manifests(args.output, manifest_urls, download_records)

if __name__ == "__main__":
    main()
