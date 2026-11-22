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

set(LIBPROCESSGROUP_CGROUP_MAP_SOURCE)
if(EXISTS "${SRC}/core/libprocessgroup/cgroup_map.cpp")
    list(APPEND LIBPROCESSGROUP_CGROUP_MAP_SOURCE "${SRC}/core/libprocessgroup/cgroup_map.cpp")
endif()

# cgroup_map consumes libcgrouprc APIs implemented in this same static
# library. Compile this translation unit against the API level that introduced
# those in-tree interfaces, without raising the NDK API level for other code.
if(LIBPROCESSGROUP_CGROUP_MAP_SOURCE)
    if(TOOLS_VERSION VERSION_GREATER_EQUAL "30.0.0")
        set_source_files_properties(${LIBPROCESSGROUP_CGROUP_MAP_SOURCE}
            PROPERTIES COMPILE_OPTIONS "-U__ANDROID_API__;-D__ANDROID_API__=30")
    else()
        set_source_files_properties(${LIBPROCESSGROUP_CGROUP_MAP_SOURCE}
            PROPERTIES COMPILE_OPTIONS "-U__ANDROID_API__;-D__ANDROID_API__=29")
    endif()
endif()

# Keep private in-tree cgrouprc consumers at the project's API 24 target.
if(LIBPROCESSGROUP_CGROUP_MAP_SOURCE)
    set_source_files_properties(${LIBPROCESSGROUP_CGROUP_MAP_SOURCE}
        PROPERTIES COMPILE_OPTIONS "-U__ANDROID_API__;-D__ANDROID_API__=24")
endif()

add_library(libprocessgroup STATIC
    ${LIBPROCESSGROUP_CGROUP_MAP_SOURCE}
    ${SRC}/core/libprocessgroup/processgroup.cpp
    ${SRC}/core/libprocessgroup/sched_policy.cpp
    ${SRC}/core/libprocessgroup/task_profiles.cpp
    ${SRC}/core/libprocessgroup/cgrouprc_format/cgroup_controller.cpp
    ${SRC}/core/libprocessgroup/cgrouprc/cgroup_controller.cpp
    ${SRC}/core/libprocessgroup/cgrouprc/cgroup_file.cpp
    )

target_include_directories(libprocessgroup PRIVATE 
    ${SRC}/core/libprocessgroup/include
    ${SRC}/core/libprocessgroup/cgrouprc/include
    ${SRC}/core/libprocessgroup/cgrouprc_format/include
    ${SRC}/core/libprocessgroup/util/include
    ${SRC}/libbase/include
    ${SRC}/core/libcutils/include
    ${SRC}/jsoncpp/include
    )
target_include_directories(libprocessgroup PRIVATE
    ${SRC}/core/libprocessgroup
    )