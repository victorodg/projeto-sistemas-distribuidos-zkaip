import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import storage
from models import Group, MemberInfo


class GroupManager:
    """Owns groups, membership and message history. Never touches sockets."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._lock = threading.RLock()
        self.groups: Dict[str, Group] = {}
        self.messages: Dict[str, List[Dict[str, Any]]] = {}

    # -- persistence ---------------------------------------------------

    def load(self) -> None:
        with self._lock:
            for raw in storage.load_groups(self.data_dir):
                group = Group.from_dict(raw)
                self.groups[group.group_id] = group
                self.messages[group.group_id] = storage.load_messages(self.data_dir, group.group_id)

    def _persist_groups(self) -> None:
        storage.save_groups(self.data_dir, [g.to_dict() for g in self.groups.values()])

    # -- groups ----------------------------------------------------------

    def list_groups(self) -> List[Group]:
        with self._lock:
            return list(self.groups.values())

    def get(self, group_id: str) -> Optional[Group]:
        with self._lock:
            return self.groups.get(group_id)

    def resolve(self, group_id_or_prefix: str) -> Optional[Group]:
        """Resolves a full groupId or an 8-char prefix to a Group."""
        with self._lock:
            if group_id_or_prefix in self.groups:
                return self.groups[group_id_or_prefix]
            matches = [g for g in self.groups.values() if g.group_id.startswith(group_id_or_prefix)]
            return matches[0] if len(matches) == 1 else None

    def create_or_update_group(self, group_id: str, creator_id: str, members: List[Dict[str, Any]]) -> Group:
        with self._lock:
            group = Group(group_id=group_id, creator_id=creator_id, members=[MemberInfo.from_dict(m) for m in members])
            self.groups[group_id] = group
            self.messages.setdefault(group_id, [])
            self._persist_groups()
            return group

    def set_members(self, group_id: str, members: List[Dict[str, Any]]) -> Optional[Group]:
        with self._lock:
            group = self.groups.get(group_id)
            if not group:
                return None
            group.members = [MemberInfo.from_dict(m) for m in members]
            self._persist_groups()
            return group

    def add_member(self, group_id: str, member: Dict[str, Any]) -> Optional[Group]:
        with self._lock:
            group = self.groups.get(group_id)
            if not group:
                return None
            if not group.get_member(member["peerId"]):
                group.members.append(MemberInfo.from_dict(member))
                self._persist_groups()
            return group

    def remove_member(self, group_id: str, peer_id: str) -> Optional[Group]:
        with self._lock:
            group = self.groups.get(group_id)
            if not group:
                return None
            group.members = [m for m in group.members if m.peer_id != peer_id]
            self._persist_groups()
            return group

    def is_member(self, group_id: str, peer_id: str) -> bool:
        with self._lock:
            group = self.groups.get(group_id)
            return bool(group and group.get_member(peer_id))

    def groups_with_member(self, peer_id: str) -> List[Group]:
        with self._lock:
            return [g for g in self.groups.values() if g.get_member(peer_id)]

    # -- messages ----------------------------------------------------------

    def add_message(self, group_id: str, envelope: Dict[str, Any], dedupe: bool = False) -> bool:
        """Appends a message envelope, keeping history sorted by clock.
        Returns True if the message was actually inserted (False if it was a
        duplicate and dedupe=True)."""
        with self._lock:
            history = self.messages.setdefault(group_id, [])
            if dedupe and any(m.get("msgId") == envelope.get("msgId") for m in history):
                return False
            history.append(envelope)
            history.sort(key=lambda m: m.get("clock", 0))
            storage.save_messages(self.data_dir, group_id, history)
            return True

    def get_messages(self, group_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.messages.get(group_id, []))

    def get_messages_after(self, group_id: str, last_clock: int) -> List[Dict[str, Any]]:
        with self._lock:
            history = self.messages.get(group_id, [])
            return [m for m in history if m.get("clock", 0) > last_clock]

    def last_clock(self, group_id: str) -> int:
        with self._lock:
            history = self.messages.get(group_id, [])
            return max((m.get("clock", 0) for m in history), default=0)
