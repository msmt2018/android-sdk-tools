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

# Build only AIDL implementation files present in the pinned release checkout.
file(GLOB AIDL_CPP_SOURCES CONFIGURE_DEPENDS "${SRC}/aidl/*.cpp")
# Unit tests are not part of the distributable AIDL compiler executable.
list(FILTER AIDL_CPP_SOURCES EXCLUDE REGEX "/aidl_unittest\\.cpp$")
# The upstream AIDL directory also contains unit-test translation units.
# They are not part of the aidl CLI target and must not be compiled into it.
list(FILTER AIDL_CPP_SOURCES EXCLUDE REGEX "_unittest\\.cpp$")
add_executable(aidl
    ${AIDL_CPP_SOURCES}
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