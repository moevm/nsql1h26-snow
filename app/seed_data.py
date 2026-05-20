from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

@lru_cache(maxsize=None)
def _load_json(filename: str) -> Any:
    path = DATA_DIR / filename
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_seed_json(filename: str) -> Any:
    return copy.deepcopy(_load_json(filename))

def get_seed_map_objects() -> list[dict]:
    return load_seed_json("seed_map_objects.json")

def get_seed_graph() -> dict[str, list[dict]]:
    return load_seed_json("seed_graph.json")

def get_seed_routes() -> list[dict]:
    return load_seed_json("seed_routes.json")

def get_seed_simulations() -> list[dict]:
    return load_seed_json("seed_simulations.json")
