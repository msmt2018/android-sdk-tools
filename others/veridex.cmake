# Veridex was added after the Android 8.x tool source snapshots.
set(VERIDEX_SOURCES)
foreach(_source
    flow_analysis.cc
    hidden_api.cc
    hidden_api_finder.cc
    precise_hidden_api_finder.cc
    resolver.cc
    veridex.cc
)
    if(EXISTS "${SRC}/art/tools/veridex/${_source}")
        list(APPEND VERIDEX_SOURCES "${SRC}/art/tools/veridex/${_source}")
    endif()
endforeach()

if(VERIDEX_SOURCES)
    add_executable(veridex ${VERIDEX_SOURCES})
    target_include_directories(veridex PRIVATE
        ${SRC}/art/libdexfile
        ${SRC}/art/libartbase
        ${SRC}/fmtlib/include
        ${SRC}/logging/liblog/include
        ${SRC}/libbase/include
        ${SRC}/libziparchive/include
    )
    target_link_libraries(veridex
        libdexfile
        libartbase
        libartpalette
        libbase
        libutils
        liblog
        libziparchive
        fmt::fmt
        sdk_system_libs
    )
else()
    message(STATUS "veridex: not present in this historical AOSP manifest; skipping")
endif()
