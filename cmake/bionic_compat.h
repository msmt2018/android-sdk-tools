/*
 * Compatibility shim for older AOSP snapshots built with modern Android NDKs.
 * Bionic fortify declarations in fcntl.h require __unused to be an attribute
 * macro, even when a previous sys/cdefs.h include left it unavailable.
 */
#pragma once

#if defined(ANDROID) || defined(__ANDROID__) || defined(__BIONIC__)
#include <sys/cdefs.h>
#ifdef __unused
#undef __unused
#endif
#define __unused __attribute__((__unused__))
/* Parse fortify declarations while the compatibility annotation is defined. */
#include <fcntl.h>
#ifndef __unused
#define __unused __attribute__((__unused__))
#endif
#endif
#if defined(SDK_USE_HASMNTOPT_COMPAT) && defined(__ANDROID_API__) && __ANDROID_API__ < 26 && !defined(__cplusplus)
#include <mntent.h>
#include <stddef.h>
#include <string.h>
/* Bionic lacks GNU hasmntopt(); emulate its comma-delimited option matching. */
static inline char *sdk_hasmntopt(const struct mntent *mnt, const char *opt) {
    if (mnt == NULL || mnt->mnt_opts == NULL || opt == NULL || opt[0] == '\0') return NULL;
    size_t opt_len = strlen(opt);
    const char *cursor = mnt->mnt_opts;
    while (cursor != NULL && cursor[0] != '\0') {
        const char *end = strchr(cursor, ',');
        size_t token_len = end != NULL ? (size_t)(end - cursor) : strlen(cursor);
        if (token_len >= opt_len && strncmp(cursor, opt, opt_len) == 0 &&
            (token_len == opt_len || cursor[opt_len] == '=')) return (char *)cursor;
        if (end == NULL) break;
        cursor = end + 1;
    }
    return NULL;
}
#define hasmntopt sdk_hasmntopt
#endif


/*
 * __system_property_read_callback was added to the public NDK surface at API 26.
 * Adapt release-generated sysprop code for the API-24 toolchain using the
 * older property read primitive that remains available at this API level.
 */
#if defined(__ANDROID_API__) && __ANDROID_API__ < 26
#include <sys/system_properties.h>
#include <stdint.h>
typedef void (*sdk_system_property_read_callback_fn)(
    void* cookie, const char* name, const char* value, uint32_t serial);
static inline int sdk_compat_system_property_read_callback(
    const prop_info* pi,
    sdk_system_property_read_callback_fn callback,
    void* cookie) {
    char name[PROP_NAME_MAX] = {};
    char value[PROP_VALUE_MAX] = {};
    int serial = __system_property_read(pi, name, value);
    if (serial >= 0 && callback != NULL) {
        callback(cookie, name, value, (uint32_t)serial);
    }
    return serial < 0 ? serial : 0;
}
#define __system_property_read_callback sdk_compat_system_property_read_callback
#endif
