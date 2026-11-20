#!/usr/bin/env python3
#
# Copyright © 2022 Github Lzhiyong
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# pylint: disable=not-callable, line-too-long, no-else-return

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION_HEADER = ROOT / 'patches/misc/platform_tools_version.h'


def tools_version():
    """read PLATFORM_TOOLS_VERSION from patches/misc/platform_tools_version.h"""
    text = VERSION_HEADER.read_text()
    match = re.search(r'^\s*#define\s+PLATFORM_TOOLS_VERSION\s+"([^"]+)"', text, re.M)
    if match is None:
        sys.exit('can not find PLATFORM_TOOLS_VERSION in {}'.format(VERSION_HEADER))
    return match.group(1)


def check(command):
    if shutil.which(command) is None:
        sys.exit('please install the {} package'.format(command))


# Platform-tools 28.0.x and 29.0.0 predate the release-specific manifest refs.
# These are the nearest official Google source snapshots at the corresponding
# release points; all project revisions are then taken from that manifest.
MANIFEST_TAG_OVERRIDES = {
    '28.0.0': 'android-p-preview-4',
    '28.0.1': 'android-9.0.0_r1',
    '28.0.2': 'android-9.0.0_r33',
    '29.0.0': 'android-q-preview-5',
}


def manifest_tag_for(version, requested_tag):
    return MANIFEST_TAG_OVERRIDES.get(version, requested_tag)


def resolve_manifest_revisions(repos, release_tag, retries):
    version = tools_version()
    manifest_tag = manifest_tag_for(version, release_tag)
    manifest_dir = ROOT / '.aosp-manifest'
    shutil.rmtree(manifest_dir, ignore_errors=True)
    command = [
        'git', 'clone', '-q', '-c', 'advice.detachedHead=false',
        '--depth', '1', '--branch', manifest_tag,
        'https://android.googlesource.com/platform/manifest',
        str(manifest_dir),
    ]
    result = None
    for attempt in range(1, retries + 1):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            break
        shutil.rmtree(manifest_dir, ignore_errors=True)
        if attempt < retries:
            time.sleep(5 * attempt)
    if result is None or result.returncode != 0:
        raise RuntimeError('failed to fetch Google platform manifest tag {}:\n{}'.format(
            manifest_tag, result.stderr if result else 'no git result'))

    manifest_file = manifest_dir / 'default.xml'
    if not manifest_file.is_file():
        raise RuntimeError('Google manifest tag {} has no default.xml'.format(manifest_tag))
    root = ET.parse(str(manifest_file)).getroot()
    default = root.find('default')
    if default is None:
        raise RuntimeError('Google manifest {} has no default revision'.format(manifest_tag))
    default_revision = default.get('revision')

    projects = {}
    for project in root.findall('project'):
        name = project.get('name')
        if not name:
            continue
        revision = project.get('revision') or default_revision
        if revision:
            projects[name] = revision

    resolved = []
    missing = []
    for repo in repos:
        # Third-party sources with an explicit pin retain that exact pin.
        if repo.get('branch'):
            resolved.append(repo)
            continue
        prefix = 'https://android.googlesource.com/'
        url = repo.get('url', '')
        if not url.startswith(prefix):
            missing.append('{} (non-AOSP URL without explicit branch)'.format(url))
            continue
        project_name = url[len(prefix):]
        revision = projects.get(project_name)
        if revision is None:
            missing.append(project_name)
            continue
        item = dict(repo)
        item['branch'] = revision.removeprefix('refs/tags/').removeprefix('refs/heads/')
        resolved.append(item)

    print('Google source manifest: {} (release tag {})'.format(manifest_tag, release_tag), flush=True)
    print('Resolved {} AOSP projects; absent from this snapshot: {}'.format(
        len(resolved), ', '.join(missing) if missing else 'none'), flush=True)
    return resolved


def clone(repo, default_branch, retries):
    path = ROOT / repo['path']
    if path.exists():
        return '{} already exists, skip'.format(repo['path'])
    # a repo can pin its own branch/tag (e.g. zlib), otherwise use the AOSP tag
    branch = repo.get('branch', default_branch)
    command = ['git', 'clone', '-q', '-c', 'advice.detachedHead=false',
               '--depth', '1', '--branch', branch, repo['url'], str(path)]
    for attempt in range(1, retries + 1):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            return 'cloned {} ({})'.format(repo['path'], branch)
        shutil.rmtree(path, ignore_errors=True)
        if attempt < retries:
            time.sleep(5 * attempt)
    raise RuntimeError('failed to clone {} ({}):\n{}'.format(repo['url'], branch, result.stderr))


def replace_in_file(path, old, new):
    path = ROOT / path
    if path.exists():
        text = path.read_text()
        if old in text:
            path.write_text(text.replace(old, new))


def apply_patch(patch):
    """apply a patch file if it is applicable, the patch files of this project
    use different path prefixes, so try both the project root and src/"""
    for workdir in (ROOT, ROOT / 'src'):
        base = ['patch', '-p1', '-s', '-f', '-d', str(workdir), '-i', str(patch)]
        if subprocess.run(base + ['-N', '--dry-run'], capture_output=True).returncode == 0:
            subprocess.run(base + ['-N'], check=True)
            return 'applied'
        if subprocess.run(base + ['-R', '--dry-run'], capture_output=True).returncode == 0:
            return 'already applied'
    return 'not applicable for this version, skipped'


