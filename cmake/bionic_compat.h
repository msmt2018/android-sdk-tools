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
