"""Run with KiCad's own Python. All copper contours come from pcbnew, not a text parser."""
import argparse
import json
import math
import sys
from pathlib import Path


def board_outlines(p, board, error_mm):
    """Recover overlapping circular cutouts without discarding removed material.

    Only retry when the remaining native outline is valid. Circle disks must be
    wholly inside it; Boolean subtraction unions duplicate/intersecting cutouts.
    The source board and its exact circular primitives remain unchanged.
    """
    def native(outline):
        if int(p.Version().split('.')[0]) >= 10:
            return board.GetBoardPolygonOutlines(outline, False)
        return board.GetBoardPolygonOutlines(outline)

    outline = p.SHAPE_POLY_SET()
    if native(outline) and outline.OutlineCount():
        return outline, False
    circles = [x for x in board.GetDrawings()
               if x.GetLayer() == p.Edge_Cuts and x.GetShape() == p.SHAPE_T_CIRCLE]
    if not circles:
        raise ValueError("invalid or missing board outline (inference disabled)")
    try:
        for circle in circles:
            board.Remove(circle)
        outer = p.SHAPE_POLY_SET()
        if not native(outer) or outer.OutlineCount() != 1:
            raise ValueError("invalid non-circular board outline")
        disks = p.SHAPE_POLY_SET()
        for circle in circles:
            center = circle.GetCenter()
            radius = circle.GetRadius()
            if radius <= 0:
                raise ValueError("invalid circular cutout radius")
            tolerance = min(p.FromMM(error_mm), radius / 2)
            count = max(16, math.ceil(math.pi / math.acos(1 - tolerance / radius)))
            disk = p.SHAPE_POLY_SET()
            disk.NewOutline()
            for i in range(count):
                angle = 2 * math.pi * i / count
                disk.Append(round(center.x + radius * math.cos(angle)),
                            round(center.y + radius * math.sin(angle)))
            outside = disk.CloneDropTriangulation()
            outside.BooleanSubtract(outer)
            if outside.OutlineCount():
                raise ValueError("circular cutout is not inside board outline")
            disks.BooleanAdd(disk)
        outer.BooleanSubtract(disks)
        if outer.OutlineCount() != 1:
            raise ValueError("circular cutouts split board outline")
        return outer, True
    finally:
        for circle in circles:
            board.Add(circle)


