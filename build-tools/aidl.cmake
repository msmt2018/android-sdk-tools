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

find_package(BISON REQUIRED)
find_package(FLEX REQUIRED)

if(NOT BISON_FOUND OR NOT FLEX_FOUND)
    message(FATAL_ERROR "AIDL requires both Bison and Flex")
endif()

bison_target(
    LangParser ${SRC}/aidl/aidl_language_y.yy ${SRC}/aidl/aidl_language_y.cpp
    DEFINES_FILE ${SRC}/aidl/aidl_language_y.h
)
flex_target(
    LangScanner ${SRC}/aidl/aidl_language_l.ll ${SRC}/aidl/aidl_language_l.cpp
    DEFINES_FILE ${SRC}/aidl/aidl_language_l.h
)
add_flex_bison_dependency(LangScanner LangParser)

# Android P AIDL source set, matching the Google platform/system/tools/aidl
# release tree. This release predates aidl_to_rust, diagnostics, comments,
# aidl_checkapi and the newer Soong-only source split.
set(AIDL_LEGACY_COMMON_SOURCES
    ${SRC}/aidl/aidl.cpp
    ${SRC}/aidl/aidl_language.cpp
    ${SRC}/aidl/aidl_language_l.ll
    ${SRC}/aidl/aidl_language_y.yy
    ${SRC}/aidl/ast_cpp.cpp
    ${SRC}/aidl/ast_java.cpp
    ${SRC}/aidl/code_writer.cpp
    ${SRC}/aidl/generate_cpp.cpp
    ${SRC}/aidl/generate_java.cpp
    ${SRC}/aidl/generate_java_binder.cpp
    ${SRC}/aidl/import_resolver.cpp
    ${SRC}/aidl/io_delegate.cpp
    ${SRC}/aidl/line_reader.cpp
    ${SRC}/aidl/options.cpp
    ${SRC}/aidl/type_cpp.cpp
    ${SRC}/aidl/type_java.cpp
    ${SRC}/aidl/type_namespace.cpp
    ${BISON_LangParser_OUTPUTS}
    ${FLEX_LangScanner_OUTPUTS}
)

# Build only AIDL implementation files present in the pinned release checkout.
file(GLOB AIDL_CPP_SOURCES CONFIGURE_DEPENDS "${SRC}/aidl/*.cpp")
add_executable(aidl
    ${AIDL_CPP_SOURCES}
    ${BISON_LangParser_OUTPUTS}
    ${FLEX_LangScanner_OUTPUTS}
)
target_include_directories(aidl PRIVATE
    ${SRC}/aidl
    ${SRC}/googletest/googletest/include
    ${SRC}/libbase/include
    ${SRC}/core/libcutils/include
    ${SRC}/core/include
    ${SRC}/logging/liblog/include
)
target_link_libraries(aidl
    libbase
    libcutils
    liblog
    sdk_system_libs
)

# Preserve the legacy C++ backend executable provided by the same Google tag.
add_executable(aidl-cpp
    ${AIDL_LEGACY_COMMON_SOURCES}
    ${SRC}/aidl/main_cpp.cpp
)
target_include_directories(aidl-cpp PRIVATE
    ${SRC}/aidl
    ${SRC}/googletest/googletest/include
    ${SRC}/libbase/include
    ${SRC}/core/libcutils/include
    ${SRC}/core/include
    ${SRC}/logging/liblog/include
)
target_link_libraries(aidl-cpp
    libbase
    libcutils
    liblog
    sdk_system_libs
)
