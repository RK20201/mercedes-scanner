import json
import os
from datetime import datetime, timezone, timedelta


def load_seen(path: str = "data/seen_listings.json") -> dict:
    if not os.path.exists(path):
        return {"seen_ids": {}, "last_run": None, "total_seen": 0}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen_data: dict, path: str = "data/seen_listings.json") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen_data, f, ensure_ascii=False, indent=2)


def filter_new(listings: list, seen_data: dict) -> list:
    seen_ids = seen_data.get("seen_ids", {})
    return [l for l in listings if l["id"] not in seen_ids]


def mark_seen(listings: list, seen_data: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    seen_ids = seen_data.get("seen_ids", {})
    for listing in listings:
        if listing["id"] not in seen_ids:
            seen_ids[listing["id"]] = now
    seen_data["seen_ids"] = seen_ids
    seen_data["last_run"] = now
    seen_data["total_seen"] = len(seen_ids)
    return seen_data


def prune_old_ids(seen_data: dict, days: int = 60) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    seen_ids = seen_data.get("seen_ids", {})
    pruned = {
        k: v for k, v in seen_ids.items()
        if datetime.fromisoformat(v) > cutoff
    }
    seen_data["seen_ids"] = pruned
    return seen_data
