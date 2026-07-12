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


def load_or_create_identity():
    existing = storage.load_peer(DATA_DIR)
    if existing:
        return existing["peerId"], existing["port"]

    peer_id = str(uuid.uuid4())
    while True:
        raw = input("Porta para escutar conexões: ").strip()
        try:
            port = int(raw)
            break
        except ValueError:
            print("porta inválida, tente novamente.")
    storage.save_peer(DATA_DIR, peer_id, port)
    return peer_id, port


def main():
    (DATA_DIR / "messages").mkdir(parents=True, exist_ok=True)

    peer_id, port = load_or_create_identity()
    peer = Peer(peer_id, DEFAULT_HOST, port, DATA_DIR)
    peer.group_manager.load()

    # Reconnect (in background) to every known member of every saved group.
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
