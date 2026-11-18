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

set(LIBANDROIDFW_APK_PARSING_SRC)
if(EXISTS "${SRC}/base/libs/androidfw/ApkParsing.cpp")
    list(APPEND LIBANDROIDFW_APK_PARSING_SRC ${SRC}/base/libs/androidfw/ApkParsing.cpp)
endif()

set(LIBANDROIDFW_BIGBUFFER_SRC)
if(EXISTS "${SRC}/base/libs/androidfw/BigBuffer.cpp")
    list(APPEND LIBANDROIDFW_BIGBUFFER_SRC ${SRC}/base/libs/androidfw/BigBuffer.cpp)
endif()

set(LIBANDROIDFW_BIGBUFFER_STREAM_SRC)
if(EXISTS "${SRC}/base/libs/androidfw/BigBufferStream.cpp")
    list(APPEND LIBANDROIDFW_BIGBUFFER_STREAM_SRC ${SRC}/base/libs/androidfw/BigBufferStream.cpp)
endif()

set(LIBANDROIDFW_FILE_STREAM_SRC)
if(EXISTS "${SRC}/base/libs/androidfw/FileStream.cpp")
    list(APPEND LIBANDROIDFW_FILE_STREAM_SRC ${SRC}/base/libs/androidfw/FileStream.cpp)
endif()

add_library(libandroidfw STATIC
    ${SRC}/base/libs/androidfw/ApkAssets.cpp
    ${LIBANDROIDFW_APK_PARSING_SRC}
    ${SRC}/base/libs/androidfw/Asset.cpp
    ${SRC}/base/libs/androidfw/AssetDir.cpp
    ${SRC}/base/libs/androidfw/AssetManager.cpp
    ${SRC}/base/libs/androidfw/AssetManager2.cpp
    ${SRC}/base/libs/androidfw/AssetsProvider.cpp
    ${SRC}/base/libs/androidfw/AttributeResolution.cpp
    ${LIBANDROIDFW_BIGBUFFER_SRC}
    ${LIBANDROIDFW_BIGBUFFER_STREAM_SRC}
    ${SRC}/base/libs/androidfw/ChunkIterator.cpp
    ${SRC}/base/libs/androidfw/ConfigDescription.cpp
    ${LIBANDROIDFW_FILE_STREAM_SRC}
    ${SRC}/base/libs/androidfw/Idmap.cpp
    ${SRC}/base/libs/androidfw/LoadedArsc.cpp
    ${SRC}/base/libs/androidfw/Locale.cpp
    ${SRC}/base/libs/androidfw/LocaleData.cpp
    ${SRC}/base/libs/androidfw/misc.cpp
    ${SRC}/base/libs/androidfw/NinePatch.cpp
    ${SRC}/base/libs/androidfw/ObbFile.cpp
    ${SRC}/base/libs/androidfw/PosixUtils.cpp
    ${SRC}/base/libs/androidfw/Png.cpp
    ${SRC}/base/libs/androidfw/PngChunkFilter.cpp
    ${SRC}/base/libs/androidfw/PngCrunch.cpp
    ${SRC}/base/libs/androidfw/ResourceTimer.cpp
    ${SRC}/base/libs/androidfw/ResourceTypes.cpp
    ${SRC}/base/libs/androidfw/ResourceUtils.cpp
    ${SRC}/base/libs/androidfw/StreamingZipInflater.cpp
    ${SRC}/base/libs/androidfw/StringPool.cpp
    ${SRC}/base/libs/androidfw/TypeWrappers.cpp
    ${SRC}/base/libs/androidfw/Util.cpp
    ${SRC}/base/libs/androidfw/ZipFileRO.cpp
    ${SRC}/base/libs/androidfw/ZipUtils.cpp  
    ${SRC}/base/libs/androidfw/PathUtils.cpp     
    )

target_compile_definitions(libandroidfw PRIVATE 
    -DSTATIC_ANDROIDFW_FOR_TOOLS
    -D_GNU_SOURCE -DNDEBUG
    )

target_include_directories(libandroidfw PUBLIC
    ${SRC}/base/libs/androidfw/include
    ${SRC}/base/libs/androidfw/include_pathutils
    ${SRC}/core/libcutils/include
    ${SRC}/logging/liblog/include
    ${SRC}/core/libsystem/include
    ${SRC}/core/libutils/include
    ${SRC}/libpng
    ${SRC}/libbase/include
    ${SRC}/native/include
    ${SRC}/native/libs/binder/include
    ${SRC}/libziparchive/include
    ${SRC}/incremental_delivery/incfs/util/include
    ${SRC}/incremental_delivery/incfs/kernel-headers
    )
    
target_link_libraries(libandroidfw PUBLIC fmt::fmt)
