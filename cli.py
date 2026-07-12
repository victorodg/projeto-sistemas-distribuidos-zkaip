import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from connection import ConnectionState
from models import build_envelope


class CLI:
    """User input loop (runs on the main thread) + display of messages
    arriving from network threads."""

    PROMPT = "> "

    def __init__(self, peer):
        self.peer = peer
        self._print_lock = threading.Lock()
        self._running = True

    # -- output --------------------------------------------------------

    def _print_line(self, line: str) -> None:
        with self._print_lock:
            sys.stdout.write("\r\033[K" + line + "\n" + self.PROMPT)
            sys.stdout.flush()

    def notify(self, text: str) -> None:
        self._print_line(text)

    def display_message(self, envelope: Dict[str, Any], recovered: bool = False, self_sent: bool = False) -> None:
        from_id = envelope["from"]
        group_id = envelope["groupId"]
        sent_at = envelope["sentAt"]
        content = envelope["payload"].get("content", "")
        t = time.strftime("%H:%M", time.localtime(sent_at / 1000))
        name = "you" if self_sent else from_id[:8]
        tag = " [recuperada]" if recovered else ""
        group_tag = group_id[:8] if group_id else "?"
        self._print_line(f"[{t}] {name} ({group_tag}){tag}: {content}")

    # -- input loop ------------------------------------------------------

    def run(self) -> None:
        print(f"zKAIP — peer {self.peer.peer_id[:8]} escutando na porta {self.peer.port}")
        print("Comandos: /create <host> <porta> | /add <groupId> <host> <porta> | "
              "/msg <groupId> <texto> | /send <groupId> <caminho> | /groups | "
              "/accept <fileId> | /reject <fileId> | /leave <groupId> | /quit")
        while self._running:
            try:
                line = input(self.PROMPT)
            except (EOFError, KeyboardInterrupt):
                self.cmd_quit()
                break
            line = line.strip()
            if not line:
                continue
            try:
                self._dispatch(line)
            except Exception as e:
                print(f"[error] {e}")

    def _dispatch(self, line: str) -> None:
        parts = line.split(maxsplit=1)
        cmd = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

        if cmd == "/create":
            args = rest.split()
            if len(args) != 2:
                print("uso: /create <host> <porta>")
                return
            self.cmd_create(args[0], args[1])
        elif cmd == "/add":
            args = rest.split(maxsplit=2)
            if len(args) != 3:
                print("uso: /add <groupId> <host> <porta>")
                return
            self.cmd_add(args[0], args[1], args[2])
        elif cmd == "/msg":
            args = rest.split(maxsplit=1)
            if len(args) != 2:
                print("uso: /msg <groupId> <texto>")
                return
            self.cmd_msg(args[0], args[1])
        elif cmd == "/send":
            args = rest.split(maxsplit=1)
            if len(args) != 2:
                print("uso: /send <groupId> <caminho>")
                return
            self.cmd_send(args[0], args[1])
        elif cmd == "/groups":
            self.cmd_groups()
        elif cmd == "/accept":
            if not rest:
                print("uso: /accept <fileId>")
                return
            self.cmd_accept(rest.strip())
        elif cmd == "/reject":
            if not rest:
                print("uso: /reject <fileId>")
                return
            self.cmd_reject(rest.strip())
        elif cmd == "/leave":
            if not rest:
                print("uso: /leave <groupId>")
                return
            self.cmd_leave(rest.strip())
        elif cmd == "/quit":
            self.cmd_quit()
        else:
            print(f"comando desconhecido: {cmd}")

    # -- commands --------------------------------------------------------

    def cmd_create(self, host: str, port_str: str) -> None:
        try:
            port = int(port_str)
        except ValueError:
            print("porta inválida")
            return
        conn = self.peer.connect_blocking(host, port, timeout=5)
        if not conn:
            print(f"falha ao conectar em {host}:{port}")
            return
        group_id = str(uuid.uuid4())
        members = [
            {"peerId": self.peer.peer_id, "host": self.peer.host, "port": self.peer.port},
            {"peerId": conn.remote_peer_id, "host": host, "port": port},
        ]
        self.peer.group_manager.create_or_update_group(group_id, self.peer.peer_id, members)
        conn.send(build_envelope(self.peer, "CREATE_GROUP", None, {"groupId": group_id, "members": members}))
        print(f"grupo criado: {group_id[:8]} (completo: {group_id})")

    def cmd_add(self, group_id_prefix: str, host: str, port_str: str) -> None:
        group = self.peer.group_manager.resolve(group_id_prefix)
        if not group:
            print("grupo não encontrado")
            return
        if group.creator_id != self.peer.peer_id:
            print("apenas o criador do grupo pode adicionar membros")
            return
        try:
            port = int(port_str)
        except ValueError:
            print("porta inválida")
            return
        conn = self.peer.connect_blocking(host, port, timeout=5)
        if not conn:
            print(f"falha ao conectar em {host}:{port}")
            return

        old_members = list(group.members)
        new_member = {"peerId": conn.remote_peer_id, "host": host, "port": port}
        all_members = [m.to_dict() for m in old_members] + [new_member]
        self.peer.group_manager.set_members(group.group_id, all_members)

        conn.send(build_envelope(self.peer, "ADD_MEMBER", group.group_id,
                                  {"groupId": group.group_id, "allMembers": all_members}))

        for m in old_members:
            if m.peer_id == self.peer.peer_id:
                continue
            existing_conn = self.peer.get_connection(m.peer_id)
            envelope = build_envelope(self.peer, "ADD_MEMBER", group.group_id,
                                       {"groupId": group.group_id, "newMember": new_member})
            if existing_conn and existing_conn.state == ConnectionState.ONLINE:
                existing_conn.send(envelope)
            else:
                self.peer.ensure_connected(m.peer_id, m.host, m.port, then_send=envelope)

        print(f"membro {conn.remote_peer_id[:8]} adicionado ao grupo {group.group_id[:8]}")

    def cmd_msg(self, group_id_prefix: str, text: str) -> None:
        group = self.peer.group_manager.resolve(group_id_prefix)
        if not group:
            print("grupo não encontrado")
            return
        envelope = build_envelope(self.peer, "CHAT_MSG", group.group_id, {"content": text})
        self.peer.group_manager.add_message(group.group_id, envelope)
        self.peer.broadcast_to_group(group.group_id, envelope)
        self.display_message(envelope, self_sent=True)

    def cmd_send(self, group_id_prefix: str, path_str: str) -> None:
        group = self.peer.group_manager.resolve(group_id_prefix)
        if not group:
            print("grupo não encontrado")
            return
        path = Path(path_str)
        if not path.is_file():
            print("arquivo não encontrado")
            return
        file_id = str(uuid.uuid4())
        file_size = path.stat().st_size
        with self.peer.file_transfers_lock:
            self.peer.file_transfers_outgoing[file_id] = {
                "path": path,
                "group_id": group.group_id,
            }
        envelope = build_envelope(self.peer, "FILE_OFFER", group.group_id,
                                   {"fileId": file_id, "fileName": path.name, "fileSize": file_size})
        self.peer.broadcast_to_group(group.group_id, envelope)
        print(f"arquivo '{path.name}' ({file_size} bytes) oferecido ao grupo {group.group_id[:8]}")

    def cmd_groups(self) -> None:
        groups = self.peer.group_manager.list_groups()
        if not groups:
            print("nenhum grupo.")
            return
        for g in groups:
            creator_tag = " (você é o criador)" if g.creator_id == self.peer.peer_id else ""
            print(f"grupo {g.group_id[:8]}{creator_tag}")
            for m in g.members:
                if m.peer_id == self.peer.peer_id:
                    print(f"  - {m.peer_id[:8]} (você) @ {m.host}:{m.port} [local]")
                    continue
                conn = self.peer.get_connection(m.peer_id)
                online = conn is not None and conn.state == ConnectionState.ONLINE
                status = "online" if online else "offline"
                print(f"  - {m.peer_id[:8]} @ {m.host}:{m.port} [{status}]")

    def cmd_accept(self, file_id_prefix: str) -> None:
        file_id, transfer = self.peer.resolve_incoming_file(file_id_prefix)
        if not transfer:
            print("oferta de arquivo desconhecida")
            return
        conn = transfer["from_conn"]
        conn.send(build_envelope(self.peer, "FILE_ACK", transfer["group_id"], {"fileId": file_id, "accept": True}))
        print(f"aceitando arquivo {file_id[:8]}...")

    def cmd_reject(self, file_id_prefix: str) -> None:
        file_id, transfer = self.peer.resolve_incoming_file(file_id_prefix)
        if not transfer:
            print("oferta de arquivo desconhecida")
            return
        conn = transfer["from_conn"]
        conn.send(build_envelope(self.peer, "FILE_ACK", transfer["group_id"], {"fileId": file_id, "accept": False}))
        with self.peer.file_transfers_lock:
            self.peer.file_transfers_incoming.pop(file_id, None)
        print(f"arquivo {file_id[:8]} recusado")

    def cmd_leave(self, group_id_prefix: str) -> None:
        group = self.peer.group_manager.resolve(group_id_prefix)
        if not group:
            print("grupo não encontrado")
            return
        envelope = build_envelope(self.peer, "LEAVE_GROUP", group.group_id, {"groupId": group.group_id})
        self.peer.broadcast_to_group(group.group_id, envelope)
        self.peer.group_manager.remove_member(group.group_id, self.peer.peer_id)
        print(f"você saiu do grupo {group.group_id[:8]}")

    def cmd_quit(self) -> None:
        self._running = False
        print("encerrando...")
        self.peer.shutdown()
