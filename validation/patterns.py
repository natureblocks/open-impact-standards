global_ref_identifier = "^\d+$"
global_ref_alias = "^{.+}$"
global_alias_ref = "(^(action|checkpoint|thread|object|object_promise|party):{.+}).?(.*)$"
global_id_ref = "(^(action|checkpoint|thread|object|object_promise|party):\d+).?(.*)$"

# must begin with "$_", which is reserved for local variables
local_variable = "^\$_.+$"

# must begin with "$", but not the reserved "$_" or the invalid "$."
variable = "^\$(?![_\.]).+$"

# a reference to a collection or field on a collection in an aggregation pipeline filter
filter_ref = "^\$_item(\..+)?"

# hex color code
hex_code = "^#(?:[0-9a-fA-F]{3}){1,2}$"

# cannot include "_", "{", "}", or ":" (avoids ref parsing issues)
alias = "^[^_\{\}:]+$"

# cannot include "."
dotless = "^[^\.]*$"