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

if(NOT BISON_FOUND)
    message(FATAL_ERROR "can't find the bison")
endif()

if(NOT FLEX_FOUND)
    message(FATAL_ERROR "can't find the flex")
endif()

# generate aidl_language_y.h and aidl_language_y.cpp
bison_target(
    LangParser ${SRC}/aidl/aidl_language_y.yy ${SRC}/aidl/aidl_language_y.cpp
    DEFINES_FILE ${SRC}/aidl/aidl_language_y.h
    )

# generate aidl_language_l.h and aidl_language_l.cpp
flex_target(
    LangScanner ${SRC}/aidl/aidl_language_l.ll ${SRC}/aidl/aidl_language_l.cpp
    DEFINES_FILE ${SRC}/aidl/aidl_language_l.h
    )

# add dependency
add_flex_bison_dependency(LangScanner LangParser)

message(STATUS ${FLEX_LangScanner_OUTPUTS})          
message(STATUS ${BISON_LangParser_OUTPUTS})

# Some AOSP revisions retain io_delegate.cpp's LineReader calls but omit
# line_reader.cpp from the upstream Soong source list. Include its implementation
# when present to avoid an unresolved LineReader::ReadFromFile symbol.
set(AIDL_LINE_READER_SOURCE)
if(EXISTS "${SRC}/aidl/line_reader.cpp")
    list(APPEND AIDL_LINE_READER_SOURCE "${SRC}/aidl/line_reader.cpp")
endif()

set(AIDL_TO_COMMON_SRC)
if(EXISTS "${SRC}/aidl/aidl_to_common.cpp")
    list(APPEND AIDL_TO_COMMON_SRC ${SRC}/aidl/aidl_to_common.cpp)
endif()

set(AIDL_CPP_AST_SOURCE)
if(EXISTS "${SRC}/aidl/ast_cpp.cpp")
    list(APPEND AIDL_CPP_AST_SOURCE ${SRC}/aidl/ast_cpp.cpp)
endif()

set(AIDL_CPP_ANALYZER_SOURCE)
if(EXISTS "${SRC}/aidl/generate_cpp_analyzer.cpp")
    list(APPEND AIDL_CPP_ANALYZER_SOURCE ${SRC}/aidl/generate_cpp_analyzer.cpp)
endif()

set(AIDL_DUMPAPI_SOURCE)
if(EXISTS "${SRC}/aidl/aidl_dumpapi.cpp")
    list(APPEND AIDL_DUMPAPI_SOURCE "${SRC}/aidl/aidl_dumpapi.cpp")
endif()

set(AIDL_CHECK_VALID_SOURCE)
if(EXISTS "${SRC}/aidl/check_valid.cpp")
    list(APPEND AIDL_CHECK_VALID_SOURCE "${SRC}/aidl/check_valid.cpp")
endif()

set(AIDL_PREPROCESS_SOURCE)
if(EXISTS "${SRC}/aidl/preprocess.cpp")
    list(APPEND AIDL_PREPROCESS_SOURCE "${SRC}/aidl/preprocess.cpp")
endif()

set(AIDL_TO_RUST_SOURCE)
if(EXISTS "${SRC}/aidl/aidl_to_rust.cpp")
    list(APPEND AIDL_TO_RUST_SOURCE "${SRC}/aidl/aidl_to_rust.cpp")
endif()
set(AIDL_COMMENTS_SOURCE)
if(EXISTS "${SRC}/aidl/comments.cpp")
    list(APPEND AIDL_COMMENTS_SOURCE "${SRC}/aidl/comments.cpp")
endif()

add_executable(aidl
    ${SRC}/aidl/aidl_checkapi.cpp
    ${SRC}/aidl/aidl_const_expressions.cpp
    ${AIDL_DUMPAPI_SOURCE}
    ${SRC}/aidl/aidl_language_l.ll
    ${SRC}/aidl/aidl_language_y.yy
    ${SRC}/aidl/aidl_language.cpp
    ${AIDL_TO_COMMON_SRC}
    ${SRC}/aidl/aidl_to_cpp_common.cpp
    ${SRC}/aidl/aidl_to_cpp.cpp
    ${SRC}/aidl/aidl_to_java.cpp
    ${SRC}/aidl/aidl_to_ndk.cpp
    ${AIDL_TO_RUST_SOURCE}
    ${SRC}/aidl/aidl_typenames.cpp
    ${SRC}/aidl/aidl.cpp
    ${SRC}/aidl/ast_java.cpp
    ${AIDL_CPP_AST_SOURCE}
    ${AIDL_CHECK_VALID_SOURCE}
    ${SRC}/aidl/code_writer.cpp
    ${AIDL_COMMENTS_SOURCE}
    ${SRC}/aidl/diagnostics.cpp
    ${SRC}/aidl/generate_aidl_mappings.cpp
    ${SRC}/aidl/generate_cpp.cpp
    ${AIDL_CPP_ANALYZER_SOURCE}
    ${SRC}/aidl/generate_java_binder.cpp
    ${SRC}/aidl/generate_java.cpp
    ${SRC}/aidl/generate_ndk.cpp
    ${SRC}/aidl/generate_rust.cpp
    ${SRC}/aidl/import_resolver.cpp
    ${SRC}/aidl/io_delegate.cpp
    ${AIDL_LINE_READER_SOURCE}
    ${SRC}/aidl/location.cpp
    ${SRC}/aidl/logging.cpp
    ${SRC}/aidl/options.cpp
    ${SRC}/aidl/parser.cpp
    ${AIDL_PERMISSION_SOURCE}
    ${AIDL_PREPROCESS_SOURCE}
    ${SRC}/aidl/main.cpp
    ${BISON_LangParser_OUTPUTS}
    ${FLEX_LangScanner_OUTPUTS}
    )
    
target_include_directories(aidl PRIVATE
    ${SRC}/libbase/include
    ${SRC}/fmtlib/include
    ${SRC}/googletest/googletest/include
    )
    
target_link_libraries(aidl
    libbase
    liblog
    gmock
    fmt::fmt
    sdk_system_libs
    )