def ensure_art_build_defines():
    """Keep ART's stack/frame limits available in standalone NDK builds.

    The upstream Soong build normally injects these target-specific defines.
    This project builds ART sources outside Soong, so provide the same
    conservative values in the shared header when they are absent.
    """
    path = ROOT / 'src/art/libartbase/arch/instruction_set.h'
    if not path.exists():
        raise RuntimeError('ART instruction_set.h not found: {}'.format(path))

    text = path.read_text()
    marker = 'namespace art {'
    if marker not in text:
        raise RuntimeError('cannot locate namespace art in {}'.format(path))

    definitions = {
        'ART_STACK_OVERFLOW_GAP_arm': 16384,
        'ART_STACK_OVERFLOW_GAP_arm64': 16384,
        'ART_STACK_OVERFLOW_GAP_riscv64': 16384,
        'ART_STACK_OVERFLOW_GAP_x86': 16384,
        'ART_STACK_OVERFLOW_GAP_x86_64': 20480,
        'ART_FRAME_SIZE_LIMIT': 10000,
    }
    # Ignore commented-out Soong examples: they contain the same #define
    # spellings but do not provide macros to the C++ preprocessor.
    active_text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)

    missing = []
    for name, value in definitions.items():
        if not re.search(r'^\s*#\s*define\s+' + re.escape(name) + r'\b', active_text, re.M):
            missing.append('#ifndef {}\n#define {} {}\n#endif'.format(name, name, value))

    if missing:
        block = (
            '// Standalone NDK build equivalents of the defines normally supplied by Soong.\n'
            + '\n'.join(missing)
            + '\n\n'
        )
        text = text.replace(marker, block + marker, 1)
        path.write_text(text)
        print('ART standalone build defines: added {}'.format(', '.join(
            name for name in definitions if name not in active_text)), flush=True)

        # Fail early if a required definition is still absent after editing.
        verified = re.sub(r'/\*.*?\*/|//[^\n]*', '', path.read_text(), flags=re.S)
        unresolved = [
            name for name in definitions
            if not re.search(r'^\s*#\s*define\s+' + re.escape(name) + r'\b', verified, re.M)
        ]
        if unresolved:
            raise RuntimeError('failed to add ART build defines: {}'.format(', '.join(unresolved)))
    else:
        print('ART standalone build defines: already present', flush=True)



def ensure_openscreen_task_runner_compat():
    """Avoid libc++'s unsupported packaged_task<void() noexcept> specialization.

    NDK r27c's libc++ does not provide this specialization when compiling
    Open Screen with the standalone NDK toolchain. AOSP's existing patch may
    not match every platform-tools tag, so normalize the alias after patches.
    """
    path = ROOT / 'src/openscreen/platform/api/task_runner.h'
    if not path.exists():
        raise RuntimeError('Open Screen task_runner.h not found: {}'.format(path))

    text = path.read_text()
    fixed = re.sub(
        r'std::packaged_task\s*<\s*void\s*\(\s*\)\s*noexcept\s*>',
        'std::packaged_task<void()>',
        text,
    )
    if fixed != text:
        path.write_text(fixed)
        print('Open Screen standalone build: normalized packaged_task<void() noexcept>', flush=True)

    verified = path.read_text()
    if 'std::packaged_task<void()>' not in verified:
        raise RuntimeError('Open Screen Task alias is not compatible with NDK libc++: {}'.format(path))
    if 'std::packaged_task<void() noexcept>' in verified:
        raise RuntimeError('unsupported noexcept packaged_task alias remains in {}'.format(path))



def ensure_art_metrics_memory_order_compat():
    """Normalize malformed ART memory_order enum qualification for libc++."""
    path = ROOT / 'src/art/libartbase/base/metrics/metrics.h'
    if not path.is_file():
        # Older Platform Tools releases predate this ART metrics header.
        # There is no corresponding source to normalize in those snapshots.
        print('ART metrics: metrics.h is not part of this AOSP snapshot; skipping', flush=True)
        return

    text = path.read_text()
    fixed = re.sub(
        r'std::memory_order::(memory_order_(?:relaxed|consume|acquire|release|acq_rel|seq_cst))',
        r'std::\1',
        text,
    )
    if fixed != text:
        path.write_text(fixed)
        print('ART metrics: normalized malformed std::memory_order enumerators', flush=True)

    verified = path.read_text()
    if re.search(r'std::memory_order::memory_order_', verified):
        raise RuntimeError('malformed std::memory_order enumerator remains in {}'.format(path))



