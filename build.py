#!/usr/bin/env python3
#
# Copyright © 2022 Github Lzhiyong
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# pylint: disable=not-callable, line-too-long, no-else-return

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# canonical arch name -> android abi / zig target
ARCHS = {
    'aarch64': {'abi': 'arm64-v8a',   'zig': 'aarch64-linux-{libc}'},
    'arm':     {'abi': 'armeabi-v7a', 'zig': 'arm-linux-{libc}eabihf'},
    'x86_64':  {'abi': 'x86_64',      'zig': 'x86_64-linux-{libc}'},
    'i686':    {'abi': 'x86',         'zig': 'x86-linux-{libc}'},
}

ARCH_ALIASES = {
    'arm64': 'aarch64', 'arm64-v8a': 'aarch64',
    'armeabi-v7a': 'arm', 'armv7': 'arm', 'armv7a': 'arm', 'armhf': 'arm',
    'x86': 'i686', 'i386': 'i686', 'x64': 'x86_64', 'amd64': 'x86_64',
}

# the android tools
ANDROID_TOOLS = {
    'build-tools': ['aapt', 'aapt2', 'aidl', 'zipalign', 'dexdump', 'split-select'],
    'platform-tools': [
        'adb', 'fastboot', 'sqlite3', 'etc1tool', 'hprof-conv',
        'e2fsdroid', 'sload_f2fs', 'mke2fs', 'make_f2fs', 'make_f2fs_casefold'
    ],
    'others': ['veridex'],
}


def format_time(seconds):
    minute, sec = divmod(seconds, 60)
    hour, minute = divmod(minute, 60)

    hour = int(hour)
    minute = int(minute)
    if minute < 1:
        sec = float('%.2f' % sec)
    else:
        sec = int(sec)

    if hour != 0:
        return '{}h{}m{}s'.format(hour, minute, sec)
    elif minute != 0:
        return '{}m{}s'.format(minute, sec)
    else:
        return '{}s'.format(sec)


def info(message):
    print('\033[1;34m{}\033[0m'.format(message), flush=True)


def run(command, **kwargs):
    command = [str(c) for c in command]
    print('+ ' + ' '.join(command), flush=True)
    result = subprocess.run(command, **kwargs)
    if result.returncode != 0:
        sys.exit(result.returncode)
    return result


def tools_version():
    text = (ROOT / 'patches/misc/platform_tools_version.h').read_text()
    match = re.search(r'^\s*#define\s+PLATFORM_TOOLS_VERSION\s+"([^"]+)"', text, re.M)
    return match.group(1) if match else 'unknown'


def normalize_arch(arch):
    arch = ARCH_ALIASES.get(arch, arch)
    if arch not in ARCHS:
        sys.exit('unsupported arch: {}, choose from {}'.format(arch, ', '.join(ARCHS)))
    return arch


