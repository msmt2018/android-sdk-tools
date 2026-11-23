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

set(LIBBASE_LIBLOG_SYMBOLS_SOURCE)
if(EXISTS "${SRC}/libbase/liblog_symbols.cpp")
    # Include the optional logger shim only when the pinned header declares
    # every private liblog API referenced by this source.
    set(_libbase_liblog_symbols_compatible ON)
    set(_libbase_liblog_header "")
    foreach(_candidate
        "${SRC}/core/include/android/log.h"
        "${SRC}/logging/liblog/include/android/log.h"
        "${SRC}/core/liblog/include/android/log.h")
        if(EXISTS "${_candidate}")
            set(_libbase_liblog_header "${_candidate}")
            break()
        endif()
    endforeach()
    if(_libbase_liblog_header)
        file(READ "${_libbase_liblog_header}" _libbase_liblog_header_text)
        file(READ "${SRC}/libbase/liblog_symbols.cpp" _libbase_liblog_source_text)
        string(REGEX MATCHALL "__android_log_[A-Za-z0-9_]+" _libbase_liblog_symbols "${_libbase_liblog_source_text}")
        foreach(_symbol IN LISTS _libbase_liblog_symbols)
            string(FIND "${_libbase_liblog_header_text}" "${_symbol}" _symbol_position)
            if(_symbol_position EQUAL -1)
                set(_libbase_liblog_symbols_compatible OFF)
                break()
            endif()
        endforeach()
    else()
        set(_libbase_liblog_symbols_compatible OFF)
    endif()
    if(_libbase_liblog_symbols_compatible)
        list(APPEND LIBBASE_LIBLOG_SYMBOLS_SOURCE "${SRC}/libbase/liblog_symbols.cpp")
    else()
        message(STATUS "libbase: skipping optional liblog_symbols.cpp; pinned liblog headers do not declare its complete API")
    endif()
endif()

set(LIBBASE_ABI_COMPATIBILITY_SOURCE)
if(EXISTS "${SRC}/libbase/abi_compatibility.cpp")
    list(APPEND LIBBASE_ABI_COMPATIBILITY_SOURCE "${SRC}/libbase/abi_compatibility.cpp")
endif()

add_library(libbase STATIC
    ${LIBBASE_ABI_COMPATIBILITY_SOURCE}
    ${LIBBASE_LIBLOG_SYMBOLS_SOURCE}
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

# fdsan symbols are weak and fall back to close(2) on API < 29.
# Expose their API-29 declarations while retaining the android-24 target triple.
if(ANDROID)
    target_compile_options(libbase PUBLIC -U__ANDROID_API__ -D__ANDROID_API__=29)
endif()
