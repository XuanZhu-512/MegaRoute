"""Resolve KiCad 9 net class per net from project rules (patterns + explicit lists)."""
import fnmatch


def kicad_pattern_match(pattern: str, name: str) -> bool:
    return fnmatch.fnmatchcase(name, pattern)


def resolve_net_classes(net_settings: dict, net_names: list[str]) -> dict[str, str]:
    classes_list = net_settings.get("classes") or []
    classes = {item["name"] for item in classes_list if item.get("name")}
    if "Default" not in classes:
        raise ValueError("project rules have no Default net class")

    explicit: dict[str, str] = {}
    for item in classes_list:
        class_name = item.get("name")
        if not class_name:
            continue
        for net in item.get("nets") or []:
            if net:
                explicit[net] = class_name

    assignments = net_settings.get("netclass_assignments")
    if assignments is None:
        assignments = {}
    if not isinstance(assignments, dict):
        raise ValueError("invalid netclass_assignments")

    patterns: list[tuple[str, str]] = []
    for entry in net_settings.get("netclass_patterns") or []:
        if not isinstance(entry, dict):
            continue
        pattern = entry.get("pattern")
        class_name = entry.get("netclass")
        if not (pattern and class_name):
            continue
        if class_name not in classes:
            raise ValueError(f"netclass pattern {pattern!r} references undefined class {class_name!r}")
        patterns.append((pattern, class_name))

    resolved: dict[str, str] = {}
    for name in net_names:
        if not name:
            continue
        if name in explicit:
            resolved[name] = explicit[name]
            continue
        if name in assignments:
            resolved[name] = assignments[name]
            continue
        matched = None
        for pattern, class_name in patterns:
            if kicad_pattern_match(pattern, name):
                matched = class_name
                break
        resolved[name] = matched if matched is not None else "Default"
    return resolved