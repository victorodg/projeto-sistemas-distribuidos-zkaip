import base64
from typing import Any, Dict

from models import build_envelope


class Dispatcher:
    """The only component that knows about every message type. Routes each
    received envelope to its handler and keeps the Lamport clock in sync."""

    def __init__(self, peer):
        self.peer = peer
        self._handlers = {
            "HANDSHAKE": self._handle_handshake,
            "HEARTBEAT": self._handle_heartbeat,
            "HEARTBEAT_ACK": self._handle_heartbeat_ack,
            "CREATE_GROUP": self._handle_create_group,
            "ADD_MEMBER": self._handle_add_member,
            "LEAVE_GROUP": self._handle_leave_group,
            "CHAT_MSG": self._handle_chat_msg,
            "MSG_SYNC_REQ": self._handle_msg_sync_req,
            "MSG_SYNC_RES": self._handle_msg_sync_res,
            "FILE_OFFER": self._handle_file_offer,
            "FILE_ACK": self._handle_file_ack,
            "FILE_DATA": self._handle_file_data,
        }

    def handle(self, conn, msg: Dict[str, Any]) -> None:
        self.peer.clock.update(msg.get("clock", 0))
        handler = self._handlers.get(msg.get("type"))
        if handler is None:
            print(f"\r\033[K[warn] unknown message type: {msg.get('type')}")
            return
        handler(conn, msg)

    # -- handshake / liveness ----------------------------------------------

    def _handle_handshake(self, conn, msg: Dict[str, Any]) -> None:
        payload = msg["payload"]
        conn.remote_peer_id = payload["peerId"]
        conn.host = payload.get("host", conn.host)
        conn.port = payload.get("port", conn.port)
        conn.mark_online()
        if not self.peer.register_connection(conn):
            # Another connection to this same peer is already online (both
            # sides dialed each other around the same time) - drop this
            # redundant one and keep the existing one.
            conn.close()
            return

        if not conn.initiator and not conn.handshake_sent:
            conn.send_handshake()

        if self.peer.cli:
            self.peer.cli.notify(f"[info] conectado a {conn.remote_peer_id[:8]} ({conn.host}:{conn.port})")

        for group in self.peer.group_manager.groups_with_member(conn.remote_peer_id):
            last_clock = self.peer.group_manager.last_clock(group.group_id)
            conn.send(build_envelope(self.peer, "MSG_SYNC_REQ", group.group_id,
                                      {"groupId": group.group_id, "lastClock": last_clock}))

    def _handle_heartbeat(self, conn, msg: Dict[str, Any]) -> None:
        conn.send(build_envelope(self.peer, "HEARTBEAT_ACK", None, {}, tick=True))

    def _handle_heartbeat_ack(self, conn, msg: Dict[str, Any]) -> None:
        conn.on_heartbeat_ack()

    # -- groups --------------------------------------------------------------

    def _handle_create_group(self, conn, msg: Dict[str, Any]) -> None:
        payload = msg["payload"]
        group_id = payload["groupId"]
        members = payload["members"]
        self.peer.group_manager.create_or_update_group(group_id, creator_id=msg["from"], members=members)
        if self.peer.cli:
            self.peer.cli.notify(f"[info] grupo {group_id[:8]} criado por {msg['from'][:8]}")
        for m in members:
            if m["peerId"] != self.peer.peer_id:
                self.peer.ensure_connected(m["peerId"], m["host"], m["port"])

    def _handle_add_member(self, conn, msg: Dict[str, Any]) -> None:
        payload = msg["payload"]
        group_id = payload["groupId"]
        new_member = payload.get("newMember")
        all_members = payload.get("allMembers")

        if new_member and new_member["peerId"] != self.peer.peer_id:
            self.peer.ensure_connected(new_member["peerId"], new_member["host"], new_member["port"])

        if all_members is not None:
            self.peer.group_manager.set_members(group_id, all_members)
        elif new_member is not None:
            self.peer.group_manager.add_member(group_id, new_member)

        if self.peer.cli:
            who = new_member["peerId"][:8] if new_member else "?"
            self.peer.cli.notify(f"[info] {who} adicionado ao grupo {group_id[:8]}")

    def _handle_leave_group(self, conn, msg: Dict[str, Any]) -> None:
        group_id = msg["payload"]["groupId"]
        self.peer.group_manager.remove_member(group_id, msg["from"])
        if self.peer.cli:
            self.peer.cli.notify(f"[info] {msg['from'][:8]} saiu do grupo {group_id[:8]}")

    # -- chat + sync -----------------------------------------------------

    def _handle_chat_msg(self, conn, msg: Dict[str, Any]) -> None:
        group_id = msg["groupId"]
        inserted = self.peer.group_manager.add_message(group_id, msg, dedupe=True)
        if inserted and self.peer.cli:
            self.peer.cli.display_message(msg)

    def _handle_msg_sync_req(self, conn, msg: Dict[str, Any]) -> None:
        payload = msg["payload"]
        group_id = payload["groupId"]
        last_clock = payload["lastClock"]
        messages = self.peer.group_manager.get_messages_after(group_id, last_clock)
        conn.send(build_envelope(self.peer, "MSG_SYNC_RES", group_id,
                                  {"groupId": group_id, "messages": messages}))

    def _handle_msg_sync_res(self, conn, msg: Dict[str, Any]) -> None:
        payload = msg["payload"]
        group_id = payload["groupId"]
        messages = sorted(payload["messages"], key=lambda m: m.get("clock", 0))
        for envelope in messages:
            inserted = self.peer.group_manager.add_message(group_id, envelope, dedupe=True)
            if inserted and self.peer.cli:
                self.peer.cli.display_message(envelope, recovered=True)

    # -- file transfer -----------------------------------------------------

    def _handle_file_offer(self, conn, msg: Dict[str, Any]) -> None:
        payload = msg["payload"]
        file_id = payload["fileId"]
        with self.peer.file_transfers_lock:
            self.peer.file_transfers_incoming[file_id] = {
                "fileName": payload["fileName"],
                "fileSize": payload["fileSize"],
                "from_conn": conn,
                "group_id": msg["groupId"],
                "chunks": {},
            }
        if self.peer.cli:
            self.peer.cli.notify(
                f"[info] {msg['from'][:8]} quer enviar o arquivo '{payload['fileName']}' "
                f"({payload['fileSize']} bytes) [fileId {file_id[:8]}]. "
                f"Use /accept {file_id[:8]} ou /reject {file_id[:8]}"
            )

    def _handle_file_ack(self, conn, msg: Dict[str, Any]) -> None:
        payload = msg["payload"]
        file_id = payload["fileId"]
        with self.peer.file_transfers_lock:
            transfer = self.peer.file_transfers_outgoing.get(file_id)
        if not transfer:
            return
        if payload.get("accept"):
            self._send_file_chunks(conn, transfer, file_id)
        elif self.peer.cli:
            self.peer.cli.notify(f"[info] {msg['from'][:8]} recusou o arquivo {file_id[:8]}")

    def _send_file_chunks(self, conn, transfer: Dict[str, Any], file_id: str) -> None:
        import threading

        def worker():
            path = transfer["path"]
            size = path.stat().st_size
            sent = 0
            index = 0
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    sent += len(chunk)
                    is_last = sent >= size
                    conn.send(build_envelope(self.peer, "FILE_DATA", transfer["group_id"], {
                        "fileId": file_id,
                        "chunkIndex": index,
                        "data": base64.b64encode(chunk).decode("ascii"),
                        "last": is_last,
                    }))
                    index += 1
            if self.peer.cli:
                self.peer.cli.notify(f"[info] arquivo {file_id[:8]} enviado para {conn.remote_peer_id[:8]}")

        threading.Thread(target=worker, daemon=True).start()

    def _handle_file_data(self, conn, msg: Dict[str, Any]) -> None:
        payload = msg["payload"]
        file_id = payload["fileId"]
        with self.peer.file_transfers_lock:
            transfer = self.peer.file_transfers_incoming.get(file_id)
            if not transfer:
                return
            transfer["chunks"][payload["chunkIndex"]] = base64.b64decode(payload["data"])
            is_last = payload.get("last")
            if is_last:
                del self.peer.file_transfers_incoming[file_id]

        if is_last:
            self.peer.downloads_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.peer.downloads_dir / transfer["fileName"]
            with open(out_path, "wb") as f:
                for i in sorted(transfer["chunks"].keys()):
                    f.write(transfer["chunks"][i])
            if self.peer.cli:
                self.peer.cli.notify(f"[info] arquivo recebido: {out_path}")
