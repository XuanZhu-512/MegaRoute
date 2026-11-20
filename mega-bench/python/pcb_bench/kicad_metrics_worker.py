"""Pad groups and copper lengths from one board. Run with KiCad's Python."""
import argparse
import json
import sys
from pathlib import Path


def board_stats(p, board_path, expected_version):
    actual = p.Version()
    if actual != expected_version:
        raise ValueError(f"KiCad version mismatch: expected {expected_version}, got {actual}")
    board = p.LoadBoard(str(board_path))
    if board is None:
        raise ValueError("KiCad could not load board")
    board.BuildConnectivity()
    connectivity = board.GetConnectivity()
    visited = set()
    groups = {}
    pad_ids = []
    pad_keys = []
    electrical = []
    for footprint in board.GetFootprints():
        reference = footprint.GetReference()
        for pad in footprint.Pads():
            pad_ids.append(pad.m_Uuid.AsString())
            # Legacy KiCad files have no pad uuids. KiCad assigns new ones on every
            # load, so reference plus pad number is the identity that survives saving.
            pad_keys.append(f"{reference}:{pad.GetNumber()}")
            if pad.GetNetCode() != 0:
                electrical.append(pad)
    for pad in electrical:
        if pad.m_Uuid.AsString() in visited:
            continue
        groups[pad.GetNetname()] = groups.get(pad.GetNetname(), 0) + 1
        pending = [pad]
        while pending:
            item = pending.pop()
            uid = item.m_Uuid.AsString()
            if uid in visited:
                continue
            visited.add(uid)
            for track in connectivity.GetConnectedTracks(item):
                pending.append(track)
            # Pads can touch other pads directly without an intervening track.
            # The old PAD guard split those components and inflated the baseline.
            for other in connectivity.GetConnectedPads(item):
                if other.GetNetCode() == pad.GetNetCode():
                    pending.append(other)
    copper = []
    for item in board.GetTracks():
        kind = "via" if isinstance(item, p.PCB_VIA) else "segment"
        length = 0.0 if kind == "via" else float(p.ToMM(item.GetLength()))
        copper.append({"uuid": item.m_Uuid.AsString(), "kind": kind, "length_mm": length})
    return {"pad_groups": groups, "pad_uuids": pad_ids, "pad_keys": pad_keys, "copper": copper}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    try:
        import pcbnew
        print(json.dumps(board_stats(pcbnew, args.board, args.expected_version)))
        return 0
    except Exception as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
