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

set(LIBBASE_HEX_SOURCE)
if(EXISTS "${SRC}/libbase/hex.cpp")
    list(APPEND LIBBASE_HEX_SOURCE "${SRC}/libbase/hex.cpp")
endif()

set(LIBBASE_POSIX_STRERROR_SOURCE)
if(EXISTS "${SRC}/libbase/posix_strerror_r.cpp")
    list(APPEND LIBBASE_POSIX_STRERROR_SOURCE "${SRC}/libbase/posix_strerror_r.cpp")
endif()

set(LIBBASE_ABI_COMPATIBILITY_SOURCE)
if(EXISTS "${SRC}/libbase/abi_compatibility.cpp")
    list(APPEND LIBBASE_ABI_COMPATIBILITY_SOURCE "${SRC}/libbase/abi_compatibility.cpp")
endif()

add_library(libbase STATIC
    ${LIBBASE_ABI_COMPATIBILITY_SOURCE}
    ${SRC}/libbase/chrono_utils.cpp
    ${SRC}/libbase/cmsg.cpp
    ${SRC}/libbase/file.cpp
    ${LIBBASE_HEX_SOURCE}
    ${SRC}/libbase/logging.cpp
    ${SRC}/libbase/mapped_file.cpp
    ${SRC}/libbase/parsebool.cpp
    ${SRC}/libbase/parsenetaddress.cpp
    ${LIBBASE_POSIX_STRERROR_SOURCE}
    ${SRC}/libbase/process.cpp
    ${SRC}/libbase/properties.cpp
    ${SRC}/libbase/stringprintf.cpp
    ${SRC}/libbase/strings.cpp
    ${SRC}/libbase/threads.cpp
    ${SRC}/libbase/test_utils.cpp
    ${SRC}/libbase/errors_unix.cpp
    )

target_include_directories(libbase PRIVATE
    ${SRC}/libbase/include
    ${SRC}/core/include
    ${SRC}/fmtlib/include 
    ${SRC}/logging/liblog/include
    )
# fdsan functions are weak imports; expose their API-29 declarations while
# preserving the Android 24 target triple and runtime fallback on older devices.
if(ANDROID)
    target_compile_options(libbase PUBLIC -U__ANDROID_API__ -D__ANDROID_API__=29)
endif()
# fdsan functions are weak imports; expose their API-29 declarations while
# preserving the Android 24 target triple and runtime fallback on older devices.
if(ANDROID)
    target_compile_options(libbase PUBLIC -U__ANDROID_API__ -D__ANDROID_API__=29)
endif()

# fdsan functions are weak imports; expose their API-29 declarations while
# preserving the Android 24 target triple and runtime fallback on older devices.
if(ANDROID)
    target_compile_options(libbase PUBLIC -U__ANDROID_API__ -D__ANDROID_API__=29)
endif()
