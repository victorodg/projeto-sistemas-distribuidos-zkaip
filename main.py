import sys
import uuid
from pathlib import Path

import storage
from cli import CLI
from peer import Peer
from server import PeerServer

DEFAULT_HOST = "127.0.0.1"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def _ask_port() -> int:
    while True:
        raw = input("Porta para escutar conexões: ").strip()
        try:
            return int(raw)
        except ValueError:
            print("porta inválida, tente novamente.")


def _ask_username() -> str:
    while True:
        raw = input("Escolha seu nome de usuário: ").strip()
        if raw:
            return raw
        print("o nome de usuário não pode ser vazio.")


def load_or_create_identity():
    existing = storage.load_peer(DATA_DIR)
    if existing:
        peer_id = existing["peerId"]
        port = existing["port"]
        username = existing.get("username")
        if username:
            return peer_id, port, username
    else:
        peer_id = str(uuid.uuid4())
        port = _ask_port()

    username = _ask_username()
    storage.save_peer(DATA_DIR, peer_id, port, username)
    return peer_id, port, username


def main():
    (DATA_DIR / "messages").mkdir(parents=True, exist_ok=True)

    peer_id, port, username = load_or_create_identity()
    peer = Peer(peer_id, DEFAULT_HOST, port, username, DATA_DIR)
    peer.group_manager.load()

    # Inicializa o cache de nomes de usuário com base nos membros salvos dos grupos, para que peers offline
    # sejam exibidos pelo nome em vez do ID
    for group in peer.group_manager.list_groups():
        for member in group.members:
            if member.peer_id != peer.peer_id and member.username:
                peer.usernames[member.peer_id] = member.username

    # Reconecta (no background) todos os membros conhecidos de cada grupo salvo.
    for group in peer.group_manager.list_groups():
        for member in group.members:
            if member.peer_id != peer.peer_id:
                peer.ensure_connected(member.peer_id, member.host, member.port)

    server = PeerServer(peer, peer.dispatcher)
    peer.server = server
    server.start()

    cli = CLI(peer)
    peer.cli = cli
    try:
        cli.run()
    except KeyboardInterrupt:
        peer.shutdown()


if __name__ == "__main__":
    sys.exit(main())