def ensure_art_hash_set_allocator_compat():
    """Use allocator_traits instead of allocator members removed in C++20."""
    path = ROOT / 'src/art/libartbase/base/hash_set.h'
    if not path.exists():
        raise RuntimeError('ART hash_set.h not found: {}'.format(path))

    text = path.read_text()
    destroy_pattern = (
        r'allocfn_\.destroy\(\s*allocfn_\.address\(\s*([^()]+?)\s*\)\s*\)\s*;'
    )
    construct_pattern = (
        r'allocfn_\.construct\(\s*allocfn_\.address\(\s*([^()]+?)\s*\)\s*\)\s*;'
    )
    text, destroyed = re.subn(
        destroy_pattern,
        r'std::allocator_traits<allocator_type>::destroy(allocfn_, std::addressof(\1));',
        text,
    )
    text, constructed = re.subn(
        construct_pattern,
        r'std::allocator_traits<allocator_type>::construct(allocfn_, std::addressof(\1));',
        text,
    )
    if destroyed + constructed == 0 and re.search(r'allocfn_\.(?:construct|destroy)\s*\(', text):
        raise RuntimeError('unrecognized legacy allocator calls in {}'.format(path))
    if destroyed + constructed:
        path.write_text(text)
        print(
            'ART HashSet: migrated {} allocator construct and {} destroy calls to allocator_traits'.format(
                constructed, destroyed
            ),
            flush=True,
        )

    verified = path.read_text()
    if re.search(r'allocfn_\.(?:construct|destroy|address)\s*\(', verified):
        raise RuntimeError('C++20-incompatible allocator member remains in {}'.format(path))

def ensure_androidfw_theme_entry_definition():
    """Define Theme::Entry in the header so every translation unit sees a complete type."""
    path = ROOT / 'src/base/libs/androidfw/include/androidfw/AssetManager2.h'
    if not path.is_file():
        raise RuntimeError('Android framework AssetManager2.h not found: {}'.format(path))

    text = path.read_text()
    definition_marker = '  struct Entry {\n    uint32_t attr_res_id;\n    ApkAssetsCookie cookie;'
    if definition_marker not in text:
        declaration = '  struct Entry;'
        if declaration not in text:
            # Older androidfw snapshots may not use the incomplete nested
            # Theme::Entry layout that triggers this standalone-build fix.
            cpp_path = ROOT / 'src/base/libs/androidfw/AssetManager2.cpp'
            if not cpp_path.is_file():
                raise RuntimeError('Android framework AssetManager2.cpp not found: {}'.format(cpp_path))
            cpp_text = cpp_path.read_text()
            if 'struct Theme::Entry' in cpp_text:
                raise RuntimeError('Theme::Entry has an out-of-line definition but no header declaration in {}'.format(path))
            print('androidfw Theme::Entry: legacy source layout; no incomplete nested type to expose, skipping', flush=True)
            return

        definition = (
            '  struct Entry {\n'
            '    uint32_t attr_res_id;\n'
            '    ApkAssetsCookie cookie;\n'
            '    uint32_t type_spec_flags;\n'
            '    Res_value value;\n'
            '  };'
        )
        text = text.replace(declaration, definition, 1)
        path.write_text(text)

    verified = path.read_text()
    if definition_marker not in verified:
        raise RuntimeError('failed to define Theme::Entry in {}'.format(path))

    # The upstream implementation defines this nested type in the .cpp file.
    # Once it is public in the header, remove that out-of-line definition.
    cpp_path = ROOT / 'src/base/libs/androidfw/AssetManager2.cpp'
    if not cpp_path.is_file():
        raise RuntimeError('Android framework AssetManager2.cpp not found: {}'.format(cpp_path))
    cpp_text = cpp_path.read_text()
    cpp_text, removed = re.subn(
        r'\nstruct\s+Theme::Entry\s*\{[^}]*\};\s*',
        '\n',
        cpp_text,
        count=1,
    )
    if removed:
        cpp_path.write_text(cpp_text)

    verified = path.read_text()
    if definition_marker not in verified:
        raise RuntimeError('failed to define Theme::Entry in {}'.format(path))
    print('androidfw Theme::Entry: defined complete nested type in public header', flush=True)



def ensure_aidl_flex_parser_types():
    """Insert Flex/Bison semantic and location aliases even if the parser header is already included."""
    path = ROOT / 'src/aidl/aidl_language_l.ll'
    if not path.is_file():
        raise RuntimeError('AIDL Flex source not found: {}'.format(path))
    text = path.read_text()
    header = '#include "aidl_language_y.h"'
    aliases = (
        '#ifndef YYSTYPE\n#define YYSTYPE yy::parser::semantic_type\n#endif\n'
        '#ifndef YYLTYPE\n#define YYLTYPE yy::parser::location_type\n#endif\n'
    )
    if header not in text:
        prologue = '%{\n'
        if prologue not in text:
            raise RuntimeError('cannot locate Flex prologue in {}'.format(path))
        text = text.replace(prologue, prologue + header + '\n' + aliases, 1)
    elif '#define YYSTYPE yy::parser::semantic_type' not in text or '#define YYLTYPE yy::parser::location_type' not in text:
        text = text.replace(header, header + '\n' + aliases, 1)
    path.write_text(text)
    verified = path.read_text()
    for token in (header, '#define YYSTYPE yy::parser::semantic_type', '#define YYLTYPE yy::parser::location_type'):
        if token not in verified:
            raise RuntimeError('AIDL Flex parser alias missing {} in {}'.format(token, path))
    print('AIDL Flex: parser header and semantic/location aliases verified', flush=True)

