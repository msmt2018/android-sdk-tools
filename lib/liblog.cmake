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

# Match the Android.bp device source set for the pinned AOSP release.
# Host-only fake_writer/fake_log_device sources are intentionally excluded:
# the SDK tools are built for Android and need the real logd/pmsg transports.
set(LIBLOG_SOURCES)
foreach(_name
    log_event_list log_event_write logger_lock logger_name logger_read
    logger_write logprint properties log_time event_tag_map
    pmsg_reader pmsg_writer logd_reader logd_writer
)
    if(EXISTS "${SRC}/logging/liblog/${_name}.cpp")
        list(APPEND LIBLOG_SOURCES "${SRC}/logging/liblog/${_name}.cpp")
    elseif(EXISTS "${SRC}/logging/liblog/${_name}.c")
        list(APPEND LIBLOG_SOURCES "${SRC}/logging/liblog/${_name}.c")
    endif()
endforeach()

if(NOT LIBLOG_SOURCES)
    message(FATAL_ERROR "No Android-target liblog sources found in pinned AOSP tree")
endif()

add_library(liblog STATIC ${LIBLOG_SOURCES})

target_compile_definitions(liblog PRIVATE
    LIBLOG_LOG_TAG=1006
    _XOPEN_SOURCE=700
    SNET_EVENT_LOG_TAG=1397638484
    ANDROID_DEBUGGABLE=0
)

# Android P C liblog sources contain tentative globals from logger.h.
target_compile_options(liblog PRIVATE
    $<$<COMPILE_LANGUAGE:C>:-fcommon>
)

target_include_directories(liblog PRIVATE
    # Prefer this release's own liblog public/private headers over older
    # compatibility headers exposed by system/core/include.
    ${SRC}/logging/liblog/include
    ${SRC}/core/include
    ${SRC}/core/libcutils/include
    ${SRC}/libbase/include
)

# Some historical logger_write implementations use the private loggable API.
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

# Android P keeps pmsg_writer.c as C while the private debuggable
# helper is defined by properties.c but is not declared by its old headers.
if(EXISTS "${SRC}/logging/liblog/pmsg_writer.c")
    set_source_files_properties(
        "${SRC}/logging/liblog/pmsg_writer.c"
        PROPERTIES COMPILE_FLAGS "-include ${CMAKE_SOURCE_DIR}/cmake/liblog_compat.h"
    )
endif()

set_target_properties(liblog PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    CXX_EXTENSIONS OFF
)
