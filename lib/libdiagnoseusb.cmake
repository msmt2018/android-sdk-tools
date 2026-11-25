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

set(LIBDIAGNOSEUSB_SOURCE)
set(LIBDIAGNOSEUSB_INCLUDE_DIR)
if(EXISTS "${SRC}/core/diagnose_usb/diagnose_usb.cpp")
    set(LIBDIAGNOSEUSB_SOURCE "${SRC}/core/diagnose_usb/diagnose_usb.cpp")
    set(LIBDIAGNOSEUSB_INCLUDE_DIR "${SRC}/core/diagnose_usb/include")
elseif(EXISTS "${SRC}/core/adb/diagnose_usb.cpp")
    # Android 9 keeps diagnose_usb alongside adb rather than in its own directory.
    set(LIBDIAGNOSEUSB_SOURCE "${SRC}/core/adb/diagnose_usb.cpp")
    set(LIBDIAGNOSEUSB_INCLUDE_DIR "${SRC}/core/adb")
endif()

if(LIBDIAGNOSEUSB_SOURCE)
    add_library(libdiagnoseusb STATIC ${LIBDIAGNOSEUSB_SOURCE})
    target_include_directories(libdiagnoseusb PRIVATE
        ${LIBDIAGNOSEUSB_INCLUDE_DIR}
        ${SRC}/core/include
        ${SRC}/libbase/include
    )
    target_link_libraries(libdiagnoseusb PUBLIC libbase)
else()
    message(STATUS "diagnose_usb: not present in this AOSP snapshot; skipping")
endif()
