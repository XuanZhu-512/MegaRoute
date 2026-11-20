"""Build a MegaRoute routing board from exported KiCad geometry and project rules."""
import json
import math
from pathlib import Path

from .netclass import resolve_net_classes


CIRCLE = 0
THROUGH_VIA = 0


def _point(value):
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(v, (int, float)) for v in value):
        raise ValueError("point must be [x, y]")
    return [value[0], value[1]]


def _rings(polygons):
    if len(polygons) != 1:
        raise ValueError("unsupported_feature: copper with multiple outlines")
    poly = polygons[0]
    outer = [_point(p) for p in poly["outer"]]
    if len(outer) < 3:
        raise ValueError("degenerate polygon")
    holes = [[_point(p) for p in ring] for ring in poly.get("holes", [])]
    if any(len(ring) < 3 for ring in holes):
        raise ValueError("degenerate copper hole")
    return {"points": outer, "holes": holes}


def _shared_outline(parts):
    layers = [part["layer"] for part in parts]
    if len(layers) != len(set(layers)):
        raise ValueError("duplicate copper layer on pad")
    radius = _circle_layers(parts)
    if radius is not None:
        return {"kind": "circle", "radius": radius, "layers": layers}
    first = parts[0]["polygons"]
    if any(part["polygons"] != first for part in parts):
        raise ValueError("unsupported_feature: pad layers do not share one outline")
    return {"kind": "polygon", **_rings(first), "layers": layers}


def _circle_layers(parts):
    sizes = []
    for part in parts:
        if any(poly.get("holes") for poly in part.get("polygons", [])):
            return None
        if part.get("shape_code") != CIRCLE:
            return None
        width, height = _point(part["size_mm"])
        if width != height or width <= 0:
            return None
        sizes.append(width)
    if len(set(sizes)) != 1:
        return None
    return sizes[0] / 2


def _class_for(name, classes, resolved):
    chosen = resolved.get(name, "Default")
    if chosen not in classes:
        raise ValueError(f"unknown net class for {name}: {chosen}")
    return classes[chosen]


def _via_radius(center, item):
    x, y = center
    radius = 0
    for part in item["copper"]:
        for poly in part["polygons"]:
            for px, py in _rings([poly])["points"]:
                radius = max(radius, math.hypot(px - x, py - y))
    return radius


def _routing_via(design, classes, resolved):
    """Choose one shared through via; board minima are constraints, not a preset.

    The engine currently has one via size for all nets. Use the largest requested
    dimensions among active classes, then enforce the board's manufacturing limits.
    Round upwards to KiCad's integer nanometres so writeback cannot shrink a ring.
    """
    def nm(value):
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid via dimension")
        return math.ceil(round(value * 1_000_000, 6))

    used = {resolved[name] for name in resolved} or {"Default"}
    if not used <= classes.keys():
        raise ValueError("unknown net class in via selection")
    drill = max([nm(design["min_through_hole_diameter"])] +
                [nm(classes[name].get("via_drill", design["min_through_hole_diameter"])) for name in used])
    if drill <= 0:
        raise ValueError("through via drill must be positive")
    diameter = max([nm(design["min_via_diameter"]),
                    drill + max(1, 2 * nm(design["min_via_annular_width"]))] +
                   [nm(classes[name].get("via_diameter", design["min_via_diameter"])) for name in used])
    return diameter / 1_000_000, drill / 1_000_000