def ensure_fastboot_unique_fd_compat():
    """Match fastboot descriptor calls to the descriptor type in this AOSP tag."""
    path = ROOT / 'src/core/fastboot/fastboot.cpp'
    if not path.is_file():
        print('fastboot descriptor compatibility: source absent, skipping', flush=True)
        return

    text = path.read_text()
    # Platform-tools 31.0.x declares these descriptors as int. Some carried
    # patches were written for newer unique_fd snapshots and incorrectly add
    # .get(); undo only those known POSIX/file helper call forms.
    if re.search(r'\bint\s+fd\b', text):
        replacements = (
            ('get_file_size(fd.get())', 'get_file_size(fd)'),
            ('ExtractEntryToFile(zip, &zip_entry, fd.get())', 'ExtractEntryToFile(zip, &zip_entry, fd)'),
            ('lseek(fd.get(), 0, SEEK_SET)', 'lseek(fd, 0, SEEK_SET)'),
            ('fstat(fd.get(), &s)', 'fstat(fd, &s)'),
        )
        changed = 0
        for old, new in replacements:
            count = text.count(old)
            if count:
                text = text.replace(old, new)
                changed += count
        if changed:
            path.write_text(text)
        verified = path.read_text()
        if any(old in verified for old, _ in replacements):
            raise RuntimeError('raw int fastboot descriptor still uses unique_fd .get()')
        print('fastboot descriptor compatibility: restored {} raw-int call(s)'.format(changed), flush=True)
        return

    if not re.search(r'\bunique_fd\s+fd\b', text):
        print('fastboot descriptor compatibility: no fd declaration requiring conversion', flush=True)
        return
    replacements = (
        ('get_file_size(fd)', 'get_file_size(fd.get())'),
        ('ExtractEntryToFile(zip, &zip_entry, fd)', 'ExtractEntryToFile(zip, &zip_entry, fd.get())'),
        ('lseek(fd, 0, SEEK_SET)', 'lseek(fd.get(), 0, SEEK_SET)'),
        ('fstat(fd, &s)', 'fstat(fd.get(), &s)'),
    )
    changed = 0
    for old, new in replacements:
        count = text.count(old)
        if count:
            text = text.replace(old, new)
            changed += count
    if changed:
        path.write_text(text)
    verified = path.read_text()
    if any(old in verified for old, _ in replacements):
        raise RuntimeError('unique_fd fastboot descriptor conversion incomplete')
    print('fastboot descriptor compatibility: converted {} unique_fd call(s)'.format(changed), flush=True)

def ensure_adb_mdns_function_include():
    """Provide the std::function declaration used by adb_mdns.h."""
    path = ROOT / 'src/adb/adb_mdns.h'
    if not path.is_file():
        raise RuntimeError('ADB mdns header not found: {}'.format(path))

    text = path.read_text()
    if '#include <functional>' not in text:
        match = re.search(r'(?m)^#include\s+[<"]', text)
        if not match:
            raise RuntimeError('cannot locate include block in {}'.format(path))
        text = text[:match.start()] + '#include <functional>\n' + text[match.start():]
        path.write_text(text)

    verified = path.read_text()
    if '#include <functional>' not in verified:
        raise RuntimeError('failed to add <functional> to {}'.format(path))
    print('ADB mdns: added required <functional> include', flush=True)



def ensure_adb_tls_function_include():
    """Provide std::function for the TLS callback aliases in tls_connection.h."""
    path = ROOT / 'src/adb/tls/include/adb/tls/tls_connection.h'
    if not path.is_file():
        raise RuntimeError('ADB TLS connection header not found: {}'.format(path))

    text = path.read_text()
    if '#include <functional>' not in text:
        match = re.search(r'(?m)^#include\s+[<"]', text)
        if not match:
            raise RuntimeError('cannot locate include block in {}'.format(path))
        text = text[:match.start()] + '#include <functional>\n' + text[match.start():]
        path.write_text(text)

    verified = path.read_text()
    if '#include <functional>' not in verified:
        raise RuntimeError('failed to add <functional> to {}'.format(path))
    if 'using CertVerifyCb = std::function<int(X509_STORE_CTX*)>;' not in verified:
        raise RuntimeError('ADB TLS CertVerifyCb alias missing from {}'.format(path))
    if 'using SetCertCb = std::function<int(SSL*)>;' not in verified:
        raise RuntimeError('ADB TLS SetCertCb alias missing from {}'.format(path))
    print('ADB TLS: added required <functional> include for callback aliases', flush=True)

