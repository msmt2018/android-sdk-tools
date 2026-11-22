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
        raise RuntimeError('failed to fetch Google platform manifest tag {}:\\n{}'.format(
            manifest_tag, result.stderr if result else 'no git result'))

    manifest_file = manifest_dir / 'default.xml'
    if not manifest_file.is_file():
        raise RuntimeError('Google manifest tag {} has no default.xml'.format(manifest_tag))

    # Repo manifests may split projects across included XML files and apply
    # extend-project/remove-project directives. Read the complete manifest
    # graph instead of treating default.xml as a self-contained project list.
    projects_by_name = {}
    defaults = {}
    remotes = {}
    visited_manifests = set()

    def read_manifest(manifest_path):
        manifest_path = manifest_path.resolve()
        if manifest_path in visited_manifests:
            return
        if not manifest_path.is_file():
            raise RuntimeError('Google manifest include not found: {}'.format(manifest_path))
        visited_manifests.add(manifest_path)
        manifest_root = ET.parse(str(manifest_path)).getroot()

        # Resolve inherited defaults/remotes before processing project entries
        # in this file; included manifests may define their own values.
        for node in manifest_root:
            if node.tag == 'default':
                defaults.update(node.attrib)
            elif node.tag == 'remote':
                remote_name = node.get('name')
                if remote_name:
                    remotes[remote_name] = dict(node.attrib)

        for node in manifest_root:
            if node.tag == 'include':
                include_name = node.get('name')
                if not include_name:
                    raise RuntimeError('manifest include without a name in {}'.format(manifest_path))
                read_manifest(manifest_dir / include_name)
            elif node.tag == 'project':
                name = node.get('name')
                if name:
                    projects_by_name.setdefault(name, []).append(dict(node.attrib))
            elif node.tag == 'extend-project':
                name = node.get('name')
                if not name:
                    continue
                for project in projects_by_name.get(name, []):
                    path_filter = node.get('path')
                    if path_filter and project.get('path', name) != path_filter:
                        continue
                    project.update({
                        key: value for key, value in node.attrib.items()
                        if key not in ('name', 'path')
                    })
            elif node.tag == 'remove-project':
                name = node.get('name')
                if not name:
                    continue
                path_filter = node.get('path')
                remaining = [
                    project for project in projects_by_name.get(name, [])
                    if path_filter and project.get('path', name) != path_filter
                ]
                if remaining:
                    projects_by_name[name] = remaining
                else:
                    projects_by_name.pop(name, None)

    read_manifest(manifest_file)

    projects = {}
    for name, project_entries in projects_by_name.items():
        for project in project_entries:
            revision = project.get('revision') or defaults.get('revision')
            if revision:
                projects[name] = revision

    def has_release_tag(url, tag_name):
        tag_ref = 'refs/tags/{}'.format(tag_name)
        for attempt in range(1, retries + 1):
            try:
                result = subprocess.run(
                    ['git', 'ls-remote', '--exit-code', '--refs', url, tag_ref],
                    capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired:
                result = None
            if result is not None and result.returncode == 0 and result.stdout.strip():
                return True
            if result is not None and result.returncode == 2:
                return False
            if attempt < retries:
                time.sleep(2 * attempt)
        return False

    # Probe Google project release tags concurrently; serial remote checks
    # made preparation unnecessarily slow across the full source manifest.
    release_tag_by_url = {}
    tag_urls = {
        repo.get('url', '') for repo in repos
        if not repo.get('branch') and repo.get('url', '').startswith(
            'https://android.googlesource.com/')
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(has_release_tag, url, release_tag): url
            for url in tag_urls
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                release_tag_by_url[url] = future.result()
            except Exception as error:
                release_tag_by_url[url] = False
                print('Google release tag probe failed for {}: {}'.format(url, error), flush=True)

    resolved = []
    missing = []
    for repo in repos:
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

        # Prefer an exact platform-tools release tag when the Google project
        # publishes one; otherwise use the revision pinned by the selected
        # platform/manifest snapshot.
        if release_tag_by_url.get(url, False):
            item = dict(repo)
            item['branch'] = release_tag
            resolved.append(item)
            print('verified Google project release tag: {} ({})'.format(project_name, release_tag), flush=True)
            continue

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
    # Older official zlib snapshots do not consistently ship every private
    # implementation header checked by newer releases. A successful Git
    # checkout is complete even when those optional headers are absent; let
    # the release-specific CMake source list determine what is actually built.
    required_files = ('zlib.h',) if repo.get('path') == 'src/zlib' else ()
    def complete():
        return not required_files or all((path / name).is_file() for name in required_files)
    if path.exists():
        if complete():
            return '{} already exists, skip'.format(repo['path'])
        shutil.rmtree(path, ignore_errors=True)
    revision = repo.get('branch', default_branch)
    url = repo['url']
    result = None
    for attempt in range(1, retries + 1):
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(['git', 'init', '-q', str(path)], capture_output=True, text=True)
        if result.returncode == 0:
            result = subprocess.run(['git', '-C', str(path), 'remote', 'add', 'origin', url], capture_output=True, text=True)
        if result.returncode == 0:
            refs = ([revision] if revision.startswith('refs/') or re.fullmatch(r'[0-9a-fA-F]{40}', revision)
                    else ['refs/tags/' + revision, 'refs/heads/' + revision])
            for index, ref in enumerate(refs):
                result = subprocess.run(['git', '-C', str(path), 'fetch', '--depth', '1', 'origin', ref], capture_output=True, text=True)
                if result.returncode == 0:
                    checkout = subprocess.run(['git', '-C', str(path), 'checkout', '--detach', '--quiet', 'FETCH_HEAD'], capture_output=True, text=True)
                    if checkout.returncode == 0 and complete():
                        return 'fetched {} ({})'.format(repo['path'], revision)
                    result = checkout
                if index + 1 < len(refs):
                    subprocess.run(['git', '-C', str(path), 'remote', 'remove', 'origin'], capture_output=True, text=True)
                    subprocess.run(['git', '-C', str(path), 'init', '-q'], capture_output=True, text=True)
                    subprocess.run(['git', '-C', str(path), 'remote', 'add', 'origin', url], capture_output=True, text=True)
        if attempt < retries:
            time.sleep(5 * attempt)
    raise RuntimeError('failed to fetch {} ({}) [manifest-pinned revision]:\\n{}'.format(
        url, revision, result.stderr if result else 'no git result'))


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
    candidates = (
        ROOT / 'src/art/libartbase/arch/instruction_set.h',
        ROOT / 'src/art/runtime/arch/instruction_set.h',
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        print('ART instruction_set.h is not present in this source layout; using target compile definitions', flush=True)
        return

    text = path.read_text()
    marker = 'namespace art {'
    if marker not in text:
        raise RuntimeError('cannot locate namespace art in {}'.format(path))

    definitions = {
        'ART_STACK_OVERFLOW_GAP_arm': 8192,
        'ART_STACK_OVERFLOW_GAP_arm64': 8192,
        'ART_STACK_OVERFLOW_GAP_mips': 16384,
        'ART_STACK_OVERFLOW_GAP_mips64': 16384,
        'ART_STACK_OVERFLOW_GAP_riscv64': 16384,
        'ART_STACK_OVERFLOW_GAP_x86': 8192,
        'ART_STACK_OVERFLOW_GAP_x86_64': 8192,
        'ART_FRAME_SIZE_LIMIT': 1736,
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



def ensure_art_memory_tool_compat():
    """Keep optional Valgrind annotations disabled unless explicitly requested."""
    candidates = (
        ROOT / 'src/art/libartbase/base/memory_tool.h',
        ROOT / 'src/art/runtime/base/memory_tool.h',
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return

    text = path.read_text()
    if 'ART_USE_VALGRIND' in text:
        return

    lines = text.splitlines(keepends=True)
    asan_index = next(
        (i for i, line in enumerate(lines)
         if '__has_feature(address_sanitizer)' in line),
        None,
    )
    if asan_index is None:
        raise RuntimeError('cannot locate ART address-sanitizer branch in {}'.format(path))

    depth = 0
    else_index = None
    closing_index = None
    for i in range(asan_index + 1, len(lines)):
        directive = re.match(r'^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b', lines[i])
        if directive is None:
            continue
        kind = directive.group(1)
        if kind in ('if', 'ifdef', 'ifndef'):
            depth += 1
        elif kind == 'else' and depth == 0:
            else_index = i
        elif kind == 'endif':
            if depth == 0:
                closing_index = i
                break
            depth -= 1

    if else_index is None or closing_index is None:
        raise RuntimeError('cannot isolate ART Valgrind branch in {}'.format(path))

    lines[else_index] = '#elif defined(ART_USE_VALGRIND)\n'
    fallback = [
        '#else\n',
        '#define MEMORY_TOOL_MAKE_NOACCESS(p, s) do { (void)(p); (void)(s); } while (0)\n',
        '#define MEMORY_TOOL_MAKE_UNDEFINED(p, s) do { (void)(p); (void)(s); } while (0)\n',
        '#define MEMORY_TOOL_MAKE_DEFINED(p, s) do { (void)(p); (void)(s); } while (0)\n',
        '#define ATTRIBUTE_NO_SANITIZE_ADDRESS\n',
        '#define RUNNING_ON_MEMORY_TOOL 0U\n',
        'constexpr bool kMemoryToolIsAvailable = false;\n',
        'constexpr bool kRunningOnMemoryTool = false;\n',
        'constexpr bool kMemoryToolIsValgrind = false;\n',
        'constexpr bool kMemoryToolDetectsLeaks = false;\n',
        'constexpr bool kMemoryToolAddsRedzones = false;\n',
        'constexpr size_t kMemoryToolStackGuardSizeScale = 1;\n',
    ]
    lines[closing_index:closing_index] = fallback
    path.write_text(''.join(lines))
    print('ART memory tool: disabled optional Valgrind hooks for standalone build', flush=True)


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
    if 'std::function' not in text:
        print('ADB mdns: no std::function callback in this AOSP snapshot; skipping', flush=True)
        return
    if '#include <functional>' not in text:
        match = re.search(r'(?m)^#include\s+[<"]', text)
        if not match:
            print('ADB mdns: no include block in this legacy header; skipping', flush=True)
            return
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
    if 'std::function' not in text:
        print('ADB TLS: no std::function callback in this AOSP snapshot; skipping', flush=True)
        return
    if '#include <functional>' not in text:
        match = re.search(r'(?m)^#include\s+[<"]', text)
        if not match:
            print('ADB TLS: no include block in this legacy header; skipping', flush=True)
            return
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
    if new in verified:
        print('AAPT2: selected Protobuf SetTotalBytesLimit overload by version', flush=True)
    elif old not in verified:
        print('AAPT2: this historical source uses a different SetTotalBytesLimit form; leaving upstream call unchanged', flush=True)
    else:
        raise RuntimeError('AAPT2 Protobuf SetTotalBytesLimit compatibility fix failed: {}'.format(path))


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


def run_compat_if_present(relative_path, function):
    path = ROOT / relative_path
    if path.is_file():
        function()
    else:
        print('{}: source is absent in this Google snapshot; skipping compatibility patch'.format(
            relative_path), flush=True)


def create_legacy_source_aliases():
    # Reconcile split and pre-split AOSP layouts from the exact manifest-pinned
    # snapshot. Existing files always win; only missing paths are linked from
    # the same release's historical system/core or ART directories.
    aliases = {
        'src/adb': 'src/core/adb',
        'src/libbase': 'src/core/base',
        'src/libziparchive': 'src/core/libziparchive',
        'src/unwinding/libbacktrace': 'src/core/libbacktrace',
        'src/logging/liblog': 'src/core/liblog',
        'src/art/libartbase/base': 'src/art/runtime/base',
    }
    for destination, source in aliases.items():
        dst = ROOT / destination
        src = ROOT / source
        if not src.is_dir():
            continue
        if not dst.exists() and not dst.is_symlink():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(src, target_is_directory=True)
            print('legacy AOSP layout: {} -> {}'.format(destination, source), flush=True)
            continue
        if dst.is_symlink():
            try:
                if dst.resolve() == src.resolve():
                    continue
            except FileNotFoundError:
                pass
        if not dst.is_dir():
            continue
        linked = 0
        for candidate in src.rglob('*'):
            relative = candidate.relative_to(src)
            target = dst / relative
            if candidate.is_dir():
                if not target.exists() and not target.is_symlink():
                    target.mkdir(parents=True, exist_ok=True)
            elif candidate.is_file():
                if target.exists() or target.is_symlink():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(candidate.resolve())
                linked += 1
        if linked:
            print('legacy AOSP layout: merged {} missing file(s) from {}'.format(
                linked, source), flush=True)

    legacy_files = {
        'src/art/libdexfile/dex/type_lookup_table.cc': 'src/art/runtime/type_lookup_table.cc',
        'src/art/libdexfile/dex/type_lookup_table.h': 'src/art/runtime/type_lookup_table.h',
    }
    for destination, source in legacy_files.items():
        dst = ROOT / destination
        src = ROOT / source
        if src.is_file() and not dst.exists() and not dst.is_symlink():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(src.resolve())
            print('legacy ART layout: {} -> {}'.format(destination, source), flush=True)


def normalize_optional_release_sources():
    """Remove only CMake source entries absent from this exact Google snapshot.

    Source inventories differ across Android release tags. Optional files
    introduced after the selected snapshot must not be passed to add_library()
    or add_executable(); no replacement source is fabricated here.
    """
    optional_sources = {
        'lib/libbase.cmake': [
            ('${SRC}/libbase/process.cpp', 'LIBBASE_PROCESS_SOURCE'),
            ('${SRC}/libbase/cmsg.cpp', 'LIBBASE_CMSG_SOURCE'),
            ('${SRC}/libbase/parsebool.cpp', 'LIBBASE_PARSEBOOL_SOURCE'),
            ('${SRC}/libbase/mapped_file.cpp', 'LIBBASE_MAPPED_FILE_SOURCE'),
            ('${SRC}/libbase/threads.cpp', 'LIBBASE_THREADS_SOURCE'),
        ],
        'lib/liblog.cmake': [
            ('${SRC}/logging/liblog/log_event_write.cpp', 'LIBLOG_EVENT_WRITE_SOURCE'),
            ('${SRC}/logging/liblog/logger_name.cpp', 'LIBLOG_LOGGER_NAME_SOURCE'),
            ('${SRC}/logging/liblog/logger_write.cpp', 'LIBLOG_LOGGER_WRITE_SOURCE'),
        ],
        'lib/libandroidfw.cmake': [
            ('${SRC}/base/libs/androidfw/ConfigDescription.cpp', 'ANDROIDFW_CONFIG_DESCRIPTION_SOURCE'),
            ('${SRC}/base/libs/androidfw/Idmap.cpp', 'ANDROIDFW_IDMAP_SOURCE'),
            ('${SRC}/base/libs/androidfw/PosixUtils.cpp', 'ANDROIDFW_POSIX_UTILS_SOURCE'),
        ],
        'lib/libziparchive.cmake': [
            ('${SRC}/libziparchive/zip_error.cpp', 'LIBZIPARCHIVE_ZIP_ERROR_SOURCE'),
            ('${SRC}/libziparchive/zip_cd_entry_map.cc', 'LIBZIPARCHIVE_CD_ENTRY_MAP_SOURCE'),
        ],
        'lib/libsparse.cmake': [
            ('${SRC}/core/libsparse/output_file.cpp', 'LIBSPARSE_OUTPUT_FILE_SOURCE'),
        ],
        'lib/libprocessgroup.cmake': [
            ('${SRC}/core/libprocessgroup/sched_policy.cpp', 'LIBPROCESSGROUP_SCHED_POLICY_SOURCE'),
            ('${SRC}/core/libprocessgroup/task_profiles.cpp', 'LIBPROCESSGROUP_TASK_PROFILES_SOURCE'),
            ('${SRC}/core/libprocessgroup/cgrouprc/cgroup_controller.cpp', 'LIBPROCESSGROUP_LEGACY_CGROUP_CONTROLLER_SOURCE'),
        ],
        'lib/libprotoc.cmake': [
            ('${SRC}/protobuf/src/google/protobuf/generated_message_table_driven_lite.cc', 'PROTOBUF_GENERATED_MESSAGE_TABLE_DRIVEN_LITE_SOURCE'),
            ('${SRC}/protobuf/src/google/protobuf/implicit_weak_message.cc', 'PROTOBUF_IMPLICIT_WEAK_MESSAGE_SOURCE'),
            ('${SRC}/protobuf/src/google/protobuf/any_lite.cc', 'PROTOBUF_ANY_LITE_SOURCE'),
            ('${SRC}/protobuf/src/google/protobuf/generated_enum_util.cc', 'PROTOBUF_GENERATED_ENUM_UTIL_SOURCE'),
            ('${SRC}/protobuf/src/google/protobuf/io/io_win32.cc', 'PROTOBUF_IO_WIN32_SOURCE'),
        ],
        'build-tools/aidl.cmake': [
            ('${SRC}/aidl/aidl_checkapi.cpp', 'AIDL_CHECKAPI_SOURCE'),
            ('${SRC}/aidl/diagnostics.cpp', 'AIDL_DIAGNOSTICS_SOURCE'),
        ],
        'build-tools/dexdump.cmake': [
            ('${SRC}/art/libartbase/base/membarrier.cc', 'ART_MEMBARRIER_SOURCE'),
            ('${SRC}/art/libartbase/base/memfd.cc', 'ART_MEMFD_SOURCE'),
            ('${SRC}/art/libartpalette/apex/palette.cc', 'ART_PALETTE_APEX_SOURCE'),
            ('${SRC}/art/libartpalette/system/palette_fake.cc', 'ART_PALETTE_FAKE_SOURCE'),
            ('${SRC}/art/libdexfile/dex/signature.cc', 'ART_DEX_SIGNATURE_SOURCE'),
            ('${SRC}/art/libartbase/base/arena_allocator.cc', 'ART_ARENA_ALLOCATOR_SOURCE'),
            ('${SRC}/art/libartbase/base/globals_unix.cc', 'ART_GLOBALS_UNIX_SOURCE'),
            ('${SRC}/art/libdexfile/dex/type_lookup_table.cc', 'ART_TYPE_LOOKUP_TABLE_SOURCE'),
        ],
        'platform-tools/e2fsprogs.cmake': [
            ('${SRC}/e2fsprogs/lib/e2p/encoding.c', 'E2FSPROGS_ENCODING_SOURCE'),
            ('${SRC}/e2fsprogs/lib/e2p/ljs.c', 'E2FSPROGS_LJS_SOURCE'),
            ('${SRC}/e2fsprogs/lib/ext2fs/nls_utf8.c', 'E2FSPROGS_NLS_UTF8_SOURCE'),
        ],
        'platform-tools/f2fs-tools.cmake': [
            ('${SRC}/f2fs-tools/fsck/compress.c', 'F2FS_COMPRESS_SOURCE'),
        ],
        'platform-tools/fastboot.cmake': [
            ('${SRC}/extras/ext4_utils/ext4_utils.cpp', 'FASTBOOT_EXT4_UTILS_SOURCE'),
            ('${SRC}/extras/ext4_utils/wipe.cpp', 'FASTBOOT_EXT4_WIPE_SOURCE'),
            ('${SRC}/core/fastboot/fastboot_driver.cpp', 'FASTBOOT_DRIVER_SOURCE'),
        ],
        'lib/libusb.cmake': [
            ('${SRC}/libusb/libusb/os/events_posix.c', 'LIBUSB_EVENTS_POSIX_SOURCE'),
        ],
        'build-tools/zipalign.cmake': [
            ('${SRC}/build/tools/zipalign/ZipAlignMain.cpp', 'ZIPALIGN_MAIN_SOURCE'),
        ],
        'platform-tools/adb.cmake': [
            ('${SRC}/adb/sysdeps/env.cpp', 'ADB_ENV_SOURCE'),
            ('${SRC}/core/libcrypto_utils/android_pubkey.cpp', 'ADB_ANDROID_PUBKEY_SOURCE'),
        ],
        'lib/libincfs.cmake': [
            ('${SRC}/incremental_delivery/incfs/util/map_ptr.cpp', 'INCFS_MAP_PTR_SOURCE'),
        ],
    }

    # Some legacy Google zlib snapshots keep their C files below a
    # subdirectory. Preserve the exact checked-out files and expose them at
    # the path expected by the shared CMake target.
    zlib_root = ROOT / 'src/zlib'
    if zlib_root.is_dir():
        for filename in (
            'adler32.c', 'compress.c', 'crc32.c', 'deflate.c',
            'gzclose.c', 'gzlib.c', 'gzread.c', 'gzwrite.c',
            'infback.c', 'inffast.c', 'inflate.c', 'inftrees.c',
            'trees.c', 'uncompr.c', 'zutil.c',
        ):
            destination = zlib_root / filename
            if destination.exists():
                continue
            matches = [
                candidate for candidate in zlib_root.rglob(filename)
                if candidate.is_file() and candidate != destination
            ]
            if len(matches) == 1:
                destination.symlink_to(matches[0])
                print('legacy zlib layout: {} -> {}'.format(
                    destination.relative_to(ROOT), matches[0].relative_to(ROOT)
                ), flush=True)
        # Older external/zlib snapshots place private implementation
        # headers below src/ while their C files are normalized to the root.
        # Mirror only uniquely located headers; do not overwrite release files.
        for filename in (
            'zutil.h', 'deflate.h', 'inflate.h', 'inftrees.h',
            'inffast.h', 'trees.h', 'gzguts.h', 'crc32.h',
        ):
            destination = zlib_root / filename
            if destination.exists():
                continue
            matches = [
                candidate for candidate in zlib_root.rglob(filename)
                if candidate.is_file() and candidate != destination
            ]
            if len(matches) == 1:
                destination.symlink_to(matches[0])
                print('legacy zlib header: {} -> {}'.format(
                    destination.relative_to(ROOT), matches[0].relative_to(ROOT)
                ), flush=True)

        zlib_sources = sorted(
            candidate.relative_to(zlib_root).as_posix()
            for candidate in zlib_root.rglob('*.c')
            if candidate.is_file()
        )
        print('zlib C source inventory: {}'.format(', '.join(zlib_sources)), flush=True)

    for relative_path, entries in optional_sources.items():
        cmake_file = ROOT / relative_path
        if not cmake_file.is_file():
            continue
        text = cmake_file.read_text()
        changed = False
        for source, variable in entries:
            source_line = '    ' + source + '\n'
            if source_line not in text:
                continue
            text = text.replace(source_line, '    ${' + variable + '}\n', 1)
            guard = (
                'set(' + variable + ')\n'
                'if(EXISTS "' + source + '")\n'
                '    list(APPEND ' + variable + ' "' + source + '")\n'
                'endif()\n\n'
            )
            target_positions = [
                position for position in (
                    text.find('add_library('),
                    text.find('add_executable('),
                ) if position >= 0
            ]
            if not target_positions:
                raise RuntimeError('no CMake target in {}'.format(relative_path))
            insert_at = min(target_positions)
            text = text[:insert_at] + guard + text[insert_at:]
            changed = True
        if changed:
            cmake_file.write_text(text)
            print('normalized optional sources for {}'.format(relative_path), flush=True)


def ensure_liblog_ndk_r27_compat():
    """Apply source-level compatibility for the NDK r27/API 24 build."""
    cmake = ROOT / 'lib/liblog.cmake'
    if cmake.is_file():
        text = cmake.read_text()
        text = re.sub(r'(?m)^\s*target_compile_options\(liblog PRIVATE .*__unused.*\)\s*\n?', '', text)
        text = re.sub(r'(?m)^target_compile_definitions\(liblog PRIVATE "__unused=__attribute__\(\(unused\)\)"\)\s*\n?', '', text)
        if '__unused=__attribute__((unused))' not in text:
            text = text.rstrip() + '\n\ntarget_compile_definitions(liblog PRIVATE "__unused=__attribute__((unused))")\n'
        cmake.write_text(text)
    event_tag_map = ROOT / 'src/logging/liblog/event_tag_map.cpp'
    if event_tag_map.is_file():
        text = event_tag_map.read_text()
        if '__android_log_is_loggable_len(' in text and 'extern "C" int __android_log_is_loggable_len' not in text:
            marker = '#include "logd_reader.h"'
            if marker not in text: raise RuntimeError('event_tag_map.cpp compatibility anchor not found')
            declaration = '#include <stddef.h>\nextern "C" int __android_log_is_loggable_len(int prio, const char* tag, size_t len, int default_prio);'
            text = text.replace(marker, marker + '\n' + declaration, 1)
            event_tag_map.write_text(text)
    properties = ROOT / 'src/core/libcutils/properties.cpp'
    if properties.is_file():
        text = properties.read_text()
        old_call = '__system_property_read_callback(pi, trampoline, data);'
        new_call = ('char name[PROP_NAME_MAX] = {};\n'
                    '    char value[PROP_VALUE_MAX] = {};\n'
                    '    __system_property_read(pi, name, value);\n'
                    '    trampoline(data, name, value, 0);')
        if old_call in text: properties.write_text(text.replace(old_call, new_call, 1))
    print('liblog NDK r27/API 24 compatibility applied', flush=True)
def patches():
    run_compat_if_present(
        'src/abseil-cpp/absl/meta/type_traits.h',
        ensure_abseil_result_of_cxx20_compat)
    run_compat_if_present(
        'src/libziparchive/zip_archive_common.h',
        ensure_libziparchive_cxx20_aggregate_compat)

    # These files only exist in snapshots that include Incremental FS and
    # fastdeploy. Do not manufacture partial source trees for older releases.
    inc_source = ROOT / 'src/incremental_delivery'
    if inc_source.is_dir():
        inc = inc_source / 'sysprop/include'
        inc.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'patches/misc/IncrementalProperties.sysprop.h', inc)
        shutil.copy2(ROOT / 'patches/misc/IncrementalProperties.sysprop.cpp', inc_source / 'sysprop')
    deployagent = ROOT / 'src/adb/fastdeploy/deployagent'
    if deployagent.is_dir():
        shutil.copy2(ROOT / 'patches/misc/deployagent.inc', deployagent)
        shutil.copy2(ROOT / 'patches/misc/deployagentscript.inc', deployagent)

    soong_include = ROOT / 'src/soong/cc/libbuildversion/include'
    soong_include.mkdir(parents=True, exist_ok=True)
    shutil.copy2(VERSION_HEADER, soong_include)

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
        if googletest_target.is_dir():
            if dest.is_symlink():
                try:
                    if dest.resolve() != googletest_target.resolve():
                        dest.unlink()
                except FileNotFoundError:
                    dest.unlink()
            if dest.parent.exists() and not dest.exists():
                dest.symlink_to(googletest_target)

    # The source patches only apply to specific versions. Apply only when the
    # corresponding source file exists in the pinned release snapshot.
    for patch in sorted((ROOT / 'patches').rglob('*.patch')):
        print('patch {}: {}'.format(patch.relative_to(ROOT), apply_patch(patch)))

    run_compat_if_present('src/art/libartbase/arch/instruction_set.h', ensure_art_build_defines)
    run_compat_if_present('src/art/libartbase/base/memory_tool.h', ensure_art_memory_tool_compat)
    run_compat_if_present('src/openscreen/platform/api/task_runner.h', ensure_openscreen_task_runner_compat)
    run_compat_if_present('src/art/libartbase/base/metrics/metrics.h', ensure_art_metrics_memory_order_compat)
    run_compat_if_present('src/art/libartbase/base/hash_set.h', ensure_art_hash_set_allocator_compat)
    run_compat_if_present('src/base/libs/androidfw/include/androidfw/AssetManager2.h', ensure_androidfw_theme_entry_definition)
    run_compat_if_present('src/libziparchive/zip_archive.cc', ensure_libziparchive_span_compat)
    run_compat_if_present('src/aidl/aidl_language_l.ll', ensure_aidl_flex_parser_types)
    run_compat_if_present('src/core/fastboot/fastboot.cpp', ensure_fastboot_unique_fd_compat)
    run_compat_if_present('src/adb/adb_mdns.h', ensure_adb_mdns_function_include)
    run_compat_if_present('src/adb/tls/include/adb/tls/tls_connection.h', ensure_adb_tls_function_include)
    ensure_sdk_sandbox_aid_compat()
    run_compat_if_present('src/core/libutils/include/utils/LruCache.h', ensure_lru_cache_cxx17_compat)
    run_compat_if_present('src/art/libartbase/base/safe_map.h', ensure_art_safe_map_invoke_result_compat)
    run_compat_if_present('src/art/libartbase/base/string_view_cpp20.h', ensure_art_string_view_cpp20_compat)
    run_compat_if_present('src/boringssl/src/crypto/x509/t_x509.c', ensure_boringssl_x509_name_print_compat)
    run_compat_if_present('src/libbase/include/android-base/result.h', ensure_libbase_fmt_format_string_compat)
    run_compat_if_present('src/boringssl/src/crypto/fipsmodule/bn/internal.h', ensure_boringssl_bn_comba8_decl_compat)
    run_compat_if_present('src/base/tools/aapt2/io/Util.h', ensure_aapt2_protobuf_limit_compat)


def normalize_release_cmake_targets():
    """Apply narrowly scoped CMake compatibility for older official snapshots."""
    base_cmake = ROOT / 'lib/libbase.cmake'
    if base_cmake.is_file():
        text = base_cmake.read_text()
        text = re.sub(
            r'\n?# fdsan is introduced.*?target_compile_options\(libbase PUBLIC -U__ANDROID_API__ -D__ANDROID_API__=29\)\s*endif\(\)\s*',
            '\n', text, flags=re.S)
        text = re.sub(
            r'\n?if\(ANDROID\)\s*target_compile_options\(libbase PUBLIC -U__ANDROID_API__ -D__ANDROID_API__=29\)\s*endif\(\)\s*',
            '\n', text)
        marker = '# SDK_API24_LIBBASE_COMPAT'
        if marker not in text:
            text += (
                '\n' + marker + '\n'
                '# Keep the API-24 runtime baseline. fdsan is guarded by the target API in unique_fd.h.\n'
                '# C++17 avoids libc++20 locale wrappers unavailable before API 26; disabling\n'
                '# fortify for this header-heavy target avoids __sendto_chk (also API 26+).\n'
                'if(ANDROID)\n'
                '    set_property(TARGET libbase PROPERTY CXX_STANDARD 17)\n'
                '    target_compile_options(libbase PRIVATE -U_FORTIFY_SOURCE)\n'
                'endif()\n'
            )
        base_cmake.write_text(text)

    for relative in (
        'src/libbase/include/android-base/unique_fd.h',
        'src/core/base/include/android-base/unique_fd.h',
    ):
        path = ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text()
        text = re.sub(
            r'#if defined\(__BIONIC__\)(?!\s*&&)',
            '#if defined(__BIONIC__) && defined(__ANDROID_API__) && __ANDROID_API__ >= 29',
            text)
        path.write_text(text)

    root_cmake = ROOT / 'CMakeLists.txt'
    if root_cmake.is_file():
        text = root_cmake.read_text()
        marker = '# SDK_GTEST_DEPRECATED_COPY_COMPAT'
        if marker not in text:
            text += (
                '\n' + marker + '\n'
                '# Older AOSP BoringSSL DES macros intentionally fall through between cases.\n'
                'if(TARGET fipsmodule)\n'
                '    target_compile_options(fipsmodule PRIVATE -Wno-error=implicit-fallthrough)\n'
                'endif()\n'
                '# Older GoogleTest snapshots trigger sign-conversion in towlower(wchar_t).\n'
                'if(TARGET gtest)\n'
                '    target_compile_options(gtest PRIVATE -Wno-error=sign-conversion)\n'
                'endif()\n'
                '# Older AOSP GoogleTest snapshots trigger deprecated-copy under -Werror.\n'
                'foreach(_sdk_gtest_target IN ITEMS gmock gmock_main)\n'
                '    if(TARGET ${_sdk_gtest_target})\n'
                '        target_compile_options(${_sdk_gtest_target} PRIVATE -Wno-error=deprecated-copy)\n'
                '    endif()\n'
                'endforeach()\n'
            )
        root_cmake.write_text(text)

    fastboot_cmake = ROOT / 'platform-tools/fastboot.cmake'
    if fastboot_cmake.is_file():
        text = fastboot_cmake.read_text()
        marker = 'set(FASTBOOT_EXT4_SOURCES)'
        if marker not in text:
            text, count = re.subn(
                r'add_library\(libext4 STATIC\s+.*?\)\s*target_include_directories\(libext4 PRIVATE\s+.*?\)\s*',
                (
                    'set(FASTBOOT_EXT4_SOURCES)\n'
                    'foreach(_sdk_ext4_source IN ITEMS ext4_utils.cpp wipe.cpp ext4_sb.cpp)\n'
                    '    foreach(_sdk_ext4_dir IN ITEMS "${SRC}/extras/ext4_utils" "${SRC}/core/fs_mgr/libext4_utils")\n'
                    '        if(EXISTS "${_sdk_ext4_dir}/${_sdk_ext4_source}")\n'
                    '            list(APPEND FASTBOOT_EXT4_SOURCES "${_sdk_ext4_dir}/${_sdk_ext4_source}")\n'
                    '            break()\n'
                    '        endif()\n'
                    '    endforeach()\n'
                    'endforeach()\n'
                    'if(FASTBOOT_EXT4_SOURCES)\n'
                    '    add_library(libext4 STATIC ${FASTBOOT_EXT4_SOURCES})\n'
                    '    target_include_directories(libext4 PRIVATE\n'
                    '        ${SRC}/core/libsparse/include\n'
                    '        ${SRC}/core/include\n'
                    '        ${SRC}/selinux/libselinux/include\n'
                    '        ${SRC}/extras/ext4_utils/include\n'
                    '        ${SRC}/core/fs_mgr/libext4_utils/include\n'
                    '        ${SRC}/libbase/include\n'
                    '    )\n'
                    'else()\n'
                    '    # This release snapshot has no standalone ext4_utils sources.\n'
                    '    add_library(libext4 INTERFACE)\n'
                    'endif()\n\n'
                ),
                text, count=1, flags=re.S)
            if count:
                fastboot_cmake.write_text(text)

    dexdump_cmake = ROOT / 'build-tools/dexdump.cmake'
    if dexdump_cmake.is_file():
        text = dexdump_cmake.read_text()
        if '${SRC}/art/runtime' not in text:
            text = text.replace('set(INCLUDES\n', 'set(INCLUDES\n    ${SRC}/art/runtime\n', 1)
        marker = 'if(ART_PALETTE_APEX_SOURCE OR ART_PALETTE_FAKE_SOURCE)'
        if marker not in text:
            text, count = re.subn(
                r'add_library\(libartpalette STATIC\s+.*?\)\s*target_include_directories\(libartpalette PRIVATE \$\{INCLUDES\}\)\s*',
                (
                    'if(ART_PALETTE_APEX_SOURCE OR ART_PALETTE_FAKE_SOURCE)\n'
                    '    add_library(libartpalette STATIC\n'
                    '        ${ART_PALETTE_APEX_SOURCE}\n'
                    '        ${ART_PALETTE_FAKE_SOURCE}\n'
                    '    )\n'
                    '    target_include_directories(libartpalette PRIVATE ${INCLUDES})\n'
                    'else()\n'
                    '    add_library(libartpalette INTERFACE)\n'
                    '    target_include_directories(libartpalette INTERFACE ${INCLUDES})\n'
                    'endif()\n'
                ),
                text, count=1, flags=re.S)
        dexdump_cmake.write_text(text)

    
    
    # SDK_API24_SYSTEM_PROPERTY_COMPAT
    # Android 7.0 headers do not expose the API-26 property callback/wait APIs.
    # Preserve the API-24 target and emulate those operations with legacy property APIs.
    properties = ROOT / 'src/libbase/properties.cpp'
    if properties.is_file():
        source_text = properties.read_text()
        if 'sdk_system_property_read_callback' not in source_text:
            if '#include <thread>' not in source_text:
                source_text = source_text.replace(
                    '#include <chrono>', '#include <chrono>\n#include <thread>', 1)
            helper = r'''#if defined(__BIONIC__) && defined(__ANDROID__) && defined(__ANDROID_API__) && __ANDROID_API__ < 26
static void sdk_system_property_read_callback(
    const prop_info* pi,
    void (*callback)(void*, const char*, const char*, uint32_t),
    void* cookie) {
    char name[PROP_NAME_MAX] = {};
    char value[PROP_VALUE_MAX] = {};
    __system_property_read(pi, name, value);
    callback(cookie, name, value, __system_property_serial(pi));
}

static bool sdk_system_property_wait(
    const prop_info* pi, uint32_t old_serial, uint32_t* new_serial_ptr,
    const timespec* relative_timeout) {
    using Clock = std::chrono::steady_clock;
    const auto timeout = relative_timeout == nullptr
        ? std::chrono::nanoseconds::zero()
        : std::chrono::seconds(relative_timeout->tv_sec) +
              std::chrono::nanoseconds(relative_timeout->tv_nsec);
    const auto deadline = Clock::now() + timeout;
    for (;;) {
        const uint32_t current_serial =
            pi == nullptr ? __system_property_area_serial() : __system_property_serial(pi);
        if (current_serial != old_serial) {
            if (new_serial_ptr != nullptr) *new_serial_ptr = current_serial;
            return true;
        }
        if (Clock::now() >= deadline) return false;
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
}
#else
#define sdk_system_property_read_callback __system_property_read_callback
#define sdk_system_property_wait __system_property_wait
#endif
'''
            if 'namespace android {' not in source_text:
                raise RuntimeError('cannot locate namespace android in libbase properties.cpp')
            source_text = source_text.replace('namespace android {', helper + '\nnamespace android {', 1)
            source_text = source_text.replace(
                '__system_property_read_callback(', 'sdk_system_property_read_callback(')
            source_text = source_text.replace(
                '__system_property_wait(', 'sdk_system_property_wait(')
            source_text = source_text.replace(
                'instance->read_only_property_ = value;',
                'strlcpy(instance->cached_value_, value, PROP_VALUE_MAX);\n                    instance->read_only_property_ = instance->cached_value_;',
                1)
            properties.write_text(source_text)

    # API-30 liblog declarations are hidden when compiling against API 24.
    # Keep the release source's runtime baseline and use libbase's Q fallback.
    logging = ROOT / 'src/libbase/logging.cpp'
    if logging.is_file():
        source_text = logging.read_text()
        call = 'return __android_log_is_loggable(priority, tag, ANDROID_LOG_INFO);'
        position = source_text.find(call)
        if position >= 0:
            line_start = source_text.rfind('\n', 0, position) + 1
            indent = source_text[line_start:position]
            if 'gMinimumLogSeverity =' in source_text:
                fallback = (
                    '#if defined(__ANDROID_API__) && __ANDROID_API__ >= 30',
                    '    return __android_log_is_loggable(priority, tag, ANDROID_LOG_INFO);',
                    '#else',
                    '    (void)priority;',
                    '    (void)tag;',
                    '    return severity >= gMinimumLogSeverity;',
                    '#endif',
                )
            else:
                fallback = (
                    '#if defined(__ANDROID_API__) && __ANDROID_API__ >= 30',
                    '    return __android_log_is_loggable(priority, tag, ANDROID_LOG_INFO);',
                    '#else',
                    '    (void)tag;',
                    '    return priority >= ANDROID_LOG_INFO;',
                    '#endif',
                )
            replacement = '\n'.join(indent + line for line in fallback)
            source_text = source_text[:line_start] + replacement + source_text[position + len(call):]
            logging.write_text(source_text)

    # Some historical Google manifests do not contain external/fmtlib.
    # Only link fmt when that exact release snapshot provides its target.
    androidfw_cmake = ROOT / 'lib/libandroidfw.cmake'
    if androidfw_cmake.is_file():
        source_text = androidfw_cmake.read_text()
        fmt_link = 'target_link_libraries(libandroidfw PUBLIC fmt::fmt)'
        if fmt_link in source_text and 'if(TARGET fmt::fmt)' not in source_text:
            source_text = source_text.replace(
                fmt_link,
                'if(TARGET fmt::fmt)\n    ' + fmt_link + '\nendif()',
                1)
            androidfw_cmake.write_text(source_text)

    veridex_cmake = ROOT / 'others/veridex.cmake'
    if veridex_cmake.is_file():
        source_text = veridex_cmake.read_text()
        if 'fmt::fmt' in source_text:
            source_text = source_text.replace('    fmt::fmt\n', '', 1)
            if 'if(TARGET fmt::fmt)' not in source_text:
                source_text += (
                    '\n# SDK_OPTIONAL_FMT_TARGET_COMPAT\n'
                    'if(TARGET fmt::fmt)\n'
                    '    target_link_libraries(veridex fmt::fmt)\n'
                    'endif()\n'
                )
            veridex_cmake.write_text(source_text)


    # SDK_ZLIB_PRIVATE_HEADERS_COMPAT
    # zlib's implementation files include zutil.h from their own source directory.
    zlib_cmake = ROOT / 'cmake/zlib.cmake'
    if zlib_cmake.is_file():
        source_text = zlib_cmake.read_text()
        public_include = 'target_include_directories(sdk_zlib PUBLIC ' + '$' + '{SDK_ZLIB_INCLUDE_DIR}' + ')'
        private_include = 'target_include_directories(sdk_zlib PRIVATE ' + '$' + '{SDK_ZLIB_SOURCE_DIR}' + ')'
        if public_include in source_text and private_include not in source_text:
            source_text = source_text.replace(
                public_include, public_include + '\n' + private_include, 1)
            zlib_cmake.write_text(source_text)

    
    # SDK_SKIP_UPSTREAM_CMAKE_PACKAGE_EXPORTS
    # This repository ships executable archives, not CMake packages. Some AOSP
    # subprojects inherit the top-level project name and emit unbound export sets.
    cmake_files = set(ROOT.rglob('CMakeLists.txt')) | set(ROOT.rglob('*.cmake'))
    export_pattern = re.compile(r'(?im)^[ \t]*install\s*\(\s*EXPORT\b')
    for cmake_file in sorted(cmake_files):
        if any(part in ('.git', 'build', 'host-tools') for part in cmake_file.parts):
            continue
        if cmake_file == ROOT / 'CMakeLists.txt' or not cmake_file.is_file():
            continue
        source_text = cmake_file.read_text()
        if 'install(EXPORT' not in source_text:
            continue
        changed = False
        while True:
            match = export_pattern.search(source_text)
            if match is None:
                break
            command_start = match.start()
            open_pos = source_text.find('(', command_start)
            depth = 0
            in_quote = False
            escaped = False
            command_end = None
            for index in range(open_pos, len(source_text)):
                char = source_text[index]
                if char == '"' and not escaped:
                    in_quote = not in_quote
                if not in_quote:
                    if char == '(':
                        depth += 1
                    elif char == ')':
                        depth -= 1
                        if depth == 0:
                            command_end = index + 1
                            break
                if char == '\\' and not escaped:
                    escaped = True
                else:
                    escaped = False
            if command_end is None:
                break
            source_text = (
                source_text[:command_start] +
                '# SDK: upstream CMake package export omitted; this build ships binaries only.\n' +
                source_text[command_end:]
            )
            changed = True
        if changed:
            cmake_file.write_text(source_text)
            print('release CMake: removed upstream install(EXPORT) from {}'.format(
                cmake_file.relative_to(ROOT)), flush=True)

    # SDK_FILTER_MISSING_RELEASE_SOURCES
    # The shared CMake lists are newer than some official release snapshots.
    # Keep the exact checked-out sources and omit only source paths absent from
    # that snapshot; later releases retain their files and therefore retain them.
    source_extensions = ('.c', '.cc', '.cpp', '.cxx', '.s', '.m', '.mm')
    for directory in ('lib', 'build-tools', 'platform-tools'):
        for cmake_file in sorted((ROOT / directory).glob('*.cmake')):
            lines = cmake_file.read_text().splitlines(keepends=True)
            output = []
            in_target = False
            depth = 0
            removed = []
            for original_line in lines:
                line = original_line
                if not in_target and re.search(r'\badd_(?:library|executable)\s*\(', original_line):
                    in_target = True
                    depth = 0
                if in_target and not original_line.lstrip().startswith('#'):
                    matches = list(re.finditer(r'\$\{SRC\}/([^\s\")]+)', line))
                    for match in reversed(matches):
                        relative = match.group(1)
                        if not relative.lower().endswith(source_extensions):
                            continue
                        if (ROOT / 'src' / relative).is_file():
                            continue
                        token = match.group(0)
                        normalized_line = line.strip().rstrip(',').strip()
                        if normalized_line in (token, '"' + token + '"', "'" + token + "'"):
                            line = ''
                            removed.append(relative)
                            break
                        line = line.replace(token, '')
                        removed.append(relative)
                if line:
                    output.append(line)
                if in_target:
                    depth += original_line.count('(') - original_line.count(')')
                    if depth <= 0:
                        in_target = False
            if removed:
                cmake_file.write_text(''.join(output))
                print('release CMake source filter {}: removed {}'.format(
                    cmake_file.relative_to(ROOT), ', '.join(sorted(set(removed)))), flush=True)



def ensure_historical_android_api_compat():
    """Fix historical AOSP source/API mismatches for the API-24 static build."""
    # SDK_AIDL_BISON_CPP_PURE_COMPAT
    # Bison 3.x rejects api.pure when the C++ lalr1.cc skeleton does not consume it.
    # The legacy %pure-parser directive is retained for the AIDL parser's supported
    # Bison compatibility path and avoids the unused api.pure %define error.
    aidl_grammar = ROOT / 'src/aidl/aidl_language_y.yy'
    if aidl_grammar.is_file():
        grammar = aidl_grammar.read_text()
        grammar, count = re.subn(
            r'(?m)^[ \t]*%define[ \t]+api\.pure(?:[ \t]+(?:true|full))?[ \t]*    # Keep VectorImpl's safe_iop.h include. The matching external/safe-iop
    # project is fetched from the selected Google manifest snapshot.
    zip_cmake = ROOT / 'lib/libziparchive.cmake'
    if zip_cmake.is_file():
        text = zip_cmake.read_text()
        marker = '# SDK_HISTORICAL_LIBUTILS_INCLUDE_COMPAT'
        if marker not in text:
            text += (
                '\n' + marker + '\n'
                'if(EXISTS "' + '$' + '{SRC}/core/libutils/include/utils/Compat.h")\n'
                '    target_include_directories(libziparchive PRIVATE "' + '$' + '{SRC}/core/libutils/include")\n'
                'elseif(EXISTS "' + '$' + '{SRC}/libutils/include/utils/Compat.h")\n'
                '    target_include_directories(libziparchive PRIVATE "' + '$' + '{SRC}/libutils/include")\n'
                'endif()\n'
            )
            zip_cmake.write_text(text)

    cgroup_header = ROOT / 'src/core/libprocessgroup/cgrouprc/include/android/cgrouprc.h'
    if cgroup_header.is_file():
        header = cgroup_header.read_text()
        header, guard_count = re.subn(
            r'(?m)^[ \t]*#if[ \t]+__ANDROID_API__[ \t]*>=[ \t]*__ANDROID_API_Q__[ \t]*\n',
            '', header, count=1)
        if guard_count:
            if header.rstrip().endswith('#endif'):
                header = header.rstrip()[:-len('#endif')].rstrip() + '\n'
            else:
                header, _ = re.subn(
                    r'(?m)^[ \t]*#endif[ \t]*\n(?=[ \t]*__END_DECLS)',
                    '', header, count=1)
            if '__END_DECLS' not in header:
                header = header.rstrip() + '\n\n__END_DECLS\n'
            cgroup_header.write_text(header)
        # These declarations are private to the in-tree libprocessgroup implementation.
        # Remove public SDK availability attributes so the code can stay at API 24.
        header = re.sub(r'\s*__INTRODUCED_IN\s*\([^)]*\)', '', header)
        cgroup_header.write_text(header)
        if '__ANDROID_API_Q__' in header and 'ACgroupFile_getVersion' in header:
            raise RuntimeError('cgrouprc API declarations remain hidden by an API guard')

    processgroup_cmake = ROOT / 'lib/libprocessgroup.cmake'
    if processgroup_cmake.is_file():
        text = processgroup_cmake.read_text()
        marker = '# SDK_HISTORICAL_CGROUPRC_API_SOURCES'
        if marker not in text:
            anchor = 'add_library(libprocessgroup STATIC\n'
            if anchor not in text:
                raise RuntimeError('libprocessgroup CMake target anchor not found')
            block = (
                marker + '\n'
                'set(LIBPROCESSGROUP_CGROUPRC_API_SOURCES)\n'
                'foreach(_cgrouprc_api_source\n'
                '    "' + '$' + '{SRC}/core/libprocessgroup/cgrouprc/a_cgroup_controller.cpp"\n'
                '    "' + '$' + '{SRC}/core/libprocessgroup/cgrouprc/a_cgroup_file.cpp")\n'
                '    if(EXISTS "' + '$' + '{_cgrouprc_api_source}")\n'
                '        list(APPEND LIBPROCESSGROUP_CGROUPRC_API_SOURCES "' + '$' + '{_cgrouprc_api_source}")\n'
                '    endif()\n'
                'endforeach()\n\n'
            )
            text = text.replace(anchor, block + anchor, 1)
            text = text.replace(
                anchor,
                anchor + '    ' + '$' + '{LIBPROCESSGROUP_CGROUPRC_API_SOURCES}\n',
                1)
            processgroup_cmake.write_text(text)

    buildversion = ROOT / 'src/soong/cc/libbuildversion/libbuildversion.cpp'
    if buildversion.is_file():
        source = buildversion.read_text()
        callback = re.compile(
            r'__system_property_read_callback\s*\(\s*pi\s*,\s*'
            r'\[\]\s*\(\s*void\s*\*\s*cookie\s*,\s*const\s+char\s*\*\s*,\s*'
            r'const\s+char\s*\*\s*value\s*,\s*(?:unsigned|uint32_t)\s*\)\s*'
            r'\{\s*auto\s+property_value\s*=\s*reinterpret_cast<std::string\s*\*>\(cookie\)\s*;\s*'
            r'\*property_value\s*=\s*value\s*;\s*\}\s*,\s*&property_value\s*\)\s*;',
            re.S)
        source, count = callback.subn(
            'char property_name[PROP_NAME_MAX] = {};\n'
            '    char property_buffer[PROP_VALUE_MAX] = {};\n'
            '    if (__system_property_read(pi, property_name, property_buffer) >= 0) {\n'
            '        property_value = property_buffer;\n'
            '    }',
            source, count=1)
        if count:
            buildversion.write_text(source)
        elif '__system_property_read_callback' in source:
            raise RuntimeError('unhandled property callback in {}'.format(buildversion))

    zip_archive = ROOT / 'src/libziparchive/zip_archive.cc'
    if zip_archive.is_file():
        source = zip_archive.read_text()
        source = source.replace(
            '#if defined(__BIONIC__)',
            '#if defined(__BIONIC__) && defined(__ANDROID_API__) && __ANDROID_API__ >= 29'
        )
        zip_archive.write_text(source)

    selinux_cmake = ROOT / 'lib/libselinux.cmake'
    if selinux_cmake.is_file():
        source = selinux_cmake.read_text()
        marker = '# SDK_HISTORICAL_BORINGSSL_INCLUDE_COMPAT'
        if marker not in source:
            source += (
                '\n' + marker + '\n'
                'if(EXISTS "' + '$' + '{SRC}/boringssl/src/include/openssl/sha.h")\n'
                '    target_include_directories(libselinux PRIVATE "' + '$' + '{SRC}/boringssl/src/include")\n'
                'endif()\n'
            )
            selinux_cmake.write_text(source)


    # ART FdFile uses fdsan APIs introduced in API 29. Keep API-24
    # builds on ordinary close() semantics.
    for fd_file in (ROOT / 'src/art/libartbase/base/unix_file/fd_file.cc',
                    ROOT / 'src/art/runtime/base/unix_file/fd_file.cc'):
        if fd_file.is_file():
            source = fd_file.read_text()
            source = source.replace('#if defined(__BIONIC__)',
                                    '#if defined(__BIONIC__) && defined(__ANDROID_API__) && __ANDROID_API__ >= 29')
            fd_file.write_text(source)

    # Format the enum class as an integer in ART's fatal diagnostic.
    for dex_file in (ROOT / 'src/art/libdexfile/dex/dex_file.cc',
                     ROOT / 'src/art/runtime/dex_file.cc'):
        if dex_file.is_file():
            source = dex_file.read_text()
            source, count = re.subn(r'(UNIMPLEMENTED\(FATAL\)\s*<<\s*": type "\s*<<\s*)type_(\s*;)',
                                   r'\1static_cast<int>(type_)\2', source, count=1)
            if count:
                dex_file.write_text(source)

    # Align legacy liblog headers with the message-based logger implementation.
    for log_header in (ROOT / 'src/logging/liblog/include/android/log.h',
                       ROOT / 'src/core/liblog/include/android/log.h'):
        if log_header.is_file():
            header = log_header.read_text()
            header, _ = re.subn(r'typedef\s+void\s*\(\s*\*__android_logger_function\s*\)\s*\(\s*const\s+struct\s+__android_logger_data\s*\*\s*\w+\s*,\s*const\s+char\s*\*\s*\w+\s*\)\s*;',
                                'typedef void (*__android_logger_function)(const struct __android_log_message* log_message);',
                                header, count=1)
            header, _ = re.subn(r'void\s+__android_log_logd_logger\s*\(\s*const\s+struct\s+__android_logger_data\s*\*\s*\w+\s*,\s*const\s+char\s*\*\s*\w+\s*\)\s*;',
                                'void __android_log_logd_logger(const struct __android_log_message* log_message);',
                                header, count=1)
            header, _ = re.subn(r'void\s+__android_log_stderr_logger\s*\(\s*const\s+struct\s+__android_logger_data\s*\*\s*\w+\s*,\s*const\s+char\s*\*\s*\w+\s*\)\s*;',
                                'void __android_log_stderr_logger(const struct __android_log_message* log_message);',
                                header, count=1)
            log_header.write_text(header)


def main():
    version = tools_version()
    parser = argparse.ArgumentParser()
    parser.add_argument('--tags', default='platform-tools-{}'.format(version),
                        help='git tag or branch of the AOSP repositories, default is platform-tools-{} '
                             '(from patches/misc/platform_tools_version.h)'.format(version))
    parser.add_argument('--jobs', type=int, default=8, help='clone N repositories in parallel')
    parser.add_argument('--retries', type=int, default=3, help='retry times of a failed clone')
    parser.add_argument('--skip-patch', action='store_true', help='only clone, do not patch the sources')
    parser.add_argument('--normalize-optional-sources-only', action='store_true', help='normalize CMake sources against an already fetched source tree')
    args = parser.parse_args()

    if args.normalize_optional_sources_only:
        create_legacy_source_aliases()
        normalize_optional_release_sources()
        ensure_liblog_ndk_r27_compat()
        ensure_art_build_defines()
        ensure_art_memory_tool_compat()
        normalize_release_cmake_targets()
        ensure_historical_android_api_compat()
        return

    # check necessary packages
    for command in ('git', 'patch', 'go', 'bison', 'flex'):
        check(command)

    repos = json.loads((ROOT / 'repository.json').read_text())
    print('fetching sources from Google manifest: {}'.format(args.tags))
    repos = resolve_manifest_revisions(repos, args.tags, args.retries)
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

    create_legacy_source_aliases()
    normalize_optional_release_sources()
    ensure_liblog_ndk_r27_compat()

    if not args.skip_patch:
        patches()

    normalize_release_cmake_targets()
    ensure_historical_android_api_compat()
    print('download success!!')


if __name__ == '__main__':
    main()
,
            '%pure-parser',
            grammar,
            count=1,
        )
        if count:
            aidl_grammar.write_text(grammar)
        if re.search(r'(?m)^[ \t]*%define[ \t]+api\.pure\b', aidl_grammar.read_text()):
            raise RuntimeError('AIDL Bison grammar still contains unsupported api.pure: {}'.format(aidl_grammar))
        print('AIDL Bison: normalized legacy pure-parser directive', flush=True)

    # SDK_LIBBASE_LOGGER_CALLBACK_COMPAT
    # The pinned liblog header uses the API-30 message callback structure, while
    # older libbase snapshots still pass the pre-API-30 two-argument callback.
    logging = ROOT / 'src/libbase/logging.cpp'
    if logging.is_file():
        source_text = logging.read_text()
        old_signature = re.compile(
            r'\[\]\s*\(\s*const struct __android_logger_data\s*\*\s*logger_data\s*,\s*'
            r'const char\s*\*\s*message\s*\)\s*\{'
        )
        new_signature = '[](const struct __android_log_message* log_message) {'
        if old_signature.search(source_text):
            source_text = old_signature.sub(new_signature, source_text, count=1)
            source_text = source_text.replace('logger_data->', 'log_message->')
            source_text = source_text.replace(
                'function(log_id, severity, log_message->tag, log_message->file, log_message->line, message);',
                'function(log_id, severity, log_message->tag, log_message->file, log_message->line, log_message->message);',
                1,
            )
            logging.write_text(source_text)
        if old_signature.search(logging.read_text()):
            raise RuntimeError('legacy libbase logger callback signature remains in {}'.format(logging))
        if 'log_message->message' not in logging.read_text() and '__android_log_set_logger' in logging.read_text():
            raise RuntimeError('libbase logger callback message field was not normalized: {}'.format(logging))

    # SDK_CGROUPRC_FLAGS_API24_DECLARATION_COMPAT
    # The implementation is built from this same manifest-pinned source tree,
    # but the public declaration may be hidden by the API-30 availability guard.
    cgroup_header = ROOT / 'src/core/libprocessgroup/cgrouprc/include/android/cgrouprc.h'
    if cgroup_header.is_file():
        header = cgroup_header.read_text()
        prototype = 'uint32_t ACgroupController_getFlags(const ACgroupController* controller);'
        if prototype not in header:
            anchor = '__END_DECLS'
            if anchor not in header:
                raise RuntimeError('cannot locate C linkage end in {}'.format(cgroup_header))
            if 'ACgroupController' not in header:
                raise RuntimeError('ACgroupController type is absent from {}'.format(cgroup_header))
            header = header.replace(anchor, prototype + '\n\n' + anchor, 1)
            cgroup_header.write_text(header)
        if prototype not in cgroup_header.read_text():
            raise RuntimeError('Cgroup Flags API declaration missing from {}'.format(cgroup_header))
        print('libprocessgroup: exposed manifest-local Cgroup Flags declaration for API-24 build', flush=True)

    # Keep VectorImpl's safe_iop.h include. The matching external/safe-iop
    # project is fetched from the selected Google manifest snapshot.
    zip_cmake = ROOT / 'lib/libziparchive.cmake'
    if zip_cmake.is_file():
        text = zip_cmake.read_text()
        marker = '# SDK_HISTORICAL_LIBUTILS_INCLUDE_COMPAT'
        if marker not in text:
            text += (
                '\n' + marker + '\n'
                'if(EXISTS "' + '$' + '{SRC}/core/libutils/include/utils/Compat.h")\n'
                '    target_include_directories(libziparchive PRIVATE "' + '$' + '{SRC}/core/libutils/include")\n'
                'elseif(EXISTS "' + '$' + '{SRC}/libutils/include/utils/Compat.h")\n'
                '    target_include_directories(libziparchive PRIVATE "' + '$' + '{SRC}/libutils/include")\n'
                'endif()\n'
            )
            zip_cmake.write_text(text)

    cgroup_header = ROOT / 'src/core/libprocessgroup/cgrouprc/include/android/cgrouprc.h'
    if cgroup_header.is_file():
        header = cgroup_header.read_text()
        header, guard_count = re.subn(
            r'(?m)^[ \t]*#if[ \t]+__ANDROID_API__[ \t]*>=[ \t]*__ANDROID_API_Q__[ \t]*\n',
            '', header, count=1)
        if guard_count:
            if header.rstrip().endswith('#endif'):
                header = header.rstrip()[:-len('#endif')].rstrip() + '\n'
            else:
                header, _ = re.subn(
                    r'(?m)^[ \t]*#endif[ \t]*\n(?=[ \t]*__END_DECLS)',
                    '', header, count=1)
            if '__END_DECLS' not in header:
                header = header.rstrip() + '\n\n__END_DECLS\n'
            cgroup_header.write_text(header)
        # These declarations are private to the in-tree libprocessgroup implementation.
        # Remove public SDK availability attributes so the code can stay at API 24.
        header = re.sub(r'\s*__INTRODUCED_IN\s*\([^)]*\)', '', header)
        cgroup_header.write_text(header)
        if '__ANDROID_API_Q__' in header and 'ACgroupFile_getVersion' in header:
            raise RuntimeError('cgrouprc API declarations remain hidden by an API guard')

    processgroup_cmake = ROOT / 'lib/libprocessgroup.cmake'
    if processgroup_cmake.is_file():
        text = processgroup_cmake.read_text()
        marker = '# SDK_HISTORICAL_CGROUPRC_API_SOURCES'
        if marker not in text:
            anchor = 'add_library(libprocessgroup STATIC\n'
            if anchor not in text:
                raise RuntimeError('libprocessgroup CMake target anchor not found')
            block = (
                marker + '\n'
                'set(LIBPROCESSGROUP_CGROUPRC_API_SOURCES)\n'
                'foreach(_cgrouprc_api_source\n'
                '    "' + '$' + '{SRC}/core/libprocessgroup/cgrouprc/a_cgroup_controller.cpp"\n'
                '    "' + '$' + '{SRC}/core/libprocessgroup/cgrouprc/a_cgroup_file.cpp")\n'
                '    if(EXISTS "' + '$' + '{_cgrouprc_api_source}")\n'
                '        list(APPEND LIBPROCESSGROUP_CGROUPRC_API_SOURCES "' + '$' + '{_cgrouprc_api_source}")\n'
                '    endif()\n'
                'endforeach()\n\n'
            )
            text = text.replace(anchor, block + anchor, 1)
            text = text.replace(
                anchor,
                anchor + '    ' + '$' + '{LIBPROCESSGROUP_CGROUPRC_API_SOURCES}\n',
                1)
            processgroup_cmake.write_text(text)

    buildversion = ROOT / 'src/soong/cc/libbuildversion/libbuildversion.cpp'
    if buildversion.is_file():
        source = buildversion.read_text()
        callback = re.compile(
            r'__system_property_read_callback\s*\(\s*pi\s*,\s*'
            r'\[\]\s*\(\s*void\s*\*\s*cookie\s*,\s*const\s+char\s*\*\s*,\s*'
            r'const\s+char\s*\*\s*value\s*,\s*(?:unsigned|uint32_t)\s*\)\s*'
            r'\{\s*auto\s+property_value\s*=\s*reinterpret_cast<std::string\s*\*>\(cookie\)\s*;\s*'
            r'\*property_value\s*=\s*value\s*;\s*\}\s*,\s*&property_value\s*\)\s*;',
            re.S)
        source, count = callback.subn(
            'char property_name[PROP_NAME_MAX] = {};\n'
            '    char property_buffer[PROP_VALUE_MAX] = {};\n'
            '    if (__system_property_read(pi, property_name, property_buffer) >= 0) {\n'
            '        property_value = property_buffer;\n'
            '    }',
            source, count=1)
        if count:
            buildversion.write_text(source)
        elif '__system_property_read_callback' in source:
            raise RuntimeError('unhandled property callback in {}'.format(buildversion))

    zip_archive = ROOT / 'src/libziparchive/zip_archive.cc'
    if zip_archive.is_file():
        source = zip_archive.read_text()
        source = source.replace(
            '#if defined(__BIONIC__)',
            '#if defined(__BIONIC__) && defined(__ANDROID_API__) && __ANDROID_API__ >= 29'
        )
        zip_archive.write_text(source)

    selinux_cmake = ROOT / 'lib/libselinux.cmake'
    if selinux_cmake.is_file():
        source = selinux_cmake.read_text()
        marker = '# SDK_HISTORICAL_BORINGSSL_INCLUDE_COMPAT'
        if marker not in source:
            source += (
                '\n' + marker + '\n'
                'if(EXISTS "' + '$' + '{SRC}/boringssl/src/include/openssl/sha.h")\n'
                '    target_include_directories(libselinux PRIVATE "' + '$' + '{SRC}/boringssl/src/include")\n'
                'endif()\n'
            )
            selinux_cmake.write_text(source)


    # ART FdFile uses fdsan APIs introduced in API 29. Keep API-24
    # builds on ordinary close() semantics.
    for fd_file in (ROOT / 'src/art/libartbase/base/unix_file/fd_file.cc',
                    ROOT / 'src/art/runtime/base/unix_file/fd_file.cc'):
        if fd_file.is_file():
            source = fd_file.read_text()
            source = source.replace('#if defined(__BIONIC__)',
                                    '#if defined(__BIONIC__) && defined(__ANDROID_API__) && __ANDROID_API__ >= 29')
            fd_file.write_text(source)

    # Format the enum class as an integer in ART's fatal diagnostic.
    for dex_file in (ROOT / 'src/art/libdexfile/dex/dex_file.cc',
                     ROOT / 'src/art/runtime/dex_file.cc'):
        if dex_file.is_file():
            source = dex_file.read_text()
            source, count = re.subn(r'(UNIMPLEMENTED\(FATAL\)\s*<<\s*": type "\s*<<\s*)type_(\s*;)',
                                   r'\1static_cast<int>(type_)\2', source, count=1)
            if count:
                dex_file.write_text(source)

    # Align legacy liblog headers with the message-based logger implementation.
    for log_header in (ROOT / 'src/logging/liblog/include/android/log.h',
                       ROOT / 'src/core/liblog/include/android/log.h'):
        if log_header.is_file():
            header = log_header.read_text()
            header, _ = re.subn(r'typedef\s+void\s*\(\s*\*__android_logger_function\s*\)\s*\(\s*const\s+struct\s+__android_logger_data\s*\*\s*\w+\s*,\s*const\s+char\s*\*\s*\w+\s*\)\s*;',
                                'typedef void (*__android_logger_function)(const struct __android_log_message* log_message);',
                                header, count=1)
            header, _ = re.subn(r'void\s+__android_log_logd_logger\s*\(\s*const\s+struct\s+__android_logger_data\s*\*\s*\w+\s*,\s*const\s+char\s*\*\s*\w+\s*\)\s*;',
                                'void __android_log_logd_logger(const struct __android_log_message* log_message);',
                                header, count=1)
            header, _ = re.subn(r'void\s+__android_log_stderr_logger\s*\(\s*const\s+struct\s+__android_logger_data\s*\*\s*\w+\s*,\s*const\s+char\s*\*\s*\w+\s*\)\s*;',
                                'void __android_log_stderr_logger(const struct __android_log_message* log_message);',
                                header, count=1)
            log_header.write_text(header)


def main():
    version = tools_version()
    parser = argparse.ArgumentParser()
    parser.add_argument('--tags', default='platform-tools-{}'.format(version),
                        help='git tag or branch of the AOSP repositories, default is platform-tools-{} '
                             '(from patches/misc/platform_tools_version.h)'.format(version))
    parser.add_argument('--jobs', type=int, default=8, help='clone N repositories in parallel')
    parser.add_argument('--retries', type=int, default=3, help='retry times of a failed clone')
    parser.add_argument('--skip-patch', action='store_true', help='only clone, do not patch the sources')
    parser.add_argument('--normalize-optional-sources-only', action='store_true', help='normalize CMake sources against an already fetched source tree')
    args = parser.parse_args()

    if args.normalize_optional_sources_only:
        create_legacy_source_aliases()
        normalize_optional_release_sources()
        ensure_liblog_ndk_r27_compat()
        ensure_art_build_defines()
        ensure_art_memory_tool_compat()
        normalize_release_cmake_targets()
        ensure_historical_android_api_compat()
        return

    # check necessary packages
    for command in ('git', 'patch', 'go', 'bison', 'flex'):
        check(command)

    repos = json.loads((ROOT / 'repository.json').read_text())
    print('fetching sources from Google manifest: {}'.format(args.tags))
    repos = resolve_manifest_revisions(repos, args.tags, args.retries)
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

    create_legacy_source_aliases()
    normalize_optional_release_sources()
    ensure_liblog_ndk_r27_compat()

    if not args.skip_patch:
        patches()

    normalize_release_cmake_targets()
    ensure_historical_android_api_compat()
    print('download success!!')


if __name__ == '__main__':
    main()
