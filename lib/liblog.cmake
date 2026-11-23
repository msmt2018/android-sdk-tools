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

# Build the Android.bp host/fake-device liblog source set used by standalone
# tools. Do not mix in the target logd/pmsg transports: those define the same
# transport globals as fake_writer and produce duplicate symbols.
set(LIBLOG_SOURCES)
foreach(_name
    config_read config_write local_logger log_event_list log_event_write
    log_ratelimit logger_lock logger_name logger_read logger_write properties log_time
    logprint stderr_write fake_log_device fake_writer event_tag_map
)
    if(EXISTS "${SRC}/logging/liblog/${_name}.cpp")
        list(APPEND LIBLOG_SOURCES "${SRC}/logging/liblog/${_name}.cpp")
    elseif(EXISTS "${SRC}/logging/liblog/${_name}.c")
        list(APPEND LIBLOG_SOURCES "${SRC}/logging/liblog/${_name}.c")
    endif()
endforeach()

if(NOT LIBLOG_SOURCES)
    message(FATAL_ERROR "No host/fake-device liblog sources found in pinned AOSP tree")
endif()

add_library(liblog STATIC ${LIBLOG_SOURCES})

target_compile_definitions(liblog PRIVATE
    LIBLOG_LOG_TAG=1006
    _XOPEN_SOURCE=700
    FAKE_LOG_DEVICE=1
    SNET_EVENT_LOG_TAG=1397638484
    ANDROID_DEBUGGABLE=0
)

# The Android P C liblog sources use tentative globals from logger.h.
# Match the historical Android build's common-symbol semantics under NDK clang.
target_compile_options(liblog PRIVATE
    $<$<COMPILE_LANGUAGE:C>:-fcommon>
)

target_include_directories(liblog PRIVATE
    ${SRC}/core/include
    ${SRC}/logging/liblog/include
    ${SRC}/core/libcutils/include
    ${SRC}/libbase/include
)

# API-24 is the toolchain baseline, but logger_write in the pinned source uses
# liblog's in-tree length-aware private interface. Keep the declaration visible.
if(EXISTS "${SRC}/logging/liblog/include/log/log_main.h")
    target_compile_definitions(liblog PRIVATE __ANDROID_USE_LIBLOG_LOGGABLE_INTERFACE=2)
endif()
if(EXISTS "${SRC}/logging/liblog/logger_write.c" AND
   EXISTS "${SRC}/logging/liblog/include/log/log_main.h")
    set_source_files_properties(
        "${SRC}/logging/liblog/logger_write.c"
        PROPERTIES COMPILE_FLAGS "-include ${SRC}/logging/liblog/include/log/log_main.h"
    )
endif()

set_target_properties(liblog PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    CXX_EXTENSIONS OFF
)
