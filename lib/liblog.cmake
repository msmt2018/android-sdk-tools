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

# liblog changed its source extensions and host/device source partition
# between Android 9 and Android 10. Resolve each file against the pinned
# manifest tree instead of assuming the newer C++ filenames exist.
set(LIBLOG_SOURCES)
foreach(_name
    config_read config_write local_logger log_event_list log_event_write
    log_ratelimit logger_lock logger_name logger_read logger_write
    logprint stderr_write fake_log_device fake_writer event_tag_map
    log_time properties pmsg_reader pmsg_writer logd_reader logd_writer
)
    if(EXISTS "${SRC}/logging/liblog/${_name}.cpp")
        list(APPEND LIBLOG_SOURCES "${SRC}/logging/liblog/${_name}.cpp")
    elseif(EXISTS "${SRC}/logging/liblog/${_name}.c")
        list(APPEND LIBLOG_SOURCES "${SRC}/logging/liblog/${_name}.c")
    endif()
endforeach()

if(NOT LIBLOG_SOURCES)
    message(FATAL_ERROR "No liblog sources found in pinned AOSP source tree")
endif()

add_library(liblog STATIC ${LIBLOG_SOURCES})

# The standalone tools compile against API 24, while this private in-tree
# liblog implementation requires the length-aware internal interface (v2).
if(EXISTS "${SRC}/logging/liblog/include/log/log_main.h")
    # The legacy pmsg writer uses the private debuggable query declared in
# log/log_properties.h but does not include that header itself.
foreach(_pmsg_source
    "${SRC}/logging/liblog/pmsg_writer.c"
    "${SRC}/logging/liblog/pmsg_writer.cpp"
)
    if(EXISTS "${_pmsg_source}" AND EXISTS "${SRC}/logging/liblog/include/log/log_properties.h")
        set_source_files_properties("${_pmsg_source}" PROPERTIES
            COMPILE_FLAGS "-include ${SRC}/logging/liblog/include/log/log_properties.h")
    endif()
endforeach()

target_compile_definitions(liblog PRIVATE __ANDROID_USE_LIBLOG_LOGGABLE_INTERFACE=2)
endif()

target_compile_definitions(liblog PRIVATE
    LIBLOG_LOG_TAG=1006
    _XOPEN_SOURCE=700
    FAKE_LOG_DEVICE=1
    SNET_EVENT_LOG_TAG=1397638686
    ANDROID_DEBUGGABLE=0
)

target_include_directories(liblog PRIVATE
    ${SRC}/core/include
    ${SRC}/logging/liblog/include
    ${SRC}/core/libcutils/include
    ${SRC}/libbase/include
)

set_target_properties(liblog PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    CXX_EXTENSIONS OFF
)
