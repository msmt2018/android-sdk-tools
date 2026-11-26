#!/usr/bin/env python3
"""Bootstrap immutable checksums from official Google HTTPS archives.

This is a one-time provenance task for historical archives whose original
repository XML is no longer available from Google's live manifest endpoints.
It does not assert that the computed hashes were published by Google.
"""
import hashlib
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSIONS = (
    "28.0.0", "28.0.1", "28.0.2", "28.0.3",
    "29.0.0", "29.0.1", "29.0.2", "29.0.3",
    "29.0.4", "29.0.5", "29.0.6", "30.0.2",
    "33.0.4", "34.0.3", "36.1.0",
)
BASE = "https://dl.google.com/android/repository/platform-tools_r{}-linux.zip"

MANIFESTS = (
    "https://dl.google.com/android/repository/repository-12.xml",
    "https://dl.google.com/android/repository/repository-11.xml",
    "https://dl.google.com/android/repository/repository2-1.xml",
)


def inspect_historical_manifests():
    expected = {
        BASE.format(version).rsplit("/", 1)[-1]
        for version in VERSIONS
    }
    expected.update(
        "platform-tools_r{}.0.0-linux.zip".format(v)
        for v in ("28", "29", "30", "31", "32", "33", "34", "35", "36", "37")
    )
    records = []
    for url in MANIFESTS:
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "android-sdk-tools-archive-audit/1.0"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                root = __import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(response.read())
            for complete in root.iter():
                if complete.tag.rsplit("}", 1)[-1] != "complete":
                    continue
                fields = {node.tag.rsplit("}", 1)[-1]: node for node in complete}
                url_node = fields.get("url")
                checksum_node = fields.get("checksum")
                size_node = fields.get("size")
                if url_node is None or checksum_node is None or size_node is None:
                    continue
                filename = url_node.text.rsplit("/", 1)[-1]
                if filename not in expected:
                    continue
                if checksum_node.attrib.get("type", "sha1").lower() not in ("sha1", "sha-1"):
                    continue
                records.append({
                    "manifest": url,
                    "filename": filename,
                    "sha1": checksum_node.text.strip().lower(),
                    "size": int(size_node.text.strip()),
                })
        except Exception as error:
            print(json.dumps({"manifest": url, "status": "unavailable", "error": str(error)}, sort_keys=True))
    print("HISTORICAL_GOOGLE_MANIFEST_CHECKSUMS=" + json.dumps(records, sort_keys=True))
    return records


def inspect(version):
    url = BASE.format(version)
    request = urllib.request.Request(url, headers={"User-Agent": "android-sdk-tools-archive-audit/1.0"})
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    size = 0
    with tempfile.TemporaryDirectory(prefix="google-platform-tools-") as temp:
        archive = Path(temp) / "archive.zip"
        with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                size += len(chunk)
                sha1.update(chunk)
                sha256.update(chunk)
        with zipfile.ZipFile(archive) as zf:
            bad_member = zf.testzip()
            members = len(zf.infolist())
            if bad_member is not None:
                raise RuntimeError("{} has corrupt ZIP member {}".format(version, bad_member))
    return {
        "version": version,
        "url": url,
        "http": "success",
        "size": size,
        "sha1": sha1.hexdigest(),
        "sha256": sha256.hexdigest(),
        "zip_members": members,
        "zip_crc": "passed",
        "checksum_provenance": "computed locally from the official dl.google.com HTTPS download",
    }


def main():
    inspect_historical_manifests()
    results = []
    failures = []
    for version in VERSIONS:
        try:
            result = inspect(version)
            results.append(result)
            print(json.dumps(result, sort_keys=True))
        except Exception as error:
            failure = {"version": version, "status": "unavailable_or_invalid", "error": str(error)}
            failures.append(failure)
            print(json.dumps(failure, sort_keys=True))
    print("ARCHIVE_CHECKSUM_RESULTS=" + json.dumps(results, sort_keys=True))
    print("ARCHIVE_CHECKSUM_FAILURES=" + json.dumps(failures, sort_keys=True))


if __name__ == "__main__":
    main()
