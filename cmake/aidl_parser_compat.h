#pragma once

// The generated Flex scanner includes aidl_language_y.h, whose YYSTYPE union
// uses AIDL AST declarations and std::map. Keep those declarations visible
// without relying on repeated -include options that CMake may de-duplicate.
#include <map>
#include "aidl_language.h"
