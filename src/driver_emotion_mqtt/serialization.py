from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def to_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]

    item = getattr(value, "item", None)
    if callable(item):
        return to_json_value(item())

    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return to_json_value(tolist())

    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(
            to_json_value(data),
            stream,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
