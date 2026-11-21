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

set(LIBLOG_EVENT_LIST_SOURCE)
if(EXISTS "${SRC}/logging/liblog/log_event_list.cpp")
    list(APPEND LIBLOG_EVENT_LIST_SOURCE "${SRC}/logging/liblog/log_event_list.cpp")
endif()

add_library(liblog STATIC
    ${LIBLOG_EVENT_LIST_SOURCE}
    ${SRC}/logging/liblog/log_event_write.cpp
    ${SRC}/logging/liblog/logger_name.cpp
    ${SRC}/logging/liblog/logger_read.cpp
    ${SRC}/logging/liblog/logger_write.cpp
    ${SRC}/logging/liblog/properties.cpp
    ${SRC}/logging/liblog/logprint.cpp
    ${SRC}/logging/liblog/event_tag_map.cpp
    ${SRC}/logging/liblog/log_time.cpp
    ${SRC}/logging/liblog/pmsg_reader.cpp
    ${SRC}/logging/liblog/pmsg_writer.cpp
    ${SRC}/logging/liblog/logd_reader.cpp
    ${SRC}/logging/liblog/logd_writer.cpp
    )

target_compile_definitions(liblog PRIVATE
    LIBLOG_LOG_TAG=1006
    _XOPEN_SOURCE=700
    FAKE_LOG_DEVICE=1
    SNET_EVENT_LOG_TAG=1397638686
    ANDROID_DEBUGGABLE=0

    )
    
# Prefer the release-matched liblog public header over the older core/include copy.
if(EXISTS "${SRC}/logging/liblog/include/android/log.h")
    target_include_directories(liblog BEFORE PRIVATE ${SRC}/logging/liblog/include)
endif()

target_include_directories(liblog PRIVATE
    ${SRC}/core/include
    ${SRC}/logging/liblog/include
    ${SRC}/core/libcutils/include
    ${SRC}/libbase/include
    )
    
# Historical liblog relies on std::unary_function, removed in C++20.
# Bionic does not expose this legacy annotation in every NDK API level.
# Quote the attribute so the shell does not parse its parentheses.
target_compile_options(liblog PRIVATE "SHELL:-D__unused='__attribute__((unused))'")

set_target_properties(liblog PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON CXX_EXTENSIONS OFF)
