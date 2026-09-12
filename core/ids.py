"""Resource-id validity against a registry plus the project's ``extra_ids``."""
from __future__ import annotations


def is_valid(id_: str, valid_set: set[str], extra_ids: set[str]) -> bool:
    """True if ``id_`` is in the registry set, listed in ``extra_ids``, or its
    whole namespace is allowed there as ``<ns>:*``."""
    if id_ in valid_set or id_ in extra_ids:
        return True
    ns = id_.split(":", 1)[0]
    return f"{ns}:*" in extra_ids


def non_minecraft(ids: set[str]) -> set[str]:
    """The modded ids of a set (everything not under ``minecraft:``)."""
    return {i for i in ids if not i.startswith("minecraft:")}