def ensure_libziparchive_span_compat():
    """Avoid narrowing std::span extents while remaining compatible with older AOSP snapshots."""
    path = ROOT / 'src/libziparchive/zip_archive.cc'
    if not path.is_file():
        raise RuntimeError('libziparchive zip_archive.cc not found: {}'.format(path))

    text = path.read_text()
    old_forms = (
        'return {buf.first, ssize_t(buf.second)};',
        'return {buf.first, static_cast<ssize_t>(buf.second)};',
    )
    for old in old_forms:
        if old in text:
            text = text.replace(old, 'return {buf.first, buf.second};', 1)
            path.write_text(text)
            break

    verified = path.read_text()
    if 'ssize_t(buf.second)' in verified or 'static_cast<ssize_t>(buf.second)' in verified:
        raise RuntimeError('narrowing ssize_t span extent remains in {}'.format(path))
    if 'return {buf.first, buf.second};' in verified:
        print('libziparchive: std::span extent uses size_t', flush=True)
    else:
        print('libziparchive: no ssize_t span narrowing in this AOSP snapshot', flush=True)


def ensure_boringssl_x509_name_print_compat():
    """Remove the obsolete line counter only when this snapshot still has it."""
    path = ROOT / 'src/boringssl/src/crypto/x509/t_x509.c'
    if not path.is_file():
        raise RuntimeError('BoringSSL X509 source not found: {}'.format(path))

    text = path.read_text()
    match = re.search(
        r'int\s+X509_NAME_print\s*\(\s*BIO\s*\*\s*bp\s*,\s*(?:const\s+)?X509_NAME\s*\*\s*name\s*,\s*int\s+obase\s*\)\s*\{.*?\n\}',
        text,
        re.S,
    )
    if match is None:
        # Some platform-tools snapshots no longer contain this legacy function.
        print('BoringSSL X509_NAME_print: no legacy function in this snapshot', flush=True)
        return

    function = match.group(0)
    fixed = function
    if re.search(r'\bint\s+ret\s*=\s*0\s*,\s*l\s*,\s*i\s*;', fixed):
        fixed = re.sub(r'\bint\s+ret\s*=\s*0\s*,\s*l\s*,\s*i\s*;', 'int ret = 0, i;', fixed, count=1)
    fixed = re.sub(r'(?m)^\s*l\s*=\s*80\s*-\s*2\s*-\s*obase\s*;\s*\n', '', fixed)
    fixed = re.sub(r'(?m)^\s*l--\s*;\s*\n', '', fixed)

    # obase is only unused after removing the obsolete line counter.
    if '(void)obase;' not in fixed and len(re.findall(r'\bobase\b', fixed)) == 1:
        fixed = re.sub(r'\{', '{\n    (void)obase;', fixed, count=1)

    if fixed != function:
        text = text[:match.start()] + fixed + text[match.end():]
        path.write_text(text)

    verified = re.search(
        r'int\s+X509_NAME_print\s*\(\s*BIO\s*\*\s*bp\s*,\s*(?:const\s+)?X509_NAME\s*\*\s*name\s*,\s*int\s+obase\s*\)\s*\{.*?\n\}',
        path.read_text(),
        re.S,
    )
    if verified is not None and re.search(r'\bl\b', verified.group(0)):
        raise RuntimeError('BoringSSL X509_NAME_print still references obsolete line counter: {}'.format(path))
    print('BoringSSL X509_NAME_print: legacy line-counter compatibility verified', flush=True)


def ensure_boringssl_bn_comba8_decl_compat():
    """Match the BoringSSL declaration to the 8-limb implementation."""
    path = ROOT / 'src/boringssl/src/crypto/fipsmodule/bn/internal.h'
    if not path.is_file():
        raise RuntimeError('BoringSSL bn internal.h not found: {}'.format(path))

    text = path.read_text()
    pattern = re.compile(
        r'(bn_sqr_comba8\s*\([^;{}]*?\bconst\s+BN_ULONG\s+a\s*)\[\s*4\s*\](?=\s*\)\s*;)',
        re.S,
    )
    fixed, count = pattern.subn(r'\1[8]', text, count=1)
    if count:
        path.write_text(fixed)

    verified = path.read_text()
    if pattern.search(verified):
        raise RuntimeError('BoringSSL bn_sqr_comba8 declaration still has a 4-limb bound')
    if 'bn_sqr_comba8' in verified and not re.search(
        r'bn_sqr_comba8\s*\([^;{}]*?\bconst\s+BN_ULONG\s+a\s*\[\s*8\s*\]\s*\)\s*;',
        verified,
        re.S,
    ):
        raise RuntimeError('BoringSSL bn_sqr_comba8 declaration was found but not recognized')
    print('BoringSSL BN: bn_sqr_comba8 declaration verified for 8 limbs', flush=True)


def ensure_libbase_fmt_format_string_compat():
    """Use the fmt string-view conversion supported by the release-pinned fmtlib."""
    path = ROOT / 'src/libbase/include/android-base/result.h'
    if not path.is_file():
        raise RuntimeError('libbase result.h not found: {}'.format(path))

    text = path.read_text()
    old = 'fmt::vformat(fmt.get(),'
    new = 'fmt::vformat(fmt,'
    if old in text:
        text = text.replace(old, new)
        path.write_text(text)
        print('libbase: adapted fmt::vformat to the tag-pinned fmt format_string API', flush=True)

    verified = path.read_text()
    if old in verified:
        raise RuntimeError('libbase result.h still calls format_string::get(): {}'.format(path))


