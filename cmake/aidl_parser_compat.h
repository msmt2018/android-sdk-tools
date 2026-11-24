#pragma once

// The generated Flex scanner's semantic union uses declarations from the
// parser-facing AIDL header. Newer AIDL revisions moved AidlToken from
// aidl_language.h into parser.h; prefer that header when present.
#include <map>
#if __has_include("parser.h")
#include "parser.h"
#else
#include "aidl_language.h"
#endif
