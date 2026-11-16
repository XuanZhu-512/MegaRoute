"""Build a MegaRoute routing board from exported KiCad geometry and project rules."""
import json
import math
from pathlib import Path


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
    if poly.get("holes"):
        raise ValueError("unsupported_feature: polygon holes are not part of the routing model")
    outer = [_point(p) for p in poly["outer"]]
    if len(outer) < 3:
        raise ValueError("degenerate polygon")
    return outer


def _circle_layers(parts):
    sizes = []
    for part in parts:
        if part.get("shape_code") != CIRCLE:
            return None
        width, height = _point(part["size_mm"])
        if width != height or width <= 0:
            return None
        sizes.append(width)
    if len(set(sizes)) != 1:
        return None
    return sizes[0] / 2


def _class_for(name, classes, assignments):
    chosen = assignments.get(name, "Default")
    if chosen not in classes:
        raise ValueError(f"unknown net class for {name}: {chosen}")
    return classes[chosen]


def _via_radius(center, item):
    x, y = center
    radius = 0
    for part in item["copper"]:
        for poly in part["polygons"]:
            for px, py in _rings([poly]):
                radius = max(radius, math.hypot(px - x, py - y))
    return radius


def adapt_geometry(geometry, rules):
    if geometry.get("schema_version") != "kicad-geometry-1.0" or geometry.get("units") != "mm":
        raise ValueError("expected kicad-geometry-1.0 in mm")
    patterns = rules.get("net_settings", {}).get("netclass_patterns") or []
    if patterns:
        raise ValueError("unsupported_feature: netclass_patterns")
    design = rules["board"]["design_settings"]["rules"]
    classes = {item["name"]: item for item in rules["net_settings"]["classes"]}
    if "Default" not in classes:
        raise ValueError("project rules have no Default net class")
    assignments = rules.get("net_settings", {}).get("netclass_assignments") or {}
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
        rule = _class_for(net["name"], classes, assignments)
        nets.append({"id": net["name"], "width": rule["track_width"], "clearance": rule["clearance"]})
    known = {net["id"] for net in nets}
    pads = []
    for pad in geometry["pads"]:
        if pad.get("attribute") == "plated_through_hole":
            plated = True
        elif pad.get("attribute") == "smd":
            plated = False
        else:
            raise ValueError(f"unsupported_feature: pad attribute {pad.get('attribute')}")
        if pad.get("net_name") not in known:
            raise ValueError(f"pad {pad['id']} has no electrical net")
        copper = pad["copper"]
        if not copper:
            raise ValueError(f"pad {pad['id']} has no copper")
        layers = [part["layer"] for part in copper]
        if len(layers) != len(set(layers)):
            raise ValueError(f"duplicate copper layer on pad {pad['id']}")
        center = _point(pad["position_mm"])
        radius = _circle_layers(copper)
        record = {"id": pad["id"], "net": pad["net_name"], "center": center, "layers": layers, "plated": plated}
        if radius is not None:
            record.update(kind="circle", radius=radius)
        elif len(copper) == 1:
            record.update(kind="polygon", points=_rings(copper[0]["polygons"]))
        else:
            raise ValueError("unsupported_feature: plated pad layers do not share one circle")
        pads.append(record)
    fixed = []
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
    for item in geometry.get("copper_graphics", []):
        if len(item["copper"]) != 1:
            raise ValueError("unsupported_feature: copper graphic on multiple layers")
        part = item["copper"][0]
        fixed.append({"id": item["id"], "kind": "polygon", "layers": [part["layer"]],
                      "points": _rings(part["polygons"]),
                      "center": _point(part["polygons"][0]["outer"][0])})
    return {"schema_version": "1.0", "units": "mm", "layers": layer_count, "outline": outline,
            "holes": holes, "nets": nets, "pads": pads, "fixed_copper": fixed, "keepouts": [],
            "rules": {"min_width": design["min_track_width"], "clearance": design["min_clearance"],
                      "edge_clearance": design["min_copper_edge_clearance"],
                      "via_diameter": design["min_via_diameter"],
                      "via_drill": design["min_through_hole_diameter"],
                      "min_annular": design["min_via_annular_width"]}}


def adapt_files(geometry_path, rules_path, out_path):
    geometry = json.loads(Path(geometry_path).read_text(encoding="utf-8"))
    rules = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    board = adapt_geometry(geometry, rules)
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")
    return board
