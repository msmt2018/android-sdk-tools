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

# ========================= aapt2 proto ============================
set(AAPT2_PROTO_SRC)  # proto source files
set(AAPT2_PROTO_HDRS) # proto head files
set(AAPT2_PROTO_DIR ${SRC}/base/tools/aapt2)

file(GLOB_RECURSE PROTO_FILES ${AAPT2_PROTO_DIR}/*.proto)

foreach(proto ${PROTO_FILES})
    get_filename_component(FIL_WE ${proto} NAME_WE)
    
    if(DEFINED PROTOC_PATH)
        # execute the protoc command to generate the proto targets for host arch
        execute_process(
            COMMAND ${PROTOC_COMPILER} ${proto}
            --proto_path=${AAPT2_PROTO_DIR}
            --cpp_out=${AAPT2_PROTO_DIR}
            COMMAND_ECHO STDOUT
            RESULT_VARIABLE RESULT
            WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}
        )
    
        # check command result
        if(RESULT EQUAL 0)
            message(STATUS "generate cpp file ${TARGET_CPP_FILE}")
            message(STATUS "generate head file ${TARGET_HEAD_FILE}")
        endif()
    endif()
    
    set(TARGET_CPP_FILE "${AAPT2_PROTO_DIR}/${FIL_WE}.pb.cc")
    set(TARGET_HEAD_FILE "${AAPT2_PROTO_DIR}/${FIL_WE}.pb.h")
    
    if(EXISTS ${TARGET_CPP_FILE} AND EXISTS ${TARGET_HEAD_FILE})
        list(APPEND AAPT2_PROTO_SRC ${TARGET_CPP_FILE})
        list(APPEND AAPT2_PROTO_HDRS ${TARGET_HEAD_FILE})
    endif()
endforeach()

if(DEFINED PROTOC_PATH)
    set_source_files_properties(${AAPT2_PROTO_SRC} PROPERTIES GENERATED TRUE)
    set_source_files_properties(${AAPT2_PROTO_HDRS} PROPERTIES GENERATED TRUE)
endif()
# ========================= aapt2 proto ============================


set(INCLUDES
    ${SRC}/base/tools/aapt2
    ${SRC}/protobuf/src
    ${SRC}/logging/liblog/include
    ${SRC}/expat/lib
    ${SRC}/fmtlib/include
    ${SRC}/native/include
    ${SRC}/libpng
    ${SRC}/libbase/include
    ${SRC}/base/libs/androidfw/include
    ${SRC}/base/libs/androidfw/include_pathutils
    ${SRC}/base/cmds/idmap2/libidmap2_policies/include
    ${SRC}/core/libsystem/include
    ${SRC}/core/libutils/include
    ${SRC}/googletest/googletest/include
    ${SRC}/libziparchive/include 
    ${SRC}/soong/cc/libbuildversion/include
    ${SRC}/incremental_delivery/incfs/util/include 
    ${SRC}/incremental_delivery/incfs/kernel-headers
    )

set(COMPILE_FLAGS
    -Wno-unused-parameter
    -Wno-missing-field-initializers
    -fno-exceptions 
    -fno-rtti
    )

set(TOOL_SOURCE
    ${AAPT2_APK_INFO_CMD_SRC}
    ${SRC}/base/tools/aapt2/cmd/Command.cpp
    ${SRC}/base/tools/aapt2/cmd/Compile.cpp
    ${SRC}/base/tools/aapt2/cmd/Convert.cpp
    ${SRC}/base/tools/aapt2/cmd/Diff.cpp
    ${SRC}/base/tools/aapt2/cmd/Dump.cpp
    ${SRC}/base/tools/aapt2/cmd/Link.cpp
    ${SRC}/base/tools/aapt2/cmd/Optimize.cpp
    ${SRC}/base/tools/aapt2/cmd/Util.cpp
    )
    
# build the host static library: aapt2
set(AAPT2_RES_ENTRY_WRITER_SRC)
if(EXISTS "${SRC}/base/tools/aapt2/format/binary/ResEntryWriter.cpp")
    list(APPEND AAPT2_RES_ENTRY_WRITER_SRC ${SRC}/base/tools/aapt2/format/binary/ResEntryWriter.cpp)
endif()
set(AAPT2_APK_INFO_CMD_SRC)
if(EXISTS "${SRC}/base/tools/aapt2/cmd/ApkInfo.cpp")
    list(APPEND AAPT2_APK_INFO_CMD_SRC ${SRC}/base/tools/aapt2/cmd/ApkInfo.cpp)
endif()

set(AAPT2_FEATURE_FLAGS_FILTER_SRC)
if(EXISTS "${SRC}/base/tools/aapt2/link/FeatureFlagsFilter.cpp")
    list(APPEND AAPT2_FEATURE_FLAGS_FILTER_SRC ${SRC}/base/tools/aapt2/link/FeatureFlagsFilter.cpp)
endif()

set(AAPT2_OBFUSCATOR_SRC)
if(EXISTS "${SRC}/base/tools/aapt2/optimize/Obfuscator.cpp")
    list(APPEND AAPT2_OBFUSCATOR_SRC ${SRC}/base/tools/aapt2/optimize/Obfuscator.cpp)
endif()

set(AAPT2_PRODUCT_FILTER_SRC)
if(EXISTS "${SRC}/base/tools/aapt2/process/ProductFilter.cpp")
    list(APPEND AAPT2_PRODUCT_FILTER_SRC ${SRC}/base/tools/aapt2/process/ProductFilter.cpp)
elseif(EXISTS "${SRC}/base/tools/aapt2/link/ProductFilter.cpp")
    list(APPEND AAPT2_PRODUCT_FILTER_SRC ${SRC}/base/tools/aapt2/link/ProductFilter.cpp)
endif()

set(AAPT2_VALUE_TRANSFORMER_SOURCE)
if(EXISTS "${SRC}/base/tools/aapt2/ValueTransformer.cpp")
    list(APPEND AAPT2_VALUE_TRANSFORMER_SOURCE "${SRC}/base/tools/aapt2/ValueTransformer.cpp")
endif()

# Build against the source files actually present in this release tag.
# AAPT2's source layout changed substantially between Android P and later
# releases, so a fixed list copied from a newer tag is not valid here.
file(GLOB_RECURSE AAPT2_ALL_CPP CONFIGURE_DEPENDS
    "${SRC}/base/tools/aapt2/*.cpp")
list(FILTER AAPT2_ALL_CPP EXCLUDE REGEX "/(test|tests|integration-tests)/|(_test|_tests)\\.cpp$")
# Unicode_data.cpp is generated data included by Unicode.cpp, not a translation unit.
list(REMOVE_ITEM AAPT2_ALL_CPP "${SRC}/base/tools/aapt2/text/Unicode_data.cpp")
set(AAPT2_MAIN_SOURCE "${SRC}/base/tools/aapt2/Main.cpp")
if(NOT EXISTS "${AAPT2_MAIN_SOURCE}")
    message(FATAL_ERROR "AAPT2 Main.cpp is missing from the selected Google source tag")
endif()
list(REMOVE_ITEM AAPT2_ALL_CPP "${AAPT2_MAIN_SOURCE}")
if(NOT AAPT2_ALL_CPP)
    message(FATAL_ERROR "No AAPT2 implementation sources found in the selected Google source tag")
endif()
set(AAPT2_LIBRARY_SOURCES ${AAPT2_ALL_CPP} ${AAPT2_PROTO_SRC})

add_library(libaapt2 STATIC ${AAPT2_LIBRARY_SOURCES})
target_include_directories(libaapt2 PRIVATE ${INCLUDES})
target_compile_options(libaapt2 PRIVATE ${COMPILE_FLAGS})

# build the host shared library: aapt2_jni
#add_library(libaapt2_jni SHARED
#   ${SRC}/base/tools/aapt2/jni/aapt2_jni.cpp
#   ${TOOL_SOURCE}
#   )
#target_include_directories(libaapt2_jni PRIVATE ${INCLUDES})
#target_compile_options(libaapt2_jni PRIVATE ${COMPILE_FLAGS})
#target_link_libraries(libaapt2_jni libaapt2)

# build the executable file aapt2
add_executable(aapt2 ${AAPT2_MAIN_SOURCE})
target_include_directories(aapt2 PRIVATE ${INCLUDES})
target_compile_options(aapt2 PRIVATE ${COMPILE_FLAGS})
target_link_libraries(aapt2
    libaapt2
    libandroidfw
    libincfs
    libselinux
    libsepol
    libpackagelistparser
    libutils
    libcutils
    libziparchive
    libbase
    libbuildversion
    liblog
    protobuf::libprotoc
    protobuf::libprotobuf
    expat
    crypto
    ssl
    pcre2-8
    png_static
    sdk_system_libs
    )