def ensure_aapt2_protobuf_limit_compat():
    """Support both the legacy and modern Protobuf SetTotalBytesLimit signatures."""
    path = ROOT / 'src/base/tools/aapt2/io/Util.h'
    if not path.is_file():
        raise RuntimeError('AAPT2 Util.h not found: {}'.format(path))

    text = path.read_text()
    old = '''    coded_stream.SetTotalBytesLimit(std::numeric_limits<int32_t>::max(),
                                    coded_stream.BytesUntilTotalBytesLimit());'''
    new = '''#if GOOGLE_PROTOBUF_VERSION >= 3021000
    coded_stream.SetTotalBytesLimit(std::numeric_limits<int32_t>::max());
#else
    coded_stream.SetTotalBytesLimit(std::numeric_limits<int32_t>::max(),
                                    coded_stream.BytesUntilTotalBytesLimit());
#endif'''
    if old in text:
        text = text.replace(old, new, 1)
        path.write_text(text)

    verified = path.read_text()
    if new not in verified:
        raise RuntimeError('AAPT2 Protobuf SetTotalBytesLimit compatibility fix failed: {}'.format(path))
    print('AAPT2: selected Protobuf SetTotalBytesLimit overload by version', flush=True)


def ensure_sdk_sandbox_aid_compat():
    """Keep Android 13+ SDK sandbox AIDs compatible with the selected AOSP snapshot."""
    version = tuple(int(part) for part in tools_version().split('.'))
    if version < (33, 0, 0):
        print('Android core AIDs: SDK sandbox UID range is not part of this pre-Android-13 release; skipping', flush=True)
        return

    path = ROOT / 'src/core/libcutils/include/private/android_filesystem_config.h'
    if not path.is_file():
        raise RuntimeError('Android filesystem AID header not found: {}'.format(path))

    text = path.read_text()
    definitions = (
        '#ifndef AID_SDK_SANDBOX_PROCESS_START\n'
        '#define AID_SDK_SANDBOX_PROCESS_START 20000 /* start of uids allocated to sdk sandbox processes */\n'
        '#endif\n'
        '#ifndef AID_SDK_SANDBOX_PROCESS_END\n'
        '#define AID_SDK_SANDBOX_PROCESS_END 29999 /* end of uids allocated to sdk sandbox processes */\n'
        '#endif\n'
    )
    if 'AID_SDK_SANDBOX_PROCESS_START' not in text:
        marker = '#define AID_APP_END 19999'
        if marker in text:
            text = text.replace(marker, marker + '\n\n' + definitions.rstrip(), 1)
        else:
            marker = '#define AID_APP_START 10000'
            if marker not in text:
                raise RuntimeError('cannot locate Android app UID range in {}'.format(path))
            text = text.replace(marker, definitions + '\n' + marker, 1)
        path.write_text(text)

    verified = path.read_text()
    if not re.search(r'(?m)^#\s*define\s+AID_SDK_SANDBOX_PROCESS_START\s+20000\b', verified):
        raise RuntimeError('SDK sandbox start AID compatibility definition missing: {}'.format(path))
    if not re.search(r'(?m)^#\s*define\s+AID_SDK_SANDBOX_PROCESS_END\s+29999\b', verified):
        raise RuntimeError('SDK sandbox end AID compatibility definition missing: {}'.format(path))
    print('Android core AIDs: added SDK sandbox UID range 20000-29999 when absent', flush=True)


def ensure_lru_cache_cxx17_compat():
    """Remove obsolete std::unary_function base classes (removed from C++17)."""
    path = ROOT / 'src/core/libutils/include/utils/LruCache.h'
    if not path.is_file():
        raise RuntimeError('libutils LruCache.h not found: {}'.format(path))

    text = path.read_text()
    text = re.sub(
        r'\s*:\s*public\s+std::unary_function\s*<\s*KeyedEntry\s*\*\s*,\s*hash_t\s*>',
        '',
        text,
    )
    path.write_text(text)

    verified = path.read_text()
    if 'std::unary_function' in verified:
        raise RuntimeError('obsolete std::unary_function remains in {}'.format(path))
    print('libutils LruCache: removed obsolete std::unary_function inheritance', flush=True)


def ensure_art_safe_map_invoke_result_compat():
    """Use C++17 invoke_result instead of result_of, which is removed in C++20."""
    path = ROOT / 'src/art/libartbase/base/safe_map.h'
    if not path.is_file():
        raise RuntimeError('ART safe_map.h not found: {}'.format(path))

    text = path.read_text()
    if '#include <type_traits>' not in text:
        include = re.search(r'(?m)^#include\s+[<"]', text)
        if include is None:
            raise RuntimeError('cannot locate include block in {}'.format(path))
        text = text[:include.start()] + '#include <type_traits>\n' + text[include.start():]

    replacements = (
        (
            r'typename\s+std::result_of\s*<\s*CreateFn\s*\(\s*\)\s*>\s*::\s*type',
            'std::invoke_result_t<CreateFn>',
        ),
        (
            r'std::result_of_t\s*<\s*CreateFn\s*\(\s*\)\s*>',
            'std::invoke_result_t<CreateFn>',
        ),
    )
    total = 0
    for pattern, replacement in replacements:
        text, count = re.subn(pattern, replacement, text)
        total += count

    if total:
        path.write_text(text)

    verified = path.read_text()
    if re.search(r'std::result_of(?:_t)?\s*<', verified):
        raise RuntimeError('C++20-incompatible std::result_of remains in {}'.format(path))
    if 'std::invoke_result_t<CreateFn>' not in verified:
        raise RuntimeError('ART safe_map invoke_result compatibility was not applied: {}'.format(path))
    print('ART SafeMap: migrated result_of to invoke_result_t ({} replacement(s))'.format(total), flush=True)




