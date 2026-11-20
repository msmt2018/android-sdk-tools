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

add_library(libext4 STATIC
    ${SRC}/extras/ext4_utils/ext4_utils.cpp
    ${SRC}/extras/ext4_utils/wipe.cpp
    ${SRC}/extras/ext4_utils/ext4_sb.cpp
    )
target_include_directories(libext4 PRIVATE
    ${SRC}/core/libsparse/include
    ${SRC}/core/include
    ${SRC}/selinux/libselinux/include
    ${SRC}/extras/ext4_utils/include
    ${SRC}/libbase/include
    )

# The liblp source set differs between platform-tools snapshots. Keep every
# source provided by the selected AOSP tag, without requiring files introduced
# by a later release.
set(LIBFSMGR_SRC)
foreach(source
    images.cpp
    builder.cpp
    super_layout_builder.cpp
    property_fetcher.cpp
    partition_opener.cpp
    reader.cpp
    utility.cpp
    writer.cpp
    )
    if(EXISTS "${SRC}/core/fs_mgr/liblp/${source}")
        list(APPEND LIBFSMGR_SRC "${SRC}/core/fs_mgr/liblp/${source}")
    endif()
endforeach()

set(FASTBOOT_LIBFSMGR_TARGETS)
if(LIBFSMGR_SRC)
    add_library(libfsmgr STATIC ${LIBFSMGR_SRC})
    target_include_directories(libfsmgr PRIVATE
        ${SRC}/core/fs_mgr/liblp/include
        ${SRC}/libbase/include
        ${SRC}/extras/ext4_utils/include
        ${SRC}/core/libsparse/include
        ${SRC}/boringssl/include
        ${SRC}/core/libcutils/include
        )
    if(TARGET fmt::fmt)
        target_link_libraries(libfsmgr PUBLIC fmt::fmt)
    endif()
    list(APPEND FASTBOOT_LIBFSMGR_TARGETS libfsmgr)
else()
    # Android 9 snapshots predate logical partitions/liblp; the matching
    # fastboot source does not consume liblp in those releases.
    message(STATUS "liblp is absent from this AOSP snapshot; omitting libfsmgr")
endif()

set(FASTBOOT_FILESYSTEM_SRC)
if(EXISTS "${SRC}/core/fastboot/filesystem.cpp")
    list(APPEND FASTBOOT_FILESYSTEM_SRC ${SRC}/core/fastboot/filesystem.cpp)
endif()

set(FASTBOOT_STORAGE_SRC)
if(EXISTS "${SRC}/core/fastboot/storage.cpp")
    list(APPEND FASTBOOT_STORAGE_SRC ${SRC}/core/fastboot/storage.cpp)
endif()

set(FASTBOOT_TASK_SRC)
if(EXISTS "${SRC}/core/fastboot/task.cpp")
    list(APPEND FASTBOOT_TASK_SRC ${SRC}/core/fastboot/task.cpp)
endif()

set(FASTBOOT_SUPER_FLASH_SRC)
if(EXISTS "${SRC}/core/fastboot/super_flash_helper.cpp")
    list(APPEND FASTBOOT_SUPER_FLASH_SRC ${SRC}/core/fastboot/super_flash_helper.cpp)
endif()

set(FASTBOOT_VENDOR_BOOT_IMG_SOURCE)
if(EXISTS "${SRC}/core/fastboot/vendor_boot_img_utils.cpp")
    list(APPEND FASTBOOT_VENDOR_BOOT_IMG_SOURCE "${SRC}/core/fastboot/vendor_boot_img_utils.cpp")
endif()

add_executable(fastboot
    ${SRC}/core/fastboot/bootimg_utils.cpp
    ${SRC}/core/fastboot/fastboot.cpp
    ${SRC}/core/fastboot/fastboot_driver.cpp
    ${SRC}/core/fastboot/fs.cpp
    ${FASTBOOT_FILESYSTEM_SRC}
    ${FASTBOOT_SUPER_FLASH_SRC}
    ${SRC}/core/fastboot/main.cpp
    ${SRC}/core/fastboot/socket.cpp
    ${FASTBOOT_STORAGE_SRC}
    ${FASTBOOT_TASK_SRC}
    ${SRC}/core/fastboot/tcp.cpp
    ${SRC}/core/fastboot/udp.cpp
    ${SRC}/core/fastboot/usb_linux.cpp
    ${FASTBOOT_VENDOR_BOOT_IMG_SOURCE}
    ${SRC}/core/fastboot/util.cpp
    )

target_include_directories(fastboot PRIVATE
    ${SRC}/avb
    ${SRC}/libbase/include
    ${SRC}/soong/cc/libbuildversion/include
    ${SRC}/core/include
    ${SRC}/core/adb
    ${SRC}/core/libsparse/include
    ${SRC}/core/fs_mgr/liblp/include
    ${SRC}/core/fs_mgr/libstorage_literals
    ${SRC}/libziparchive/include
    ${SRC}/extras/ext4_utils/include
    ${SRC}/extras/f2fs_utils
    ${SRC}/mkbootimg/include/bootimg
    ${SRC}/core/diagnose_usb/include
    ${SRC}/googletest/googletest/include
    )
target_compile_definitions(fastboot PRIVATE
    -D_GNU_SOURCE
    -D_XOPEN_SOURCE=700
    -DUSE_F2FS
    )
set(FASTBOOT_DIAGNOSEUSB_TARGETS)
if(TARGET libdiagnoseusb)
    list(APPEND FASTBOOT_DIAGNOSEUSB_TARGETS libdiagnoseusb)
endif()

target_link_libraries(fastboot
    ${FASTBOOT_DIAGNOSEUSB_TARGETS}
    libsparse
    libziparchive
    libbuildversion
    libcutils
    ${FASTBOOT_LIBFSMGR_TARGETS}
    libutils
    libbase
    libext4
    libselinux
    libsepol
    liblog
    crypto
    pcre2-8
    sdk_system_libs
    )