def adapt_geometry(geometry, rules):
    if geometry.get("schema_version") != "kicad-geometry-1.0" or geometry.get("units") != "mm":
        raise ValueError("expected kicad-geometry-1.0 in mm")
    design = rules["board"]["design_settings"]["rules"]
    net_settings = rules.get("net_settings") or {}
    classes = {item["name"]: item for item in net_settings.get("classes") or []}
    if "Default" not in classes:
        raise ValueError("project rules have no Default net class")
    net_names = [net["name"] for net in geometry["nets"] if net.get("code")]
    resolved = resolve_net_classes(net_settings, net_names)
    via_diameter, via_drill = _routing_via(design, classes, resolved)
    outlines = geometry["outline"]
    if len(outlines) != 1:
        raise ValueError("unsupported_feature: multiple board outlines")
    outline = [_point(point) for point in outlines[0]["outer"]]
    holes = [[_point(point) for point in ring] for ring in outlines[0].get("holes", [])]
    if len(outline) < 3 or any(len(ring) < 3 for ring in holes):
        raise ValueError("degenerate board outline")
    layer_count = len(geometry["layers"])
    if layer_count < 1:
        raise ValueError("board has no copper layers")
    nets = []
    for net in geometry["nets"]:
        if net["code"] == 0:
            continue
        if not net["name"]:
            raise ValueError("unnamed electrical net")
        rule = _class_for(net["name"], classes, resolved)
        nets.append({"id": net["name"], "width": rule["track_width"], "clearance": rule["clearance"]})
    known = {net["id"] for net in nets}
    pads = []
    fixed = []
    normalized_clearances = []
    ignored_pads = []
    def clearance(item):
        value = item.get("local_clearance_mm")
        if value is None:
            return {}
        if value < 0:
            # Legacy KiCad pads may store negative local clearance. It is not
            # negative physical spacing: retain raw provenance, use the existing
            # zero/fallback semantics, and keep net/board minimum checks intact.
            normalized_clearances.append({"id": item["id"], "raw_mm": value, "effective_override_mm": 0})
        return {"clearance_override": max(0, value)}
    # Non-plated copper on separate layers is not a vertical connection. Model
    # each layer independently, including connector pads with different outlines.
    pad_parts = []
    for pad in geometry["pads"]:
        if pad.get("attribute") in ("smd", "connector") and len(pad["copper"]) > 1:
            for part in pad["copper"]:
                pad_parts.append({**pad, "id": f"{pad['id']}:L{part['layer']}", "copper": [part]})
        else:
            pad_parts.append(pad)
    for pad in pad_parts:
        attribute = pad.get("attribute")
        if attribute == "plated_through_hole":
            plated = True
        elif attribute in ("smd", "non_plated_hole", "connector"):
            plated = False
        else:
            raise ValueError(f"unsupported_feature: pad attribute {attribute}")
        copper = pad["copper"]
        if not copper:
            # A non-electrical, drill-free, non-copper auxiliary pad has no
            # routing geometry. Keep it in the immutable KiCad board only.
            if (attribute in ("smd", "connector") and not pad.get("net_name") and
                    not pad.get("net_code", 0) and pad.get("drill_size_mm") == [0, 0]):
                ignored_pads.append({"id": pad["id"], "reason": "non_copper_non_electrical_pad"})
                continue
            raise ValueError(f"pad {pad['id']} has no copper")
        center = _point(pad["position_mm"])
        shape = _shared_outline(copper)
        net_name = pad.get("net_name") or ""
        obstacle = attribute == "non_plated_hole" or net_name not in known
        if obstacle and net_name:
            raise ValueError(f"pad {pad['id']} has no electrical net")
        if shape["kind"] == "circle" and obstacle:
            shape = {"kind": "polygon", **_rings(copper[0]["polygons"]), "layers": shape["layers"]}
        # The routing access point must lie on copper, even for a custom annular pad.
        # Keep the source position in the lossless geometry bundle; use a valid
        # outer-boundary access point for polygon pads with explicit cutouts.
        if shape.get("holes"):
            center = shape["points"][0]
        record = {"id": pad["id"], "center": center, "layers": shape["layers"], **{
            key: shape[key] for key in ("kind", "radius", "points", "holes") if key in shape}}
        record.update(clearance(pad))
        if obstacle:
            # KiCad permits overlapping pieces of one numbered pad in a
            # footprint, even when no net is assigned. Do not exempt separate
            # pad numbers, footprints, or unnumbered decorative copper.
            if not net_name and pad.get("number") and pad.get("footprint_uuid"):
                record["copper_group"] = "pad:" + json.dumps([pad["footprint_uuid"], pad["number"]])
            if plated and len(shape["layers"]) > 1:
                record["plated"] = True
                fixed.append(record)
            elif len(shape["layers"]) == 1:
                fixed.append(record)
            else:
                for layer in shape["layers"]:
                    piece = dict(record)
                    piece["id"] = f"{pad['id']}:L{layer}"
                    piece["layers"] = [layer]
                    fixed.append(piece)
            continue
        record.update(net=net_name, plated=plated)
        pads.append(record)
    for item in geometry["tracks_and_vias"]:
        kind = item.get("type")
        if kind == "PCB_ARC":
            raise ValueError("unsupported_feature: arc tracks")
        if kind == "PCB_VIA":
            if item.get("via_type_code") != THROUGH_VIA:
                raise ValueError("unsupported_feature: only through vias")
            center = _point(item["position_mm"])
            radius = _via_radius(center, item)
            drill = item["drill_mm"]
            if not (drill > 0 and radius > drill / 2):
                raise ValueError(f"invalid via {item['id']}")
            fixed.append({"id": item["id"], "net": item.get("net_name") or "", "kind": "via",
                          "center": center, "radius": radius, "drill": drill,
                          "layers": list(range(layer_count))})
        elif kind == "PCB_TRACK":
            layers = [part["layer"] for part in item["copper"]]
            if len(layers) != 1:
                raise ValueError("unsupported_feature: track must occupy one copper layer")
            fixed.append({"id": item["id"], "net": item.get("net_name") or "", "kind": "segment",
                          "a": _point(item["start_mm"]), "b": _point(item["end_mm"]),
                          "width": item["width_mm"], "layers": layers})
        else:
            raise ValueError(f"unsupported_feature: copper item {kind}")
        fixed[-1].update(clearance(item))
    for item in geometry.get("copper_graphics", []):
        if len(item["copper"]) != 1:
            raise ValueError("unsupported_feature: copper graphic on multiple layers")
        part = item["copper"][0]
        if "primitives" in part:
            if item.get("type") not in ("PCB_TEXT", "PCB_FIELD"):
                raise ValueError("unsupported_feature: primitives require copper text")
            for i, primitive in enumerate(part["primitives"]):
                if primitive.get("kind") == "segment":
                    shape = {"kind": "segment", "a": _point(primitive["a"]),
                             "b": _point(primitive["b"]), "width": primitive["width"]}
                elif primitive.get("kind") == "polygon":
                    shape = {"kind": "polygon", "center": _point(primitive["center"]),
                             "points": [_point(p) for p in primitive["points"]]}
                else:
                    raise ValueError("unsupported_feature: copper text primitive")
                fixed.append({**shape, "id": f"{item['id']}:text:{i}",
                              "copper_group": item["id"], "layers": [part["layer"]]})
            continue
        fixed.append({"id": item["id"], "kind": "polygon", "layers": [part["layer"]],
                      **_rings(part["polygons"]),
                      "center": _point(part["polygons"][0]["outer"][0])})
    board = {"schema_version": "1.0", "units": "mm", "layers": layer_count, "outline": outline,
            "holes": holes, "nets": nets, "pads": pads, "fixed_copper": fixed, "keepouts": [],
            "rules": {"min_width": design["min_track_width"], "clearance": design["min_clearance"],
                      "fixed_boundary_policy": "kicad_edges",
                      "edge_clearance": design["min_copper_edge_clearance"],
                      "via_diameter": via_diameter,
                      "via_drill": via_drill,
                      "min_annular": design["min_via_annular_width"]}}
    if normalized_clearances:
        board["metadata"] = {"normalized_local_clearances": normalized_clearances}
    if ignored_pads:
        board.setdefault("metadata", {})["ignored_pads"] = ignored_pads
    return board


def adapt_files(geometry_path, rules_path, out_path):
    geometry = json.loads(Path(geometry_path).read_text(encoding="utf-8"))
    rules = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    board = adapt_geometry(geometry, rules)
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    return board
