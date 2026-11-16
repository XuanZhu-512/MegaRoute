# EasyEDA adapter boundary

Only the `IBoardImporter` / `EasyEdaImporter` contract is implemented. Calling the
EasyEDA adapter raises `unsupported_format`. There is no EasyEDA parsing or conversion script.

A future adapter must return the neutral `Board` model, preserve source identifiers
in a separate mapping, explicitly report unsupported geometry/rules, and convert
coordinates to mm and copper layers to stackup indices. Do not silently drop
unknown rules or create an empty board on import failure. Future export must map
route IDs and physical vias back to the original design without overwriting the input.
