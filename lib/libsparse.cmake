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

# Android P uses C++ implementations for the sparse writer, while Android 9
# snapshots reverted those files to C. Select the source files actually pinned
# by the release manifest instead of silently omitting the C implementations.
set(LIBSPARSE_SOURCES)
foreach(_name backed_block output_file sparse sparse_crc32 sparse_err)
    if(EXISTS "${SRC}/core/libsparse/${_name}.cpp")
        list(APPEND LIBSPARSE_SOURCES "${SRC}/core/libsparse/${_name}.cpp")
    elseif(EXISTS "${SRC}/core/libsparse/${_name}.c")
        list(APPEND LIBSPARSE_SOURCES "${SRC}/core/libsparse/${_name}.c")
    else()
        message(FATAL_ERROR "Pinned libsparse source is missing: ${_name}.c/.cpp")
    endif()
endforeach()

if(EXISTS "${SRC}/core/libsparse/sparse_read.cpp")
    list(APPEND LIBSPARSE_SOURCES "${SRC}/core/libsparse/sparse_read.cpp")
elseif(EXISTS "${SRC}/core/libsparse/sparse_read.c")
    list(APPEND LIBSPARSE_SOURCES "${SRC}/core/libsparse/sparse_read.c")
else()
    message(FATAL_ERROR "Pinned libsparse snapshot has no sparse_read implementation")
endif()

add_library(libsparse STATIC ${LIBSPARSE_SOURCES})

target_include_directories(libsparse PRIVATE
    ${SRC}/core/libsparse/include 
    ${SRC}/libbase/include
    )
