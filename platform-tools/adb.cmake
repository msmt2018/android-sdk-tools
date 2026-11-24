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

# Append only source files that exist in the manifest-pinned AOSP revision.
# Platform-tools 28/29 predate several modern ADB subsystems (pairing, TLS,
# fastdeploy and Incremental FS); do not compile later-release paths against
# those historical source trees.
function(append_existing_sources output)
    set(_existing)
    foreach(_source IN LISTS ARGN)
        if(EXISTS "${_source}")
            list(APPEND _existing "${_source}")
        endif()
    endforeach()
    set(${output} "${_existing}" PARENT_SCOPE)
endfunction()

# ========================= adb proto ============================
set(ADB_PROTO_SRC)  # adb proto source files
set(ADB_PROTO_HDRS) # adb proto head files
set(ADB_PROTO_DIR ${SRC}/adb/proto)

file(GLOB_RECURSE PROTO_FILES ${ADB_PROTO_DIR}/*.proto)

foreach(proto ${PROTO_FILES})
    get_filename_component(FIL_WE ${proto} NAME_WE)
    if(DEFINED PROTOC_PATH)
        # execute the protoc command to generate the proto targets for host arch
        execute_process(
            COMMAND ${PROTOC_COMPILER} ${proto}
            --proto_path=${ADB_PROTO_DIR}
            --cpp_out=${ADB_PROTO_DIR}
            COMMAND_ECHO STDOUT
            RESULT_VARIABLE RESULT
            WORKING_DIRECTORY ${ADB_PROTO_DIR}
        )
        
        # check command result
        if(RESULT EQUAL 0)
            message(STATUS "generate cpp file ${TARGET_CPP_FILE}")
            message(STATUS "generate head file ${TARGET_HEAD_FILE}")
        endif()
    endif()
    
    set(TARGET_CPP_FILE "${ADB_PROTO_DIR}/${FIL_WE}.pb.cc")
    set(TARGET_HEAD_FILE "${ADB_PROTO_DIR}/${FIL_WE}.pb.h")
   
    if(EXISTS ${TARGET_CPP_FILE} AND EXISTS ${TARGET_HEAD_FILE})
        list(APPEND ADB_PROTO_SRC ${TARGET_CPP_FILE})
        list(APPEND ADB_PROTO_HDRS ${TARGET_HEAD_FILE})
    endif()
endforeach()

if(DEFINED PROTOC_PATH)
    set_source_files_properties(${ADB_PROTO_SRC} PROPERTIES GENERATED TRUE)
    set_source_files_properties(${ADB_PROTO_HDRS} PROPERTIES GENERATED TRUE)
endif()
# ========================= adb proto ============================


# ========================= optional fastdeploy proto ============================
set(FASTDEPLOY_PROTO_SRC)
set(FASTDEPLOY_PROTO_HDRS)
set(FASTDEPLOY_PROTO_DIR ${CMAKE_SOURCE_DIR}/src/adb/fastdeploy/proto)
if(EXISTS "${FASTDEPLOY_PROTO_DIR}/ApkEntry.proto")
    if(DEFINED PROTOC_PATH)
        execute_process(
            COMMAND ${PROTOC_COMPILER} ${FASTDEPLOY_PROTO_DIR}/ApkEntry.proto
            --proto_path=${FASTDEPLOY_PROTO_DIR}
            --cpp_out=${FASTDEPLOY_PROTO_DIR}
            RESULT_VARIABLE RESULT
            WORKING_DIRECTORY ${FASTDEPLOY_PROTO_DIR}
        )
        if(NOT RESULT EQUAL 0)
            message(FATAL_ERROR "Failed to generate fastdeploy protobuf sources")
        endif()
    endif()
    set(TARGET_CPP_FILE "${FASTDEPLOY_PROTO_DIR}/ApkEntry.pb.cc")
    set(TARGET_HEAD_FILE "${FASTDEPLOY_PROTO_DIR}/ApkEntry.pb.h")
    if(EXISTS "${TARGET_CPP_FILE}" AND EXISTS "${TARGET_HEAD_FILE}")
        list(APPEND FASTDEPLOY_PROTO_SRC "${TARGET_CPP_FILE}")
        list(APPEND FASTDEPLOY_PROTO_HDRS "${TARGET_HEAD_FILE}")
    endif()
    if(DEFINED PROTOC_PATH)
        set_source_files_properties(${FASTDEPLOY_PROTO_SRC} ${FASTDEPLOY_PROTO_HDRS} PROPERTIES GENERATED TRUE)
    endif()
endif()
# ========================= optional fastdeploy proto ============================


set(ADB_MDNS_SOURCE)
if(EXISTS "${SRC}/adb/adb_mdns.cpp")
    list(APPEND ADB_MDNS_SOURCE "${SRC}/adb/adb_mdns.cpp")
endif()

set(ADB_MDNS_SERVICE_INFO_SOURCE)
if(EXISTS "${SRC}/adb/client/openscreen/mdns_service_info.cpp")
    list(APPEND ADB_MDNS_SERVICE_INFO_SOURCE "${SRC}/adb/client/openscreen/mdns_service_info.cpp")
endif()

set(ADB_MDNS_SERVICE_WATCHER_SOURCE)
if(EXISTS "${SRC}/adb/client/openscreen/mdns_service_watcher.cpp")
    list(APPEND ADB_MDNS_SERVICE_WATCHER_SOURCE "${SRC}/adb/client/openscreen/mdns_service_watcher.cpp")
endif()

set(ADB_OPENSCREEN_PLATFORM_SOURCES)
foreach(openscreen_platform_source logging.cpp task_runner.cpp udp_socket.cpp)
    if(EXISTS "${SRC}/adb/client/openscreen/platform/${openscreen_platform_source}")
        list(APPEND ADB_OPENSCREEN_PLATFORM_SOURCES "${SRC}/adb/client/openscreen/platform/${openscreen_platform_source}")
    endif()
endforeach()

# AOSP's USB dispatcher owns the public usb_init()/usb_cleanup() entry points.
# The backend files alone do not provide these symbols; compile the dispatcher
# when it exists in this platform-tools source revision.
set(ADB_USB_DISPATCH_SOURCE)
if(EXISTS "${SRC}/adb/client/usb_dispatch.cpp")
    list(APPEND ADB_USB_DISPATCH_SOURCE "${SRC}/adb/client/usb_dispatch.cpp")
endif()

set(ADB_MDNS_CLIENT_SOURCE)
if(EXISTS "${SRC}/adb/client/mdnsresponder_client.cpp")
    list(APPEND ADB_MDNS_CLIENT_SOURCE "${SRC}/adb/client/mdnsresponder_client.cpp")
endif()

append_existing_sources(ADB_CORE_SOURCES
    ${SRC}/adb/adb.cpp
    ${SRC}/adb/adb_io.cpp
    ${SRC}/adb/adb_listeners.cpp
    ${SRC}/adb/adb_trace.cpp
    ${SRC}/adb/adb_unique_fd.cpp
    ${SRC}/adb/adb_utils.cpp
    ${SRC}/adb/fdevent/fdevent.cpp
    ${SRC}/adb/services.cpp
    ${SRC}/adb/sockets.cpp
    ${SRC}/adb/socket_spec.cpp
    ${SRC}/adb/sysdeps/env.cpp
    ${SRC}/adb/sysdeps/errno.cpp
    ${SRC}/adb/transport.cpp
    ${SRC}/adb/transport_fd.cpp
    ${SRC}/adb/types.cpp
    ${SRC}/adb/client/auth.cpp
    ${SRC}/adb/client/adb_wifi.cpp
    ${SRC}/adb/client/usb_libusb.cpp
    ${SRC}/adb/client/transport_local.cpp
    ${SRC}/adb/client/mdns_utils.cpp
    ${SRC}/adb/client/transport_mdns.cpp
    ${SRC}/adb/client/transport_usb.cpp
    ${SRC}/adb/client/pairing/pairing_client.cpp
    ${SRC}/adb/client/usb_linux.cpp
    ${SRC}/adb/fdevent/fdevent_epoll.cpp
    ${SRC}/adb/sysdeps_unix.cpp
    ${SRC}/adb/sysdeps/posix/network.cpp
)
add_library(libadb STATIC
    ${ADB_CORE_SOURCES}
    ${ADB_MDNS_SOURCE}
    ${ADB_MDNS_SERVICE_INFO_SOURCE}
    ${ADB_MDNS_SERVICE_WATCHER_SOURCE}
    ${ADB_OPENSCREEN_PLATFORM_SOURCES}
    ${ADB_USB_DISPATCH_SOURCE}
    ${ADB_MDNS_CLIENT_SOURCE}
    ${ADB_PROTO_SRC} ${ADB_PROTO_HDRS}
)
target_compile_definitions(libadb PRIVATE 
    -D_GNU_SOURCE
    -DADB_HOST=1
    )
target_include_directories(libadb PRIVATE
    ${SRC}/adb
    ${SRC}/adb/proto
    ${SRC}/adb/crypto/include
    ${SRC}/adb/pairing_auth/include
    ${SRC}/adb/pairing_connection/include
    ${SRC}/adb/tls/include
    ${SRC}/base/libs/androidfw/include
    ${SRC}/fmtlib/include
    ${SRC}/libbase/include
    ${SRC}/libziparchive/include
    ${SRC}/native/include
    ${SRC}/protobuf/src
    ${SRC}/zstd/lib
    ${SRC}/libusb/include
    ${SRC}/brotli/c/include
    ${SRC}/soong/cc/libbuildversion/include
    ${SRC}/mdnsresponder/mDNSShared
    ${SRC}/openscreen
    ${SRC}/abseil-cpp
    ${SRC}/core/libcrypto_utils/include
    ${SRC}/core/libcutils/include
    ${SRC}/core/include
    ${SRC}/core/diagnose_usb/include
    ${SRC}/boringssl/include
    ${SRC}/googletest/googletest/include
    ${SRC}/incremental_delivery/incfs/util/include 
    )

append_existing_sources(ADB_CRYPTO_SOURCES
    ${SRC}/adb/crypto/key.cpp
    ${SRC}/adb/crypto/rsa_2048_key.cpp
    ${SRC}/adb/crypto/x509_generator.cpp
)
if(ADB_CRYPTO_SOURCES)
    add_library(libadb_crypto STATIC ${ADB_CRYPTO_SOURCES} ${ADB_PROTO_HDRS})
    target_include_directories(libadb_crypto PRIVATE
        ${SRC}/adb
        ${SRC}/adb/crypto/include
        ${SRC}/adb/proto
        ${SRC}/boringssl/include
        ${SRC}/core/libcrypto_utils/include
        ${SRC}/libbase/include
        ${SRC}/protobuf/src
    )
else()
    # Some older ADB snapshots provide no separate crypto translation units.
    add_library(libadb_crypto INTERFACE)
endif()

if(EXISTS "${SRC}/adb/tls/tls_connection.cpp")
    add_library(libadb_tls_connection STATIC
        ${SRC}/adb/tls/adb_ca_list.cpp
        ${SRC}/adb/tls/tls_connection.cpp)
    target_include_directories(libadb_tls_connection PRIVATE
        ${SRC}/adb ${SRC}/adb/tls/include
        ${SRC}/boringssl/include ${SRC}/libbase/include)
endif()

if(EXISTS "${SRC}/adb/pairing_connection/pairing_connection.cpp")
    add_library(libadb_pairing_connection STATIC
        ${SRC}/adb/pairing_connection/pairing_connection.cpp)
    target_include_directories(libadb_pairing_connection PRIVATE
        ${SRC}/adb/proto ${SRC}/adb/pairing_connection/include
        ${SRC}/adb/pairing_auth/include ${SRC}/adb/tls/include
        ${SRC}/libbase/include ${SRC}/boringssl/include
        ${SRC}/protobuf/src)
endif()

if(EXISTS "${SRC}/adb/pairing_auth/pairing_auth.cpp")
    add_library(libadb_pairing_auth STATIC
        ${SRC}/adb/pairing_auth/aes_128_gcm.cpp
        ${SRC}/adb/pairing_auth/pairing_auth.cpp)
    target_include_directories(libadb_pairing_auth PRIVATE
        ${SRC}/adb/pairing_auth/include ${SRC}/libbase/include
        ${SRC}/boringssl/include ${SRC}/protobuf/src)
endif()

if(EXISTS "${SRC}/adb/sysdeps/env.cpp")
    add_library(libadb_sysdeps STATIC "${SRC}/adb/sysdeps/env.cpp")
    target_include_directories(libadb_sysdeps PRIVATE
        ${SRC}/libbase/include
        ${SRC}/adb
    )
else()
    add_library(libadb_sysdeps INTERFACE)
endif()

if(EXISTS "${SRC}/adb/fastdeploy/deploypatchgenerator/apk_archive.cpp")
    add_library(libfastdeploy STATIC
        ${SRC}/adb/fastdeploy/deploypatchgenerator/apk_archive.cpp
        ${SRC}/adb/fastdeploy/deploypatchgenerator/deploy_patch_generator.cpp
        ${SRC}/adb/fastdeploy/deploypatchgenerator/patch_utils.cpp
        ${FASTDEPLOY_PROTO_SRC} ${FASTDEPLOY_PROTO_HDRS})
    target_include_directories(libfastdeploy PRIVATE
        ${SRC}/adb ${SRC}/core/libcutils/include
        ${SRC}/core/libutils/include
        ${SRC}/libbase/include ${SRC}/protobuf/src
        ${SRC}/boringssl/include)
endif()

# Android 11-era system/core snapshots use android_pubkey.c, while
# newer snapshots renamed the implementation to android_pubkey.cpp.
set(ADB_ANDROID_PUBKEY_SOURCE)
if(EXISTS "${SRC}/core/libcrypto_utils/android_pubkey.cpp")
    set(ADB_ANDROID_PUBKEY_SOURCE "${SRC}/core/libcrypto_utils/android_pubkey.cpp")
elseif(EXISTS "${SRC}/core/libcrypto_utils/android_pubkey.c")
    set(ADB_ANDROID_PUBKEY_SOURCE "${SRC}/core/libcrypto_utils/android_pubkey.c")
endif()
if(ADB_ANDROID_PUBKEY_SOURCE)
    add_library(libcrypto STATIC ${ADB_ANDROID_PUBKEY_SOURCE})
    target_include_directories(libcrypto PRIVATE
        ${SRC}/core/libcrypto_utils/include
        ${SRC}/boringssl/include
    )
else()
    add_library(libcrypto INTERFACE)
endif()

append_existing_sources(ADB_EXECUTABLE_SOURCES
    ${SRC}/adb/client/adb_client.cpp
    ${SRC}/adb/client/bugreport.cpp
    ${SRC}/adb/client/commandline.cpp
    ${SRC}/adb/client/file_sync_client.cpp
    ${SRC}/adb/client/main.cpp
    ${SRC}/adb/client/console.cpp
    ${SRC}/adb/client/adb_install.cpp
    ${SRC}/adb/client/line_printer.cpp
    ${SRC}/adb/client/fastdeploy.cpp
    ${SRC}/adb/client/fastdeploycallbacks.cpp
    ${SRC}/adb/client/incremental.cpp
    ${SRC}/adb/client/incremental_server.cpp
    ${SRC}/adb/client/incremental_utils.cpp
    ${SRC}/adb/shell_service_protocol.cpp
)
add_executable(adb ${ADB_EXECUTABLE_SOURCES} ${ADB_PROTO_HDRS})
target_include_directories(adb PRIVATE
    ${SRC}/adb
    ${SRC}/adb/proto
    ${SRC}/adb/fastdeploy/deployagent
    ${SRC}/lz4/lib
    ${SRC}/zstd/lib
    ${SRC}/libbase/include 
    ${SRC}/core/include 
    ${SRC}/core/libcutils/include
    ${SRC}/core/libcrypto_utils/include 
    ${SRC}/boringssl/include
    ${SRC}/googletest/googletest/include
    )
target_compile_definitions(adb PRIVATE 
    -D_GNU_SOURCE
    -DADB_HOST=1
    )
set(ADB_LINK_LIBRARIES
    libadb libadb_crypto libcrypto libadb_sysdeps
    libselinux libsepol libbase libutils libcutils
    libdiagnoseusb libandroidfw libbuildversion libziparchive
    libusb liblog pcre2-8 crypto ssl
    protobuf::libprotoc protobuf::libprotobuf
    brotlicommon-static brotlidec-static brotlienc-static
    lz4_static sdk_system_libs
)
foreach(_optional_target
    libadb_tls_connection libadb_pairing_connection libadb_pairing_auth
    libfastdeploy libincfs libpackagelistparser libmdnssd libopenscreen
    libzstd_static)
    if(TARGET ${_optional_target})
        list(APPEND ADB_LINK_LIBRARIES ${_optional_target})
    endif()
endforeach()
foreach(_optional_target absl::base absl::strings)
    if(TARGET ${_optional_target})
        list(APPEND ADB_LINK_LIBRARIES ${_optional_target})
    endif()
endforeach()
target_link_libraries(adb ${ADB_LINK_LIBRARIES})
