from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import nbtlib

if TYPE_CHECKING:
    from validator import ValidatorContext


def load_nbt(ctx: ValidatorContext, path: Path):
    key = path.resolve()
    cache = ctx.nbt_cache
    if key in cache:
        entry = cache[key]
        if isinstance(entry, Exception):
            raise entry
        return entry
    try:
        nbt = nbtlib.load(str(path))
    except Exception as e:
        cache[key] = e
        raise
    cache[key] = nbt
    return nbt
