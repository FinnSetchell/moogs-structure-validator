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


def all_data_dirs(namespace_root: Path, name: str) -> list[Path]:
    """Return every existing form of a data directory (singular and plural).
    Handles projects where both forms coexist with files split across them."""
    dirs: list[Path] = []
    singular = namespace_root / name
    if singular.exists():
        dirs.append(singular)
    plural = _PLURAL_FORMS.get(name)
    if plural:
        plural_path = namespace_root / plural
        if plural_path.exists() and plural_path not in dirs:
            dirs.append(plural_path)
    return dirs if dirs else [singular]
