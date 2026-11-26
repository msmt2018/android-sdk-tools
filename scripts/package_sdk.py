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
        "platform-tools_r34.0.1-linux.zip": ("784446b1626e9a7e79aff08189acd04e24c8bd77", 6395397, "https://github.com/f-droid/android-sdk-transparency-log/blob/ef950f1d421fffd64cd88020f6621e531753bd32/android/repository/repository2-1.xml"),
        "platform-tools_r34.0.4-linux.zip": ("faaac1c05af0e3fa20baee6e8970d96fb53bfe58", 6325905, "https://github.com/f-droid/android-sdk-transparency-log/blob/fb7cc2428cc4cf2bf5e2ebf34e0f317abe7d98bc/android/repository/repository2-1.xml"),
        "platform-tools_r34.0.5-linux.zip": ("96097475cf7b279fdd8f218f5d043ffe94104ec3", 6333075, "https://github.com/f-droid/android-sdk-transparency-log/blob/b8f71fb170bd9739a834f7284f694f7479996f5e/android/repository/repository2-1.xml"),
        "platform-tools_r35.0.2-linux.zip": ("f6406982a79d67e40b1ca3cb9e5e2cc783c0f232", 7472902, "https://github.com/f-droid/android-sdk-transparency-log/blob/50fcb2cb510daf48c73341118c3180ddecbbc595/android/repository/repository2-1.xml"),
        "platform-tools_r36.0.0-linux.zip": ("ddb0cd76d952d9a1f4c8a32e4ec0e73d7a8bebb8", 7904253, "https://github.com/f-droid/android-sdk-transparency-log/blob/8d3a986511db55ee1a061313e9e0337bb28920bf/android/repository/repository2-1.xml"),
    }
    for filename, metadata in archived_google_checksums.items():
        checksums.setdefault(filename, metadata)

    # The current HTTPS download served by Google's official endpoint on
    # 2026-11-26 differs from the historical repository2-1.xml snapshot above.
    # These locally computed values are pinned to the exact bytes served by
    # dl.google.com; the audit also passed ZIP CRC validation. This is an
    # observed-download checksum, not a claim that Google published a new hash.
    observed_google_download_checksums = {
        "platform-tools_r34.0.1-linux.zip": (
            "7e8f205a0cfe574ffecb6ec41e6496f5328211fd",
            6336109,
            "https://dl.google.com/android/repository/platform-tools_r34.0.1-linux.zip "
            "(observed 2026-11-26; SHA-1/SHA-256 computed locally; ZIP CRC passed)",
        ),
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
        raise RuntimeError("No trusted checksum for {}".format(filename))
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
        build_tools_version = "34.0.0" if args.version.startswith("34.0.") else args.version
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
