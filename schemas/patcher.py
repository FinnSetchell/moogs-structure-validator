import copy


def apply_msl(schema: dict) -> dict:
    s = copy.deepcopy(schema)
    element = (
        s.get("properties", {})
        .get("elements", {})
        .get("items", {})
        .get("properties", {})
        .get("element", {})
    )
    element.setdefault("properties", {})["locations"] = {"type": "object"}
    return s
