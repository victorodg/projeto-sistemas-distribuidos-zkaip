import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from connection import ConnectionState
from models import build_envelope

# Número de mensagens no histórico do grupo selecionado
HISTORY_ON_CHOOSE = 20


class CLI:
    """Loop principal de entrada do usuário (executado na thread principal)
    e exibição das mensagens recebidas pelas threads de rede.

    Mantém no máximo um grupo ativo (definido por /choose). Os
    comandos /msg e /send atuam implicitamente sobre esse grupo,
    como se fossem enviados /msg [nomeGrupo] e /send [nomeGrupo].
    Mensagens de outros grupos continuam sendo exibidas em tempo real,
    identificadas pelo nome do grupo para evitar confusão com a conversa ativa.
    """

    def __init__(self, peer):
        self.peer = peer
        self._print_lock = threading.Lock()
        self._running = True
        self.current_group_id: Optional[str] = None

    def _current_prompt(self) -> str:
        if self.current_group_id:
            group = self.peer.group_manager.get(self.current_group_id)
            if group:
                return f"[{group.name}]> "
        return "> "

    def _print_line(self, line: str) -> None:
        with self._print_lock:
            sys.stdout.write("\r\033[K" + line + "\n" + self._current_prompt())
            sys.stdout.flush()

    def notify(self, text: str) -> None:
        self._print_line(text)

    def display_message(self, envelope: Dict[str, Any], recovered: bool = False, self_sent: bool = False) -> None:
        from_id = envelope["from"]
        group_id = envelope["groupId"]
        sent_at = envelope["sentAt"]
        content = envelope["payload"].get("content", "")
        t = time.strftime("%H:%M", time.localtime(sent_at / 1000))
        name = "você" if self_sent else self.peer.display_name(from_id)
        tag = " [recuperada]" if recovered else ""

        if group_id == self.current_group_id:
            self._print_line(f"[{t}] {name}{tag}: {content}")
        else:
            group = self.peer.group_manager.get(group_id)
            group_name = group.name if group else "?"
            self._print_line(f"[{t}] ({group_name}) {name}{tag}: {content}")

    # input loop

    def run(self) -> None:
        print(f"zKAIP — {self.peer.username} (porta {self.peer.port})")
        print("Comandos: /create <nomeGrupo> <host> <porta> | /add <nomeGrupo> <host> <porta> | "
              "/choose <nomeGrupo> | /msg <texto> | /send <caminho> | /groups | "
              "/accept <arquivoId> | /reject <arquivoId> | /leave <[>nomeGrupo> | /quit")
        while self._running:
            try:
                line = input(self._current_prompt())
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
            if len(args) != 3:
                print("uso: /create <nomeGrupo> <host> <porta>")
                return
            self.cmd_create(args[0], args[1], args[2])
        elif cmd == "/add":
            args = rest.split()
            if len(args) != 3:
                print("uso: /add <nomeGrupo> <host> <porta>")
                return
            self.cmd_add(args[0], args[1], args[2])
        elif cmd == "/choose":
            if not rest:
                print("uso: /choose <nomeGrupo>")
                return
            self.cmd_choose(rest.strip())
        elif cmd == "/msg":
            if not rest:
                print("uso: /msg <texto>")
                return
            self.cmd_msg(rest)
        elif cmd == "/send":
            if not rest:
                print("uso: /send <caminho>")
                return
            self.cmd_send(rest.strip())
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
            self.cmd_leave(rest.strip() if rest else None)
        elif cmd == "/quit":
            self.cmd_quit()
        else:
            print(f"comando desconhecido: {cmd}")

    # comandos

    def cmd_create(self, name: str, host: str, port_str: str) -> None:
        if " " in name or "\t" in name:
            print("o nome do grupo não pode conter espaços")
            return
        if self.peer.group_manager.has_exact_name(name):
            print(f"você já tem um grupo chamado '{name}'")
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
        group_id = str(uuid.uuid4())
        members = [
            {"peerId": self.peer.peer_id, "host": self.peer.host, "port": self.peer.port, "username": self.peer.username},
            {"peerId": conn.remote_peer_id, "host": host, "port": port, "username": conn.remote_username or conn.remote_peer_id[:8]},
        ]
        self.peer.group_manager.create_or_update_group(group_id, self.peer.peer_id, name, members)
        conn.send(build_envelope(self.peer, "CREATE_GROUP", None,
                                  {"groupId": group_id, "groupName": name, "members": members}))
        print(f"grupo '{name}' criado com {conn.remote_username or conn.remote_peer_id[:8]}")

    def cmd_add(self, name: str, host: str, port_str: str) -> None:
        group = self.peer.group_manager.resolve_by_name(name)
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

        new_member = {"peerId": conn.remote_peer_id, "host": host, "port": port,
                      "username": conn.remote_username or conn.remote_peer_id[:8]}
        all_members = [m.to_dict() for m in group.members] + [new_member]
        self.peer.group_manager.set_members(group.group_id, all_members)

        envelope = build_envelope(self.peer, "ADD_MEMBER", group.group_id, {
            "groupId": group.group_id,
            "groupName": group.name,
            "creatorId": group.creator_id,
            "newMember": new_member,
            "allMembers": all_members,
        })
        for m in all_members:
            if m["peerId"] == self.peer.peer_id:
                continue
            existing_conn = self.peer.get_connection(m["peerId"])
            if existing_conn and existing_conn.state == ConnectionState.ONLINE:
                existing_conn.send(envelope)
            else:
                self.peer.ensure_connected(m["peerId"], m["host"], m["port"], then_send=envelope)

        print(f"'{new_member['username']}' adicionado ao grupo '{group.name}'")

    def cmd_choose(self, name: str) -> None:
        group = self.peer.group_manager.resolve_by_name(name)
        if not group:
            print(f"grupo '{name}' não encontrado")
            return
        self.current_group_id = group.group_id
        print(f"--- {group.name} ---")
        history = self.peer.group_manager.get_messages(group.group_id)
        for envelope in history[-HISTORY_ON_CHOOSE:]:
            self.display_message(envelope)

    def cmd_msg(self, text: str) -> None:
        if not self.current_group_id:
            print("nenhum grupo selecionado. use /choose <nomeGrupo> primeiro.")
            return
        group = self.peer.group_manager.get(self.current_group_id)
        envelope = build_envelope(self.peer, "CHAT_MSG", group.group_id, {"content": text})
        self.peer.group_manager.add_message(group.group_id, envelope)
        self.peer.broadcast_to_group(group.group_id, envelope)
        self.display_message(envelope, self_sent=True)

    def cmd_send(self, path_str: str) -> None:
        if not self.current_group_id:
            print("nenhum grupo selecionado. use /choose <nomeGrupo> primeiro.")
            return
        group = self.peer.group_manager.get(self.current_group_id)
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
        print(f"arquivo '{path.name}' ({file_size} bytes) oferecido ao grupo '{group.name}'")

    def cmd_groups(self) -> None:
        groups = self.peer.group_manager.list_groups()
        if not groups:
            print("nenhum grupo.")
            return
        for g in groups:
            marker = " (atual)" if g.group_id == self.current_group_id else ""
            creator_tag = " (você é o criador)" if g.creator_id == self.peer.peer_id else ""
            print(f"grupo '{g.name}'{marker}{creator_tag}")
            for m in g.members:
                if m.peer_id == self.peer.peer_id:
                    print(f"  - você @ {m.host}:{m.port} [local]")
                    continue
                name = self.peer.display_name(m.peer_id)
                conn = self.peer.get_connection(m.peer_id)
                online = conn is not None and conn.state == ConnectionState.ONLINE
                status = "online" if online else "offline"
                print(f"  - {name} @ {m.host}:{m.port} [{status}]")

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

    def cmd_leave(self, name: Optional[str]) -> None:
        if name:
            group = self.peer.group_manager.resolve_by_name(name)
        else:
            if not self.current_group_id:
                print("nenhum grupo selecionado. use /leave <nomeGrupo> ou escolha um grupo com /choose primeiro.")
                return
            group = self.peer.group_manager.get(self.current_group_id)
        if not group:
            print("grupo não encontrado")
            return
        envelope = build_envelope(self.peer, "LEAVE_GROUP", group.group_id, {"groupId": group.group_id})
        self.peer.broadcast_to_group(group.group_id, envelope)
        self.peer.group_manager.remove_member(group.group_id, self.peer.peer_id)
        if self.current_group_id == group.group_id:
            self.current_group_id = None
        print(f"você saiu do grupo '{group.name}'")

    def cmd_quit(self) -> None:
        self._running = False
        print("encerrando...")
        self.peer.shutdown()