def ensure_art_string_view_cpp20_compat():
    """Remove ART's obsolete C++20 #error while retaining its string_view wrappers."""
    path = ROOT / 'src/art/libartbase/base/string_view_cpp20.h'
    if not path.is_file():
        raise RuntimeError('ART string_view_cpp20.h not found: {}'.format(path))

    text = path.read_text()
    expected_error = '#error "When upgrading to C++20, remove this error and file a bug to remove this workaround."'
    lines = text.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.strip() == expected_error]
    if len(matches) == 1:
        del lines[matches[0]]
        path.write_text(''.join(lines))
    elif len(matches) > 1:
        raise RuntimeError('multiple obsolete ART C++20 errors found in {}'.format(path))

    verified = path.read_text()
    if expected_error in verified:
        raise RuntimeError('ART C++20 error remains in {}'.format(path))
    if 'inline bool StartsWith(std::string_view sv' not in verified:
        raise RuntimeError('ART StartsWith implementation missing in {}'.format(path))
    if 'inline bool EndsWith(std::string_view sv' not in verified:
        raise RuntimeError('ART EndsWith implementation missing in {}'.format(path))
    print('ART string_view: obsolete C++20 #error removed; compatibility wrappers retained', flush=True)


def ensure_abseil_result_of_cxx20_compat():
    """Use invoke_result when C++20 removes std::result_of, retaining old-STL fallback."""
    path = ROOT / 'src/abseil-cpp/absl/meta/type_traits.h'
    if not path.is_file():
        raise RuntimeError('Abseil type_traits.h not found: {}'.format(path))

    text = path.read_text()
    old = 'template <typename T>\nusing result_of_t = typename std::result_of<T>::type;'
    new = '''namespace type_traits_internal {
#if (defined(__cpp_lib_is_invocable) && __cpp_lib_is_invocable >= 201703L) || (defined(_MSVC_LANG) && _MSVC_LANG >= 201703L)
template <typename>
struct result_of;
template <typename F, typename... Args>
struct result_of<F(Args...)> : std::invoke_result<F, Args...> {};
#else
template <typename F>
using result_of = std::result_of<F>;
#endif
}  // namespace type_traits_internal

template <typename T>
using result_of_t = typename type_traits_internal::result_of<T>::type;'''
    if old in text:
        text = text.replace(old, new, 1)
        path.write_text(text)
        print('Abseil: replaced removed C++20 std::result_of alias with invoke_result compatibility wrapper', flush=True)

    verified = path.read_text()
    if old in verified:
        raise RuntimeError('Abseil type_traits.h still uses removed std::result_of alias')
    if 'using result_of_t = typename type_traits_internal::result_of<T>::type;' not in verified:
        if 'using result_of_t =' in verified and 'std::result_of<T>' in verified:
            raise RuntimeError('Abseil result_of alias has an unrecognized incompatible form')
        print('Abseil: no incompatible result_of alias in this AOSP tag', flush=True)
    else:
        print('Abseil: C++20 result_of compatibility verified', flush=True)


def ensure_libziparchive_cxx20_aggregate_compat():
    """Keep ZIP record default construction valid under the C++20 aggregate rules."""
    path = ROOT / 'src/libziparchive/zip_archive_common.h'
    if not path.is_file():
        raise RuntimeError('libziparchive common header not found: {}'.format(path))

    text = path.read_text()
    record_types = (
        'EocdRecord',
        'CentralDirectoryRecord',
        'LocalFileHeader',
        'DataDescriptor',
        'Zip64EocdLocator',
        'Zip64EocdRecord',
        'Zip64ExtendedInfo',
    )
    changed = []
    for name in record_types:
        pattern = re.compile(
            r'(?m)^(?P<indent>[ \t]*)private:[ \t]*\n'
            r'(?P<ctor_indent>[ \t]*)' + re.escape(name) +
            r'\(\)\s*=\s*default;'
        )
        def expose_default_constructor(match):
            return (
                match.group('ctor_indent') + name + '() = default;\n\n' +
                match.group('indent') + 'private:'
            )
        text, count = pattern.subn(expose_default_constructor, text, count=1)
        if count:
            changed.append(name)

    if changed:
        path.write_text(text)
        print('libziparchive C++20 compatibility: public default constructors for ' +
              ', '.join(changed), flush=True)
    else:
        print('libziparchive C++20 compatibility: record constructors already public', flush=True)

    for name in record_types:
        pattern = re.compile(
            r'struct\s+' + re.escape(name) +
            r'\s*\{.*?private:\s*\n\s*' +
            re.escape(name) + r'\(\)\s*=\s*default;',
            re.S
        )
        if pattern.search(text):
            raise RuntimeError('libziparchive {} default constructor remains private'.format(name))


