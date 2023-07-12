global_ref_identifier = "^{.+}$"
global_ref = "(^(action|thread|object):{.+}).?(.*)$"

# must begin with "$_", which is reserved for local variables
local_variable = "^\$_.+$"

# must begin with "$", but not the reserved "$_"
variable = "^\$(?!_).+$"

# hex color code
hex_code = "^#(?:[0-9a-fA-F]{3}){1,2}$"
