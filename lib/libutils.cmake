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

# Android 14 keeps these sources directly under libutils; newer snapshots
# place binder-related sources in the binder/ subdirectory.
set(LIBUTILS_BINDER_DIR "${SRC}/core/libutils/binder")
if(NOT EXISTS "${LIBUTILS_BINDER_DIR}/SharedBuffer.cpp")
    set(LIBUTILS_BINDER_DIR "${SRC}/core/libutils")
endif()

set(LIBUTILS_BINDER_ERRORS_SRC)
if(EXISTS "${LIBUTILS_BINDER_DIR}/Errors.cpp")
    list(APPEND LIBUTILS_BINDER_ERRORS_SRC ${LIBUTILS_BINDER_DIR}/Errors.cpp)
endif()

set(LIBUTILS_REFBASE_SRC)
if(EXISTS "${LIBUTILS_BINDER_DIR}/RefBase.cpp")
    list(APPEND LIBUTILS_REFBASE_SRC ${LIBUTILS_BINDER_DIR}/RefBase.cpp)
endif()

set(LIBUTILS_BINDER_SRC
    ${LIBUTILS_BINDER_ERRORS_SRC}
    ${LIBUTILS_REFBASE_SRC}
    ${LIBUTILS_BINDER_DIR}/SharedBuffer.cpp
    ${LIBUTILS_BINDER_DIR}/String16.cpp
    ${LIBUTILS_BINDER_DIR}/String8.cpp
    ${LIBUTILS_BINDER_DIR}/StrongPointer.cpp
    ${LIBUTILS_BINDER_DIR}/Unicode.cpp
    ${LIBUTILS_BINDER_DIR}/VectorImpl.cpp
    )


set(LIBUTILS_LIGHT_REF_BASE_SOURCE)
if(EXISTS "${LIBUTILS_LIGHT_REF_BASE_SOURCE}")
    list(APPEND LIBUTILS_LIGHT_REF_BASE_SOURCE "${SRC}/core/libutils/LightRefBase.cpp")
endif()

add_library(libutils STATIC
    ${SRC}/core/libutils/FileMap.cpp
    ${SRC}/core/libutils/JenkinsHash.cpp
    ${SRC}/core/libutils/LightRefBase.cpp
    ${SRC}/core/libutils/NativeHandle.cpp
    ${SRC}/core/libutils/Printer.cpp
    ${SRC}/core/libutils/StopWatch.cpp
    ${SRC}/core/libutils/SystemClock.cpp
    ${SRC}/core/libutils/Threads.cpp
    ${SRC}/core/libutils/Timers.cpp
    ${SRC}/core/libutils/Tokenizer.cpp
    ${SRC}/core/libutils/misc.cpp
    ${SRC}/core/libutils/Looper.cpp
    ${LIBUTILS_BINDER_SRC}
    )

# see core/libutils/Android.bp, Trace.cpp is only for android
if(SDK_TARGET_ANDROID)
    target_sources(libutils PRIVATE ${SRC}/core/libutils/Trace.cpp)
endif()

target_include_directories(libutils PRIVATE
    ${SRC}/core/include
    ${SRC}/core/libutils/include
    ${SRC}/core/libprocessgroup/include
    ${SRC}/core/libvndksupport/include
    ${SRC}/logging/liblog/include 
    ${SRC}/libbase/include
    ${SRC}/unwinding/libbacktrace/include
    )
    
    