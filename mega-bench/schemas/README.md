# Neutral protocol v1.0

`board`, `config`, `routes`, `event`, `metrics`: geometry-core IR and internal
diagnostics only. `case` and `toolchain`: public KiCad benchmark input manifests
and version locks. Formal cross-algorithm scores come from the KiCad evaluator
described in the repository README, not from these geometry-core schemas.

Schemas use JSON Schema draft 2020-12. `board`, `config`, and `routes` describe the
serialized inputs. `metrics` and `event` constrain stable envelope fields; additional
diagnostic output fields are intentionally extensible.

CLI validation additionally enforces constraints not expressible in these schemas:
unique IDs and valid net references, layer indices relative to the stackup, simple
polygons, holes strictly inside the board, access centers inside pads, positive
dimensions and annular rings, through-via spans, single-layer pads, and supported
object types for each collection. `metadata` is opaque provenance and does not
change routing rules. Unknown top-level and rule/config fields are rejected.

Coordinates and lengths are mm, drill is **diameter**, radius is copper **radius**.
Polygons omit the repeated closing vertex. `layers` on the board is the copper
layer count; `layers` on shapes is an explicit integer list in stackup order.
Routes contain only newly added segments/vias; the original board is never modified.
For manual route injection, supply a routes document to the `check` command.
