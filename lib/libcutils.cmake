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

set(LIBCUTILS_SRC)
foreach(_source
    canned_fs_config.cpp
    config_utils.cpp
    fs.cpp
    fs_config.cpp
    hashmap.cpp
    iosched_policy.cpp
    load_file.cpp
    multiuser.cpp
    native_handle.cpp
    properties.cpp
    record_stream.cpp
    socket_inaddr_any_server_unix.cpp
    socket_local_client_unix.cpp
    socket_local_server_unix.cpp
    socket_network_client_unix.cpp
    sockets_unix.cpp
    sockets.cpp
    str_parms.cpp
    strlcpy.c
    sched_policy.cpp
)
    if(EXISTS "${SRC}/core/libcutils/${_source}")
        list(APPEND LIBCUTILS_SRC "${SRC}/core/libcutils/${_source}")
    endif()
endforeach()

# see core/libcutils/Android.bp
if(SDK_TARGET_ANDROID)
    set(_libcutils_platform_sources
        android_get_control_file.cpp
        android_reboot.cpp
        ashmem-dev.cpp
        klog.cpp
        partition_utils.cpp
        qtaguid.cpp
        trace-dev.cpp
        uevent.cpp
    )
else()
    set(_libcutils_platform_sources
        ashmem-host.cpp
        trace-host.cpp
    )
endif()
foreach(_source IN LISTS _libcutils_platform_sources)
    if(EXISTS "${SRC}/core/libcutils/${_source}")
        list(APPEND LIBCUTILS_SRC "${SRC}/core/libcutils/${_source}")
    endif()
endforeach()

add_library(libcutils STATIC ${LIBCUTILS_SRC})

target_compile_definitions(libcutils PRIVATE 
    -D_GNU_SOURCE
    )
# Old libcutils/properties.h enables a FORTIFY overload that depends on
# __RENAME_CLANG, which is not exposed by all NDK r27 API-level headers.
if(EXISTS "${SRC}/core/libcutils/include/cutils/properties.h")
    file(READ "${SRC}/core/libcutils/include/cutils/properties.h" _cutils_properties_header)
    if(_cutils_properties_header MATCHES "__RENAME_CLANG")
        target_compile_options(libcutils PRIVATE -U__BIONIC_FORTIFY)
    endif()
endif()

target_include_directories(libcutils PRIVATE
    ${SRC}/core/libutils/include
    ${SRC}/core/libcutils/include
    ${SRC}/logging/liblog/include 
    ${SRC}/libbase/include
    )
    
