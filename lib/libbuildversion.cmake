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

# Soong normally generates build/version.h and exports its include directory
# through generated_headers. Standalone CMake must provide the same public API.
set(LIBBUILDVERSION_INCLUDE_DIR "${SRC}/soong/cc/libbuildversion/include")
set(LIBBUILDVERSION_HEADER "${LIBBUILDVERSION_INCLUDE_DIR}/build/version.h")
if(NOT EXISTS "${LIBBUILDVERSION_HEADER}")
    file(MAKE_DIRECTORY "${LIBBUILDVERSION_INCLUDE_DIR}/build")
    file(WRITE "${LIBBUILDVERSION_HEADER}"
        "#pragma once\n"
        "#include <string>\n"
        "namespace android { namespace build { std::string GetBuildNumber(); } }\n")
endif()

if(EXISTS "${SRC}/soong/cc/libbuildversion/libbuildversion.cpp")
    add_library(libbuildversion STATIC
        ${SRC}/soong/cc/libbuildversion/libbuildversion.cpp
    )
else()
    # Some historical manifests omit the Soong implementation even though
    # imported tool sources still call GetBuildNumber(). Supply a compatible
    # runtime-property implementation instead of a link-time empty target.
    set(LIBBUILDVERSION_COMPAT_SOURCE "${CMAKE_CURRENT_BINARY_DIR}/libbuildversion_compat.cpp")
    file(WRITE "${LIBBUILDVERSION_COMPAT_SOURCE}"
        "#include <string>\n"
        "#if defined(__ANDROID__)\n"
        "#include <sys/system_properties.h>\n"
        "#endif\n"
        "namespace android { namespace build {\n"
        "std::string GetBuildNumber() {\n"
        "#if defined(__ANDROID__)\n"
        "char value[PROP_VALUE_MAX] = {};\n"
        "if (__system_property_get(\"ro.build.version.incremental\", value) > 0) return value;\n"
        "#endif\n"
        "return \"unknown\";\n"
        "} } }\n")
    add_library(libbuildversion STATIC "${LIBBUILDVERSION_COMPAT_SOURCE}")
endif()
target_include_directories(libbuildversion PUBLIC "${LIBBUILDVERSION_INCLUDE_DIR}")
