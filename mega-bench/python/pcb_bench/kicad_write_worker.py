"""Append router copper to a KiCad board copy. Run with KiCad's Python."""
import argparse
import json
import sys
from pathlib import Path


def append_routes(p, board_path, out_path, routes, layers, expected_version):
    actual = p.Version()
    if actual != expected_version:
        raise ValueError(f"KiCad version mismatch: expected {expected_version}, got {actual}")
    ordered = sorted(layers, key=lambda item: item["index"])
    layer_of = {item["index"]: item["kicad_id"] for item in ordered}
    if len(layer_of) != len(ordered):
        raise ValueError("duplicate layer index")
    board = p.LoadBoard(str(board_path))
    if board is None:
        raise ValueError("KiCad could not load board")

    def pad_ids():
        return [pad.m_Uuid.AsString() for fp in board.GetFootprints() for pad in fp.Pads()]

    def track_ids():
        return [item.m_Uuid.AsString() for item in board.GetTracks()]

    original_pads = pad_ids()
    original_tracks = track_ids()
    copper = routes["copper"]
    added = []
    seen_vias = set()
    duplicates = 0
    for existing in board.GetTracks():
        if isinstance(existing, p.PCB_VIA):
            pos = existing.GetPosition()
            seen_vias.add((existing.GetNetCode(), pos.x, pos.y, existing.GetWidth(),
                           existing.GetDrillValue(), existing.TopLayer(), existing.BottomLayer(),
                           existing.GetViaType()))
    for item in copper:
        net = board.FindNet(item["net"])
        if net is None or net.GetNetCode() == 0:
            raise ValueError(f"unknown net: {item['net']}")
        kind = item["kind"]
        if kind == "segment":
            if len(item["layers"]) != 1 or item["layers"][0] not in layer_of:
                raise ValueError(f"segment {item['id']} must use one mapped layer")
            track = p.PCB_TRACK(board)
            track.SetStart(p.VECTOR2I(p.FromMM(item["a"][0]), p.FromMM(item["a"][1])))
            track.SetEnd(p.VECTOR2I(p.FromMM(item["b"][0]), p.FromMM(item["b"][1])))
            track.SetWidth(p.FromMM(item["width"]))
            track.SetLayer(layer_of[item["layers"][0]])
            track.SetNet(net)
        elif kind == "via":
            key = (net.GetNetCode(), p.FromMM(item["center"][0]), p.FromMM(item["center"][1]),
                   p.FromMM(2 * item["radius"]), p.FromMM(item["drill"]),
                   ordered[0]["kicad_id"], ordered[-1]["kicad_id"], p.VIATYPE_THROUGH)
            if key in seen_vias:
                duplicates += 1
                continue
            seen_vias.add(key)
            track = p.PCB_VIA(board)
            track.SetPosition(p.VECTOR2I(p.FromMM(item["center"][0]), p.FromMM(item["center"][1])))
            track.SetWidth(p.FromMM(2 * item["radius"]))
            track.SetDrill(p.FromMM(item["drill"]))
            track.SetViaType(p.VIATYPE_THROUGH)
            track.SetLayerPair(ordered[0]["kicad_id"], ordered[-1]["kicad_id"])
            track.SetNet(net)
        else:
            raise ValueError(f"unsupported route kind: {kind}")
        board.Add(track)
        added.append(track.m_Uuid.AsString())
    if set(original_pads) - set(pad_ids()):
        raise RuntimeError("writeback removed an existing pad")
    remaining = track_ids()
    if set(original_tracks) - set(remaining) or len(remaining) < len(original_tracks):
        raise RuntimeError("writeback removed an existing track")
    if any(uid in original_tracks or uid in original_pads for uid in added):
        raise RuntimeError("new route reused an existing UUID")
    board.Save(str(out_path))
    return {"added": len(added), "uuids": added, "original_tracks": len(original_tracks),
            "original_pads": len(original_pads), "duplicate_vias_skipped": duplicates}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--routes", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    try:
        import pcbnew
        routes = json.loads(args.routes.read_text(encoding="utf-8"))
        geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
        report = append_routes(pcbnew, args.board, args.out, routes, geometry["layers"],
                               args.expected_version)
        print(json.dumps(report))
        return 0
    except Exception as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
