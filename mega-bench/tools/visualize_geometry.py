"""Preview kicad-geometry JSON as a scene file and a Y-up SVG.

Coordinates are the parsed JSON numbers, written back with json.dumps.
No curve fitting and no rasterization.
"""
import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape


PALETTE = (
    "#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2",
    "#b279a2", "#ff9da6", "#9d755d", "#bab0ac", "#88d27a",
)


def number_text(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"coordinate must be a number, got {value!r}")
    return json.dumps(value)


def copy_polygons(polygons):
    copied = []
    for poly in polygons:
        copied.append({
            "outer": [list(point) for point in poly["outer"]],
            "holes": [[list(point) for point in ring] for ring in poly.get("holes", [])],
        })
    return copied


def drill_from_size(center, width, height):
    if width <= 0 or height <= 0:
        return None
    if width == height:
        return {"center": list(center), "radius": width / 2}
    return {"center": list(center), "radius_x": width / 2, "radius_y": height / 2}


def object_drill(item, role):
    if role == "via":
        diameter = item.get("drill_mm", 0)
        if diameter > 0 and "position_mm" in item:
            return drill_from_size(item["position_mm"], diameter, diameter)
        return None
    if "drill_size_mm" not in item or "drill_position_mm" not in item:
        return None
    width, height = item["drill_size_mm"]
    return drill_from_size(item["drill_position_mm"], width, height)


def shape_record(item, role, polygons):
    record = {
        "id": item["id"],
        "role": role,
        "net_name": item.get("net_name"),
        "net_code": item.get("net_code"),
        "polygons": copy_polygons(polygons),
    }
    drill = object_drill(item, role)
    if drill is not None:
        record["drill"] = drill
    return record


def build_scene(geometry):
    if geometry.get("schema_version") != "kicad-geometry-1.0":
        raise ValueError("expected schema_version kicad-geometry-1.0")
    if geometry.get("units") != "mm":
        raise ValueError("expected units mm")
    layers = []
    for layer in geometry["layers"]:
        shapes = [{
            "id": "outline",
            "role": "outline",
            "net_name": None,
            "net_code": None,
            "polygons": copy_polygons(geometry["outline"]),
        }]
        index = layer["index"]
        for pad in geometry["pads"]:
            polygons = [part["polygons"] for part in pad["copper"] if part["layer"] == index]
            if polygons:
                shapes.append(shape_record(pad, "pad", [poly for group in polygons for poly in group]))
        for item in geometry["tracks_and_vias"]:
            role = "via" if item.get("type") == "PCB_VIA" else "track"
            polygons = [part["polygons"] for part in item["copper"] if part["layer"] == index]
            if polygons:
                shapes.append(shape_record(item, role, [poly for group in polygons for poly in group]))
        for item in geometry["copper_graphics"]:
            polygons = [part["polygons"] for part in item["copper"] if part["layer"] == index]
            if polygons:
                shapes.append(shape_record(item, "graphic", [poly for group in polygons for poly in group]))
        layers.append({"index": index, "name": layer["name"], "shapes": shapes})
    return {
        "schema_version": "geometry-scene-1.0",
        "units": "mm",
        "coordinate_system": geometry.get("coordinate_system"),
        "layers": layers,
    }


def net_color(code):
    if not code:
        return "#9aa0a6"
    return PALETTE[(int(code) - 1) % len(PALETTE)]


def ring_path(points):
    head = points[0]
    parts = [f"M {number_text(head[0])} {number_text(head[1])}"]
    parts.extend(f"L {number_text(x)} {number_text(y)}" for x, y in points[1:])
    parts.append("Z")
    return " ".join(parts)


def polygon_path(polygons):
    return " ".join(ring_path(poly["outer"]) + "".join(" " + ring_path(hole) for hole in poly["holes"])
                    for poly in polygons)


def iter_points(scene):
    for layer in scene["layers"]:
        for shape in layer["shapes"]:
            for poly in shape["polygons"]:
                yield from poly["outer"]
                for hole in poly["holes"]:
                    yield from hole
            drill = shape.get("drill")
            if not drill:
                continue
            x, y = drill["center"]
            rx = drill.get("radius", drill.get("radius_x", 0))
            ry = drill.get("radius", drill.get("radius_y", 0))
            yield [x - rx, y - ry]
            yield [x + rx, y + ry]


def render_svg(scene):
    points = list(iter_points(scene))
    if not points:
        raise ValueError("scene has no geometry")
    min_x = min(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_x = max(point[0] for point in points)
    max_y = max(point[1] for point in points)
    board_w = max_x - min_x
    board_h = max_y - min_y
    margin = 4
    title_h = 6
    gap = 8
    layers = scene["layers"]
    width = margin + len(layers) * board_w + max(0, len(layers) - 1) * gap + margin
    height = margin + title_h + board_h + margin
    chunks = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {number_text(width)} {number_text(height)}"',
        f' width="{number_text(width * 8)}" height="{number_text(height * 8)}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for i, layer in enumerate(layers):
        origin_x = margin + i * (board_w + gap)
        text_x = origin_x
        text_y = margin + 4
        chunks.append(f'<text x="{number_text(text_x)}" y="{number_text(text_y)}" '
                      f'font-family="sans-serif" font-size="3.5" fill="#222222">'
                      f'{escape(layer["name"])}</text>')
        tx = origin_x - min_x
        ty = margin + title_h + max_y
        chunks.append(f'<g id="layer-{layer["index"]}" '
                      f'transform="translate({number_text(tx)} {number_text(ty)}) scale(1 -1)">')
        drills = []
        for shape in layer["shapes"]:
            if shape["role"] == "outline":
                fill, stroke, width_mm = "#f5f6f7", "#333333", 0.15
            else:
                fill = net_color(shape.get("net_code"))
                stroke, width_mm = fill, 0.02
            label = shape["id"] if not shape.get("net_name") else f'{shape["id"]} {shape["net_name"]}'
            chunks.append("<g>")
            chunks.append(f"<title>{escape(label)}</title>")
            chunks.append(
                f'<path d="{polygon_path(shape["polygons"])}" fill="{fill}" stroke="{stroke}" '
                f'stroke-width="{number_text(width_mm)}" fill-rule="evenodd"/>'
            )
            chunks.append("</g>")
            if shape.get("drill"):
                drills.append(shape["drill"])
        for drill in drills:
            cx, cy = drill["center"]
            if "radius" in drill:
                chunks.append(
                    f'<circle cx="{number_text(cx)}" cy="{number_text(cy)}" r="{number_text(drill["radius"])}" '
                    'fill="#ffffff" stroke="#333333" stroke-width="0.05"/>'
                )
            else:
                chunks.append(
                    f'<ellipse cx="{number_text(cx)}" cy="{number_text(cy)}" '
                    f'rx="{number_text(drill["radius_x"])}" ry="{number_text(drill["radius_y"])}" '
                    'fill="#ffffff" stroke="#333333" stroke-width="0.05"/>'
                )
        chunks.append("</g>")
    chunks.append("</svg>")
    return "\n".join(chunks) + "\n"


def write_preview(geometry, out_dir):
    scene = build_scene(geometry)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene_path = out_dir / "scene.json"
    svg_path = out_dir / "board.svg"
    scene_path.write_text(json.dumps(scene, indent=2) + "\n", encoding="utf-8")
    svg_path.write_text(render_svg(scene), encoding="utf-8")
    return scene_path, svg_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write a scene JSON and SVG from kicad-geometry JSON")
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
    scene_path, svg_path = write_preview(geometry, args.out)
    print(json.dumps({"scene": str(scene_path), "svg": str(svg_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
