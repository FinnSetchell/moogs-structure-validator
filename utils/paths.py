from pathlib import Path

_PLURAL_FORMS = {
    "structure":       "structures",
    "loot_table":      "loot_tables",
    "advancement":     "advancements",
    "recipe":          "recipes",
    "predicate":       "predicates",
    "item_modifier":   "item_modifiers",
    "function":        "functions",
    "tags/item":       "tags/items",
    "tags/block":      "tags/blocks",
    "tags/entity_type":"tags/entity_types",
    "tags/fluid":      "tags/fluids",
    "tags/game_event": "tags/game_events",
    "tags/function":   "tags/functions",
}


def data_dir(namespace_root: Path, name: str) -> Path:
    singular = namespace_root / name
    if singular.exists():
        return singular
    plural = _PLURAL_FORMS.get(name)
    if plural:
        plural_path = namespace_root / plural
        if plural_path.exists():
            return plural_path
    # neither form found; return singular and let the caller handle a missing dir
    return singular
