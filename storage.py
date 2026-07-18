import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def _read_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# peer.json
# ---------------------------------------------------------------------------

def load_peer(data_dir: Path) -> Optional[Dict[str, Any]]:
    return _read_json(data_dir / "peer.json")


def save_peer(data_dir: Path, peer_id: str, port: int, username: str) -> None:
    _atomic_write_json(data_dir / "peer.json", {"peerId": peer_id, "port": port, "username": username})


# ---------------------------------------------------------------------------
# groups.json
# ---------------------------------------------------------------------------

def load_groups(data_dir: Path) -> List[Dict[str, Any]]:
    return _read_json(data_dir / "groups.json") or []


def save_groups(data_dir: Path, groups: List[Dict[str, Any]]) -> None:
    _atomic_write_json(data_dir / "groups.json", groups)


# ---------------------------------------------------------------------------
# messages/{groupId}.json
# ---------------------------------------------------------------------------

def _messages_path(data_dir: Path, group_id: str) -> Path:
    return data_dir / "messages" / f"{group_id}.json"


def load_messages(data_dir: Path, group_id: str) -> List[Dict[str, Any]]:
    return _read_json(_messages_path(data_dir, group_id)) or []


def save_messages(data_dir: Path, group_id: str, messages: List[Dict[str, Any]]) -> None:
    _atomic_write_json(_messages_path(data_dir, group_id), messages)
