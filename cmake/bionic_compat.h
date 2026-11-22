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