def patches():
    ensure_abseil_result_of_cxx20_compat()
    ensure_libziparchive_cxx20_aggregate_compat()
    inc = ROOT / 'src/incremental_delivery/sysprop/include'
    inc.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'patches/misc/IncrementalProperties.sysprop.h', inc)
    shutil.copy2(ROOT / 'patches/misc/IncrementalProperties.sysprop.cpp', inc.parent)

    shutil.copy2(ROOT / 'patches/misc/deployagent.inc', ROOT / 'src/adb/fastdeploy/deployagent')
    shutil.copy2(ROOT / 'patches/misc/deployagentscript.inc', ROOT / 'src/adb/fastdeploy/deployagent')

    shutil.copy2(VERSION_HEADER, ROOT / 'src/soong/cc/libbuildversion/include')

    aapt2 = 'src/base/tools/aapt2/'
    replace_in_file(aapt2 + 'ApkInfo.proto', 'frameworks/base/tools/aapt2/Resources.proto', 'Resources.proto')
    replace_in_file(aapt2 + 'Resources.proto', 'frameworks/base/tools/aapt2/Configuration.proto', 'Configuration.proto')
    replace_in_file(aapt2 + 'ResourcesInternal.proto', 'frameworks/base/tools/aapt2/Configuration.proto', 'Configuration.proto')
    replace_in_file(aapt2 + 'ResourcesInternal.proto', 'frameworks/base/tools/aapt2/Resources.proto', 'Resources.proto')

    replace_in_file('src/abseil-cpp/CMakeLists.txt', '/usr/src/googletest', '${CMAKE_SOURCE_DIR}/src/googletest')

    # BoringSSL snapshots use two GoogleTest layouts; follow its own CMake.
    boringssl_cmake = ROOT / 'src/boringssl/src/CMakeLists.txt'
    if boringssl_cmake.is_file():
        cmake_text = boringssl_cmake.read_text()
        dest = ROOT / 'src/boringssl/src/third_party/googletest'
        if 'third_party/googletest/src/gtest-all.cc' in cmake_text:
            googletest_target = ROOT / 'src/googletest/googletest'
        else:
            googletest_target = ROOT / 'src/googletest'
        if dest.is_symlink():
            try:
                if dest.resolve() != googletest_target.resolve():
                    dest.unlink()
            except FileNotFoundError:
                dest.unlink()
        if dest.parent.exists() and not dest.exists():
            dest.symlink_to(googletest_target)

    # the source patches only apply to specific versions, apply them when possible
    for patch in sorted((ROOT / 'patches').rglob('*.patch')):
        print('patch {}: {}'.format(patch.relative_to(ROOT), apply_patch(patch)))

    ensure_art_build_defines()
    ensure_openscreen_task_runner_compat()
    ensure_art_metrics_memory_order_compat()
    ensure_art_hash_set_allocator_compat()
    ensure_androidfw_theme_entry_definition()
    ensure_libziparchive_span_compat()
    ensure_aidl_flex_parser_types()
    ensure_fastboot_unique_fd_compat()
    ensure_adb_mdns_function_include()
    ensure_adb_tls_function_include()
    ensure_sdk_sandbox_aid_compat()
    ensure_lru_cache_cxx17_compat()
    ensure_art_safe_map_invoke_result_compat()
    ensure_art_string_view_cpp20_compat()
    ensure_boringssl_x509_name_print_compat()
    ensure_boringssl_bn_comba8_decl_compat()
    ensure_libbase_fmt_format_string_compat()
    ensure_aapt2_protobuf_limit_compat()


def main():
    version = tools_version()
    parser = argparse.ArgumentParser()
    parser.add_argument('--tags', default='platform-tools-{}'.format(version),
                        help='git tag or branch of the AOSP repositories, default is platform-tools-{} '
                             '(from patches/misc/platform_tools_version.h)'.format(version))
    parser.add_argument('--jobs', type=int, default=8, help='clone N repositories in parallel')
    parser.add_argument('--retries', type=int, default=3, help='retry times of a failed clone')
    parser.add_argument('--skip-patch', action='store_true', help='only clone, do not patch the sources')
    args = parser.parse_args()

    # check necessary packages
    for command in ('git', 'patch', 'go', 'bison', 'flex'):
        check(command)

    repos = json.loads((ROOT / 'repository.json').read_text())
    repos = resolve_manifest_revisions(repos, args.tags, args.retries)
    print('fetching sources from Google manifest: {}'.format(args.tags))
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(clone, repo, args.tags, args.retries) for repo in repos]
        for future in as_completed(futures):
            try:
                print(future.result(), flush=True)
            except RuntimeError as e:
                errors.append(str(e))
    if errors:
        sys.exit('\n'.join(errors))

    if not args.skip_patch:
        patches()

    print('download success!!')


if __name__ == '__main__':
    main()
