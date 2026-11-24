/*
 * Copyright (C) 2026 ZeroStudio
 * Licensed under the Apache License, Version 2.0.
 *
 * Platform-tools 30.x may contain the newer libbase logging.cpp interface
 * without the matching liblog_symbols.cpp translation unit. Return an empty
 * function table so logging.cpp uses its legacy liblog fallback path. This
 * avoids importing post-Android-10 private liblog symbols into this release.
 */
#include "liblog_symbols.h"

namespace android {
namespace base {

const std::optional<LibLogFunctions>& GetLibLogFunctions() {
    static const std::optional<LibLogFunctions> functions;
    return functions;
}

}  // namespace base
}  // namespace android
