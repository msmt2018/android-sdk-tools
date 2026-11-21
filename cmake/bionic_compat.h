/*
 * Compatibility shim for older AOSP snapshots built with modern Android NDKs.
 * Some NDK sys/cdefs.h configurations leave __unused undefined for C++.
 */
#pragma once
#if defined(__ANDROID__)
#include <sys/cdefs.h>
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#endif
