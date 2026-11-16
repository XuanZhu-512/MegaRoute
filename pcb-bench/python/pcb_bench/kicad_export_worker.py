"""Run with KiCad's own Python. All copper contours come from pcbnew, not a text parser."""
import argparse
import json
import math
import sys
from pathlib import Path


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

    outline = p.SHAPE_POLY_SET()
    major = int(actual.split('.')[0])
    if major >= 10:
        valid = board.GetBoardPolygonOutlines(outline, False)
    else:
        valid = board.GetBoardPolygonOutlines(outline)
    if not valid or not outline.OutlineCount():
        raise ValueError("invalid or missing board outline (inference disabled)")

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
                         "copper": copper(pad)})

    tracks = []
    for track in board.GetTracks():
        uid = identity(track)
        item = {"id": uid, "type": track.GetClass(), "net_code": track.GetNetCode(),
                "net_name": track.GetNetname(), "copper": copper(track)}
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
    for item in all_graphics:
        if any(item.IsOnLayer(z) for z in layers):
            if not isinstance(item, p.PCB_SHAPE):
                raise ValueError(f"unsupported copper graphic: {item.GetClass()}")
            graphics.append({"id": identity(item), "type": item.GetClass(), "copper": copper(item)})
        else:
            ignored.append({"uuid": item.m_Uuid.AsString(), "type": item.GetClass(),
                            "reason": "non_copper_graphic_preserved_in_source"})
    warnings.append("Copper contours are conservative outer polygon approximations, not exact analytic curves.")
    warnings.append("Pad drill geometry is separate; copper polygons are outer envelopes, not hole-subtracted solids.")
    warnings.append("Raw project rules are preserved; per-object effective design-rule resolution is not implemented.")
    geometry = {"schema_version": "kicad-geometry-1.0", "units": "mm",
                "coordinate_system": "KiCad board-global XY; no Y inversion",
                "layers": [{"index": i, "kicad_id": z, "name": board.GetLayerName(z)}
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
