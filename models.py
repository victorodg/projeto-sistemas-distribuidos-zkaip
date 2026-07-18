import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class MemberInfo:
    peer_id: str
    host: str
    port: int
    username: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"peerId": self.peer_id, "host": self.host, "port": self.port, "username": self.username}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "MemberInfo":
        return MemberInfo(
            peer_id=d["peerId"], host=d["host"], port=d["port"],
            username=d.get("username") or d["peerId"][:8],
        )


@dataclass
class Group:
    group_id: str
    creator_id: str
    name: str = ""
    members: List[MemberInfo] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "groupId": self.group_id,
            "creatorId": self.creator_id,
            "name": self.name,
            "members": [m.to_dict() for m in self.members],
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Group":
        return Group(
            group_id=d["groupId"],
            creator_id=d["creatorId"],
            name=d.get("name") or d["groupId"][:8],
            members=[MemberInfo.from_dict(m) for m in d.get("members", [])],
        )

    def member_ids(self) -> List[str]:
        return [m.peer_id for m in self.members]

    def get_member(self, peer_id: str) -> Optional[MemberInfo]:
        for m in self.members:
            if m.peer_id == peer_id:
                return m
        return None


@dataclass
class Message:
    """Represents a full CHAT_MSG envelope (kept mostly as a plain dict in
    practice, this dataclass documents the shape used across the app)."""

    type: str
    from_id: str
    group_id: Optional[str]
    clock: int
    sent_at: int
    msg_id: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "from": self.from_id,
            "groupId": self.group_id,
            "clock": self.clock,
            "sentAt": self.sent_at,
            "msgId": self.msg_id,
            "payload": self.payload,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Message":
        return Message(
            type=d["type"],
            from_id=d["from"],
            group_id=d.get("groupId"),
            clock=d["clock"],
            sent_at=d["sentAt"],
            msg_id=d["msgId"],
            payload=d.get("payload", {}),
        )


def build_envelope(peer, msg_type: str, group_id: Optional[str], payload: Dict[str, Any], tick: bool = True) -> Dict[str, Any]:
    """Builds a message envelope, ticking the local Lamport clock."""
    clock = peer.clock.tick() if tick else peer.clock.value
    return {
        "type": msg_type,
        "from": peer.peer_id,
        "groupId": group_id,
        "clock": clock,
        "sentAt": now_ms(),
        "msgId": str(uuid.uuid4()),
        "payload": payload,
    }
