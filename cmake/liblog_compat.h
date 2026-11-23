/*
 * Compatibility declaration for the Android P liblog C translation unit.
 * The pinned AOSP implementation is provided by properties.c/.cpp, but some
 * historical private headers do not declare this internal function.
 */
#pragma once

#ifdef __cplusplus
extern "C" {
#endif
int __android_log_is_debuggable(void);
#ifdef __cplusplus
}
#endif