# =============================== host protoc ===============================
def find_protoc(directory):
    if (directory / 'protoc').is_file():
        return directory / 'protoc'
    for candidate in sorted(directory.glob('protoc-*')):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def build_host_protoc(args):
    """Build protoc with the host compiler from the version-matched AOSP source."""
    source = ROOT / 'src/protobuf'
    build_dir = (ROOT / args.host_build).resolve()
    protoc = find_protoc(build_dir)
    if protoc is not None:
        return protoc

    info('building host protoc ...')
    # Always use the build machine compilers, never the Android cross compiler.
    env = {k: v for k, v in os.environ.items()
           if k not in ('CC', 'CXX', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS')}

    cmake_file = source / 'CMakeLists.txt'
    if cmake_file.is_file():
        # Newer AOSP protobuf snapshots include their upstream CMake build.
        run(['cmake', '-GNinja', '-S', source, '-B', build_dir,
             '-DCMAKE_BUILD_TYPE=Release',
             '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
             '-Dprotobuf_BUILD_TESTS=OFF',
             '-Dprotobuf_WITH_ZLIB=OFF'], env=env)
        run(['cmake', '--build', build_dir, '--target', 'protoc', '-j', args.jobs], env=env)
        protoc = find_protoc(build_dir)
    elif ((source / 'autogen.sh').is_file()
          and (source / 'configure.ac').is_file()
          and (source / 'src/google/protobuf/compiler/main.cc').is_file()):
        # API 33 AOSP protobuf predates the checked-in CMake build files.
        # Build its own autotools project rather than borrowing a newer protobuf
        # CMakeLists.txt or silently using a host-installed protoc.
        autotools_build = build_dir / 'autotools'
        autotools_build.mkdir(parents=True, exist_ok=True)
        # Old AOSP protobuf autogen.sh downloads gmock-1.7.0 from the retired
        # googlecode.com URL whenever this directory is absent. gmock is only
        # needed by protobuf's unit tests, which are not built for host protoc.
        # An empty marker directory lets autoreconf proceed without fetching
        # an unrelated, obsolete test dependency.
        (source / 'gmock').mkdir(exist_ok=True)
        run([source / 'autogen.sh'], cwd=source, env=env)
        run([source / 'configure', '--disable-shared', '--enable-static'],
            cwd=autotools_build, env=env)
        run(['make', '-j', str(args.jobs), 'protoc'],
            cwd=autotools_build / 'src', env=env)
        candidate = autotools_build / 'src/protoc'
        protoc = candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None
    else:
        sys.exit(
            'protobuf source is incomplete in {}; expected CMakeLists.txt or '
            'autogen.sh + configure.ac + src/google/protobuf/compiler/main.cc'.format(source)
        )

    if protoc is None:
        sys.exit('failed to build the host protoc from {}'.format(source))
    return protoc


# =============================== toolchains ===============================
def find_ndk(args):
    candidates = [args.ndk] + [os.environ.get(k) for k in
                               ('ANDROID_NDK_HOME', 'ANDROID_NDK_ROOT', 'ANDROID_NDK_LATEST_HOME', 'ANDROID_NDK')]
    for candidate in candidates:
        if candidate and (Path(candidate) / 'build/cmake/android.toolchain.cmake').exists():
            return Path(candidate).resolve()
    sys.exit('can not find the NDK, please set --ndk or ANDROID_NDK_HOME')


def toolchain_args(args):
    """return (cmake arguments, description) of the selected toolchain"""
    arch = ARCHS[args.arch]
    static = args.link == 'static'

    if args.toolchain == 'ndk':
        ndk = find_ndk(args)
        return [
            '-DCMAKE_TOOLCHAIN_FILE={}'.format(ndk / 'build/cmake/android.toolchain.cmake'),
            '-DANDROID_NDK={}'.format(ndk),
            '-DANDROID_ABI={}'.format(arch['abi']),
            '-DANDROID_PLATFORM=android-{}'.format(args.api),
            '-DANDROID_STL=c++_static',
            '-DANDROID_ARM_NEON=ON',
        ], 'ndk {} ({}, android-{})'.format(ndk.name, arch['abi'], args.api)

    if args.toolchain == 'zig':
        zig = args.zig or shutil.which('zig')
        if zig is None:
            sys.exit('can not find zig, please install it or set --zig')
        # zig only links musl statically, so glibc is used for the shared build
        target = args.zig_target or arch['zig'].format(libc='musl' if static else 'gnu')
        command = [
            '-DCMAKE_TOOLCHAIN_FILE={}'.format(ROOT / 'cmake/toolchains/zig.cmake'),
            '-DZIG_EXECUTABLE={}'.format(Path(shutil.which(zig) or zig).resolve()),
            '-DZIG_TARGET={}'.format(target),
        ]
        if args.zig_cpu:
            command.append('-DZIG_CPU={}'.format(args.zig_cpu))
        return command, 'zig ({})'.format(target)

    if args.toolchain == 'host':
        command = []
        cc = args.cc or os.environ.get('CC') or shutil.which('clang')
        cxx = args.cxx or os.environ.get('CXX') or shutil.which('clang++')
        if cc:
            command.append('-DCMAKE_C_COMPILER={}'.format(cc))
        if cxx:
            command.append('-DCMAKE_CXX_COMPILER={}'.format(cxx))
        return command, 'host ({} / {})'.format(cc or 'default', cxx or 'default')

    # custom toolchain file, e.g. a cross gcc / clang / musl-cross toolchain
    if not args.toolchain_file or not Path(args.toolchain_file).exists():
        sys.exit('--toolchain=custom requires an existing --toolchain-file')
    return ['-DCMAKE_TOOLCHAIN_FILE={}'.format(Path(args.toolchain_file).resolve())], \
        'custom ({})'.format(args.toolchain_file)


# =============================== package ===============================
def package(binary_dir, zip_path):
    """package the bin dir as a zip file, the executable permissions are kept"""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(binary_dir.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(binary_dir))


ELF_ABI = {
    # ELF class and e_machine values from the System V ABI.
    'aarch64': (2, 183),
    'arm': (1, 40),
    'x86_64': (2, 62),
    'i686': (1, 3),
}


def verify_package(zip_path, arch):
    """Verify every packaged native tool is an executable for the requested ABI."""
    expected = ELF_ABI[arch]
    required = [
        '{}/{}'.format(group, tool)
        for group, tools in ANDROID_TOOLS.items() for tool in tools
    ]
    with zipfile.ZipFile(zip_path) as archive:
        corrupt = archive.testzip()
        if corrupt is not None:
            raise RuntimeError('corrupt package member: {}'.format(corrupt))

        members = set(archive.namelist())
        missing = sorted(set(required) - members)
        if missing:
            raise RuntimeError('package is missing tools: {}'.format(', '.join(missing)))

        for name in required:
            entry = archive.getinfo(name)
            mode = (entry.external_attr >> 16) & 0o777
            if not mode & 0o111:
                raise RuntimeError('packaged tool is not executable: {} (mode {:04o})'.format(
                    name, mode))

            with archive.open(entry) as stream:
                header = stream.read(20)
            if len(header) < 20 or header[:4] != b'\x7fELF':
                raise RuntimeError('packaged tool is not an ELF executable: {}'.format(name))
            if header[4] != expected[0] or header[5] != 1:
                raise RuntimeError(
                    '{} has wrong ELF class/data for {}: class={}, data={}'.format(
                        name, arch, header[4], header[5]))
            machine = int.from_bytes(header[18:20], 'little')
            if machine != expected[1]:
                raise RuntimeError(
                    '{} has wrong ELF machine for {}: expected {}, got {}'.format(
                        name, arch, expected[1], machine))
            elf_type = int.from_bytes(header[16:18], 'little')
            if elf_type not in (2, 3):
                raise RuntimeError('{} is not an executable ELF image (type {})'.format(
                    name, elf_type))

    info('verified {} executable ELF tools for {}'.format(len(required), arch))


def complete(args, build_dir):
    binary_dir = build_dir / 'bin'
    missing = [
        '{}/{}'.format(tooldir, tool)
        for tooldir, tools in ANDROID_TOOLS.items() for tool in tools
        if not (binary_dir / tooldir / tool).exists()
    ]
    if args.target == ['all'] and missing:
        sys.exit('\033[1;31mmissing tools: {}\033[0m'.format(', '.join(missing)))
    if not binary_dir.exists():
        sys.exit('nothing was built in {}'.format(binary_dir))

    output_dir = Path(args.output_dir).resolve() if args.output_dir else build_dir
    zip_path = output_dir / 'android-sdk-tools-{}-{}.zip'.format(args.link, args.arch)
    package(binary_dir, zip_path)
    if args.target == ['all']:
        verify_package(zip_path, args.arch)
    info('package: {}'.format(zip_path))
    return zip_path


# =============================== build ===============================
def build(args):
    build_dir = Path(args.build or 'build/{}-{}-{}'.format(args.toolchain, args.link, args.arch))
    if not build_dir.is_absolute():
        build_dir = (Path.cwd() / build_dir).resolve()

    if args.protoc is not None:
        protoc = Path(args.protoc).resolve()
        if not protoc.exists():
            sys.exit('no such file or directory: {}'.format(args.protoc))
    else:
        protoc = build_host_protoc(args)

    toolchain, description = toolchain_args(args)
    info('platform-tools {}, arch {}, {} link, toolchain {}'.format(
        tools_version(), args.arch, args.link, description))

    if args.clean and build_dir.exists():
        shutil.rmtree(build_dir)

    command = ['cmake', '-GNinja', '-S', ROOT, '-B', build_dir,
               '-DCMAKE_BUILD_TYPE={}'.format(args.build_type),
               '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
               '-DSDK_STATIC={}'.format('ON' if args.link == 'static' else 'OFF'),
               '-DSDK_STRIP={}'.format('OFF' if args.no_strip else 'ON'),
               '-DPROTOC_PATH={}'.format(protoc)] + toolchain + args.cmake_args

    start_time = time.time()
    run(command)
    build_command = ['cmake', '--build', build_dir, '-j', args.jobs]
    if args.target != ['all']:
        build_command += ['--target'] + args.target
    run(build_command)

    complete(args, build_dir)
    info('build success cost time: {}'.format(format_time(time.time() - start_time)))


def main():
    parser = argparse.ArgumentParser(
        description='build the android platform-tools and build-tools',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    jobs = os.cpu_count() or 1

    parser.add_argument('--toolchain', choices=['ndk', 'zig', 'host', 'custom'], default='ndk',
                        help='ndk: android ndk (bionic); zig: zig cc (musl for static, glibc for shared); '
                             'host: compilers of the build machine ($CC/$CXX or clang); custom: --toolchain-file')
    parser.add_argument('--arch', '--abi', dest='arch', default='aarch64',
                        help='target arch: {} (android abi names are accepted too)'.format(', '.join(ARCHS)))
    parser.add_argument('--link', choices=['static', 'shared'], default='static',
                        help='link the executables statically or dynamically')

    ndk = parser.add_argument_group('ndk')
    ndk.add_argument('--ndk', help='the ndk path, default from $ANDROID_NDK_HOME / $ANDROID_NDK_ROOT')
    # Termux officially targets Android 7.0+ (API 24). Keep historical
    # Platform Tools builds runnable on that baseline; newer source snapshots
    # retain the API 30 baseline used by the current build.
    version_parts = tuple(int(part) for part in tools_version().split('.'))
    default_api = 24 if version_parts < (31, 0, 0) else 30
    ndk.add_argument('--api', type=int, default=default_api,
                     help='minimum Android API level (default: {})'.format(default_api))

    zig = parser.add_argument_group('zig')
    zig.add_argument('--zig', help='the zig executable, default is zig in PATH')
    zig.add_argument('--zig-target', help='override the zig target, e.g. aarch64-linux-musl')
    zig.add_argument('--zig-cpu', help='zig -mcpu value, e.g. baseline, cortex_a53')

    other = parser.add_argument_group('host / custom')
    other.add_argument('--cc', help='C compiler of --toolchain=host')
    other.add_argument('--cxx', help='C++ compiler of --toolchain=host')
    other.add_argument('--toolchain-file', help='CMake toolchain file of --toolchain=custom')

    parser.add_argument('--build', help='the build directory, default is build/<toolchain>-<link>-<arch>')
    parser.add_argument('--build-type', default='Release', help='CMAKE_BUILD_TYPE')
    parser.add_argument('--protoc', help='the host protoc path, built from src/protobuf when omitted')
    parser.add_argument('--host-build', default='build/host-protoc', help='build directory of the host protoc')
    parser.add_argument('--protoc-only', action='store_true', help='only build the host protoc and exit')
    parser.add_argument('--protoc-output', help='with --protoc-only, copy the host protoc to this path')
    parser.add_argument('--job', '--jobs', dest='jobs', default=jobs, help='run N jobs in parallel')
    parser.add_argument('--target', nargs='+', default=['all'],
                        help='build specified targets such as aapt2 adb fastboot, etc')
    parser.add_argument('--output-dir', help='where to put the zip package, default is the build directory')
    parser.add_argument('--no-strip', action='store_true', help='keep the symbols of the executables')
    parser.add_argument('--clean', action='store_true', help='remove the build directory first')
    parser.add_argument('cmake_args', nargs='*', help='extra cmake arguments after --, e.g. -- -DFOO=ON')

    args = parser.parse_args()
    args.arch = normalize_arch(args.arch)

    if args.protoc_only:
        protoc = build_host_protoc(args)
        if args.protoc_output:
            output = Path(args.protoc_output).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(protoc.resolve(), output)
            protoc = output
        info('host protoc: {}'.format(protoc))
        return

    build(args)


if __name__ == '__main__':
    main()
