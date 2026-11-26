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
    "29.0.4", "29.0.5", "29.0.6",
)
BASE = "https://dl.google.com/android/repository/platform-tools_r{}-linux.zip"


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
    results = []
    for version in VERSIONS:
        try:
            result = inspect(version)
            results.append(result)
            print(json.dumps(result, sort_keys=True))
        except Exception as error:
            failure = {"version": version, "error": str(error)}
            print(json.dumps(failure, sort_keys=True))
            raise
    print("ARCHIVE_CHECKSUM_RESULTS=" + json.dumps(results, sort_keys=True))


if __name__ == "__main__":
    main()
