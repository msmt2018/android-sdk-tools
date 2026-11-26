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
# Bundled static zlib. The NDK ships a zlib in its sysroot but other
# toolchains (zig, musl, cross gcc ...) don't, so always build it from source.

set(SDK_ZLIB_SOURCE_DIR ${SRC}/zlib)

if(NOT EXISTS ${SDK_ZLIB_SOURCE_DIR}/zlib.h)
    message(FATAL_ERROR "zlib source not found: ${SDK_ZLIB_SOURCE_DIR}, please run get_source.py")
endif()

add_library(sdk_zlib STATIC
    ${SDK_ZLIB_SOURCE_DIR}/adler32.c
    ${SDK_ZLIB_SOURCE_DIR}/compress.c
    ${SDK_ZLIB_SOURCE_DIR}/crc32.c
    ${SDK_ZLIB_SOURCE_DIR}/deflate.c
    ${SDK_ZLIB_SOURCE_DIR}/gzclose.c
    ${SDK_ZLIB_SOURCE_DIR}/gzlib.c
    ${SDK_ZLIB_SOURCE_DIR}/gzread.c
    ${SDK_ZLIB_SOURCE_DIR}/gzwrite.c
    ${SDK_ZLIB_SOURCE_DIR}/infback.c
    ${SDK_ZLIB_SOURCE_DIR}/inffast.c
    ${SDK_ZLIB_SOURCE_DIR}/inflate.c
    ${SDK_ZLIB_SOURCE_DIR}/inftrees.c
    ${SDK_ZLIB_SOURCE_DIR}/trees.c
    ${SDK_ZLIB_SOURCE_DIR}/uncompr.c
    ${SDK_ZLIB_SOURCE_DIR}/zutil.c
    )
set_target_properties(sdk_zlib PROPERTIES OUTPUT_NAME z)
target_compile_options(sdk_zlib PRIVATE -w)

# export only the public headers, so that the zlib internal headers
# (deflate.h, inflate.h, trees.h ...) never shadow headers of other projects
set(SDK_ZLIB_INCLUDE_DIR ${CMAKE_BINARY_DIR}/sdk-zlib/include)
configure_file(${SDK_ZLIB_SOURCE_DIR}/zlib.h ${SDK_ZLIB_INCLUDE_DIR}/zlib.h COPYONLY)
configure_file(${SDK_ZLIB_SOURCE_DIR}/zconf.h ${SDK_ZLIB_INCLUDE_DIR}/zconf.h COPYONLY)
target_include_directories(sdk_zlib PUBLIC ${SDK_ZLIB_INCLUDE_DIR})
# zlib's optimized deflate path includes contrib/optimizations/insert_string.h,
# which includes cpu_features.h from the zlib source root. Keep that root on
# this target's private include path and compile its feature implementation.
if(EXISTS "${SDK_ZLIB_SOURCE_DIR}/cpu_features.h")
    target_include_directories(sdk_zlib PRIVATE "${SDK_ZLIB_SOURCE_DIR}")
    if(EXISTS "${SDK_ZLIB_SOURCE_DIR}/cpu_features.c")
        target_sources(sdk_zlib PRIVATE "${SDK_ZLIB_SOURCE_DIR}/cpu_features.c")
    endif()

    if(ANDROID)
        target_compile_definitions(sdk_zlib PRIVATE ARMV8_OS_ANDROID)
        set(_sdk_ndk_cpufeatures "${CMAKE_ANDROID_NDK}/sources/android/cpufeatures")
        if(EXISTS "${_sdk_ndk_cpufeatures}/cpu-features.c"
           AND EXISTS "${_sdk_ndk_cpufeatures}/cpu-features.h")
            target_sources(sdk_zlib PRIVATE "${_sdk_ndk_cpufeatures}/cpu-features.c")
            target_include_directories(sdk_zlib PRIVATE "${_sdk_ndk_cpufeatures}")
        else()
            # Keep the portable zlib implementation buildable with NDKs that
            # no longer ship the deprecated cpufeatures compatibility library.
            target_compile_definitions(sdk_zlib PRIVATE CPU_NO_SIMD)
        endif()
    endif()
endif()


file(STRINGS ${SDK_ZLIB_SOURCE_DIR}/zlib.h _zlib_version_line REGEX "^#define ZLIB_VERSION \"[^\"]*\"")
string(REGEX REPLACE "^.*ZLIB_VERSION \"([^\"]*)\".*$" "\\1" SDK_ZLIB_VERSION "${_zlib_version_line}")

# many AOSP sources include <zlib.h> without linking zlib directly,
# make the bundled headers visible to every target (before the sysroot)
include_directories(${SDK_ZLIB_INCLUDE_DIR})
# keep z_off_t consistent between the library and all of its users
add_compile_definitions(Z_HAVE_UNISTD_H Z_HAVE_STDARG_H)

# an IMPORTED target (not an ALIAS), the third-party projects that install(EXPORT)
# their targets (e.g. libpng) would otherwise require sdk_zlib in their export set
if(NOT TARGET ZLIB::ZLIB)
    add_library(ZLIB::ZLIB INTERFACE IMPORTED GLOBAL)
    set_target_properties(ZLIB::ZLIB PROPERTIES INTERFACE_LINK_LIBRARIES sdk_zlib)
endif()