def export_geometry(p, board_path, expected_version, error_mm):
    actual = p.Version()
    if actual != expected_version:
        raise ValueError(f"KiCad version mismatch: expected {expected_version}, got {actual}")
    if not math.isfinite(error_mm) or not 0.000001 <= error_mm <= 0.1:
        raise ValueError("max_error_mm must be between 0.000001 and 0.1")
    board = p.LoadBoard(str(board_path))
    if board is None:
        raise ValueError("KiCad could not load board")
    layers = list(board.GetEnabledLayers().CuStack())
    layer_index = {z: i for i, z in enumerate(layers)}
    max_error = p.FromMM(error_mm)
    mappings = {}
    ignored = []
    warnings = []

    def point(v):
        return [p.ToMM(v.x), p.ToMM(v.y)]

    def ring(chain):
        if chain.ArcCount():
            raise ValueError("unexpected retained arc in polygon output")
        points = [point(chain.CPoint(i)) for i in range(chain.PointCount())]
        if len(points) > 1 and points[0] == points[-1]:
            points.pop()
        if len(points) < 3:
            raise ValueError("degenerate polygon returned by KiCad")
        return points

    def polygons(poly):
        return [{"outer": ring(poly.COutline(i)),
                 "holes": [ring(poly.CHole(i, h)) for h in range(poly.HoleCount(i))]}
                for i in range(poly.OutlineCount())]

    def identity(item):
        uid = item.m_Uuid.AsString()
        if uid in mappings:
            raise ValueError(f"duplicate KiCad UUID: {uid}")
        mappings[uid] = {"kicad_uuid": uid, "type": item.GetClass()}
        return uid

    def copper(item):
        result = []
        for z in layers:
            if item.IsOnLayer(z):
                poly = p.SHAPE_POLY_SET()
                item.TransformShapeToPolygon(poly, z, 0, max_error, p.ERROR_OUTSIDE)
                record = {"layer": layer_index[z], "polygons": polygons(poly)}
                if isinstance(item, p.PAD):
                    record.update(shape_code=int(item.GetShape(z)), size_mm=point(item.GetSize(z)))
                result.append(record)
        return result

    def local_clearance(item, footprint=None):
        value = item.GetLocalClearance()
        source = "pad" if footprint is not None else "item"
        # None and zero differ: zero on a pad masks its footprint override.
        if value is None and footprint is not None:
            value = footprint.GetLocalClearance()
            source = "footprint"
        return {"local_clearance_mm": None if value is None else p.ToMM(value),
                "local_clearance_source": None if value is None else source}

    def text_copper(item):
        if hasattr(item, "IsKnockout") and item.IsKnockout():
            raise ValueError("unsupported_feature: knockout copper text")
        # TransformShapeToPolygon returns a bounding hull for text. Use the same
        # stroke/triangle geometry as KiCad's effective text shape instead.
        shape = item.GetEffectiveTextShape(True)
        primitives = []
        for sub in shape.GetSubshapes():
            if sub.Type() == p.SH_SEGMENT:
                stroke = p.Cast_to_SHAPE_SEGMENT(sub)
                seg = stroke.GetSeg()
                primitives.append({"kind": "segment", "a": point(seg.A), "b": point(seg.B),
                                   "width": p.ToMM(stroke.GetWidth())})
            elif sub.Type() == p.SH_SIMPLE:
                triangle = p.Cast_to_SHAPE_SIMPLE(sub)
                points = [point(triangle.CPoint(i)) for i in range(triangle.PointCount())]
                primitives.append({"kind": "polygon", "points": points, "center": points[0]})
            else:
                raise ValueError(f"unsupported_feature: copper text primitive {sub.Type()}")
        return [{"layer": layer_index[z], "polygons": [], "primitives": primitives}
                for z in layers if item.IsOnLayer(z)]

    outline, normalized_cutouts = board_outlines(p, board, error_mm)
    if normalized_cutouts:
        warnings.append("overlapping circular Edge.Cuts normalized as cutout union")

    pads = []
    attributes = {p.PAD_ATTRIB_PTH: "plated_through_hole", p.PAD_ATTRIB_NPTH: "non_plated_hole",
                  p.PAD_ATTRIB_SMD: "smd", p.PAD_ATTRIB_CONN: "connector"}
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            uid = identity(pad)
            attr = pad.GetAttribute()
            if attr not in attributes:
                raise ValueError(f"unsupported pad attribute: {attr}")
            pads.append({"id": uid, "footprint_uuid": footprint.m_Uuid.AsString(),
                         "reference": footprint.GetReference(), "number": pad.GetNumber(),
                         "net_code": pad.GetNetCode(), "net_name": pad.GetNetname(),
                         "position_mm": point(pad.GetPosition()),
                         "rotation_degrees": pad.GetOrientationDegrees(),
                         "attribute": attributes[attr],
                         "plated": attr == p.PAD_ATTRIB_PTH,
                         "drill_size_mm": point(pad.GetDrillSize()),
                         "drill_shape_code": int(pad.GetDrillShape()),
                         "drill_position_mm": point(pad.GetPosition()),
                         "copper": copper(pad), **local_clearance(pad, footprint)})

    tracks = []
    for track in board.GetTracks():
        uid = identity(track)
        item = {"id": uid, "type": track.GetClass(), "net_code": track.GetNetCode(),
                "net_name": track.GetNetname(), "copper": copper(track), **local_clearance(track)}
        if isinstance(track, p.PCB_VIA):
            item.update(position_mm=point(track.GetPosition()), drill_mm=p.ToMM(track.GetDrillValue()),
                        via_type_code=int(track.GetViaType()))
        else:
            item.update(start_mm=point(track.GetStart()), end_mm=point(track.GetEnd()),
                        width_mm=p.ToMM(track.GetWidth()))
            if isinstance(track, p.PCB_ARC):
                item['mid_mm'] = point(track.GetMid())
        tracks.append(item)

    # Rule areas and zone refill involve rule semantics beyond a geometric outline.
    # Refuse them until implemented rather than silently treating them as solid copper.
    if list(board.Zones()) or any(list(fp.Zones()) for fp in board.GetFootprints()):
        raise ValueError("unsupported_feature: zones/rule areas require explicit fill/rule export")
    graphics = []
    all_graphics = list(board.GetDrawings())
    for fp in board.GetFootprints():
        all_graphics.extend(fp.GraphicalItems())
        all_graphics.extend(fp.GetFields())
    for item in all_graphics:
        if any(item.IsOnLayer(z) for z in layers):
            item_type = item.GetClass()
            is_text = isinstance(item, p.PCB_TEXT)
            if is_text and not item.IsVisible():
                ignored.append({"uuid": item.m_Uuid.AsString(), "type": item_type,
                                "reason": "invisible_copper_text"})
                continue
            if not is_text and not isinstance(item, p.PCB_SHAPE):
                raise ValueError(f"unsupported copper graphic: {item_type}")
            graphics.append({"id": identity(item), "type": item_type,
                             "copper": text_copper(item) if is_text else copper(item)})
        else:
            ignored.append({"uuid": item.m_Uuid.AsString(), "type": item.GetClass(),
                            "reason": "non_copper_graphic_preserved_in_source"})
    warnings.append("Copper contours are conservative outer polygon approximations, not exact analytic curves.")
    warnings.append("Pad drill geometry is separate; copper polygons are outer envelopes, not hole-subtracted solids.")
    warnings.append("Pad/footprint local clearance overrides are exported; arbitrary custom design rules are not resolved.")
    geometry = {"schema_version": "kicad-geometry-1.0", "units": "mm",
                "coordinate_system": "KiCad board-global XY; no Y inversion",
                # Writers need file-format layer identifiers, not user display aliases.
                "layers": [{"index": i, "kicad_id": z, "name": p.BOARD.GetStandardLayerName(z)}
                           for i, z in enumerate(layers)],
                "outline": polygons(outline),
                "nets": [{"code": n.GetNetCode(), "name": n.GetNetname()}
                         for n in board.GetNetInfo().NetsByNetcode().values()],
                "pads": pads, "tracks_and_vias": tracks, "copper_graphics": graphics}
    report = {"schema_version": "1.0", "status": "geometry_exported",
              "kicad_version": actual, "pcbnew_module": str(p.__file__),
              "polygonization": {"max_error_mm": error_mm, "clearance_mm": 0,
                                 "copper_error_location": "outside",
                                 "board_outline": "KiCad GetBoardPolygonOutlines defaults"},
              "counts": {"layers": len(layers), "nets": sum(n['code'] != 0 for n in geometry['nets']),
                         "pads": len(pads), "tracks_and_vias": len(tracks)},
              "cpp_geometry_v1_compatible": False,
              "evaluation_performed": False, "warnings": warnings,
              "ignored_non_copper_graphics": ignored}
    return geometry, {"schema_version": "1.0", "objects": mappings,
                      "layers": geometry['layers'], "nets": geometry['nets']}, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--board', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--max-error-mm', type=float, default=.005)
    args = parser.parse_args()
    try:
        import pcbnew
        geometry, mapping, report = export_geometry(pcbnew, args.board, args.expected_version, args.max_error_mm)
        for filename, data in [('geometry.json', geometry), ('source_map.json', mapping),
                               ('conversion_report.json', report)]:
            (args.out/filename).write_text(json.dumps(data, indent=2), encoding='utf-8')
        return 0
    except Exception as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
