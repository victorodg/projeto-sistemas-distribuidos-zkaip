"""
Executa uma instância do zKAIP em "modo demonstração": em vez de esperar o
usuário digitar comandos, lê um roteiro de um arquivo texto e simula a
digitação de cada comando na tela (com pequenos atrasos por caractere),
processando-o normalmente em seguida. Não altera nada do código do projeto
em si (peer.py, cli.py, etc.) - só os reaproveita.

Diretivas especiais aceitas no arquivo de roteiro (uma por linha). Todas as
que "esperam" fazem polling do estado real do peer em vez de usar uma pausa
fixa - assim o roteiro não depende de adivinhar quanto tempo cada lado vai
levar (o que gera dessincronia entre os dois processos independentes):
  #note: <texto>        imprime um destaque/narração na tela
  #pause:<segundos>      pausa (aceita decimais, ex: #pause:2.5) - use só
                          para ritmo/narração, não para esperar o outro lado
  #wait_group:<nome>     espera até o grupo existir localmente (útil quando
                          o outro peer ainda não propagou o CREATE_GROUP)
  #wait_offer            espera até existir uma oferta de arquivo pendente
  #wait_online:<nome>    espera até a conexão com esse peer (por nome de
                          usuário) estar online
  #accept_last           aceita a oferta de arquivo pendente mais recente
                          (o fileId é gerado em tempo de execução, então não
                          dá para escrever "/accept <id>" fixo no roteiro)
  #signal:<nome>         cria um arquivo .signal_<nome> na pasta demo/, para
                          o script PowerShell que orquestra as janelas saber
                          quando é a hora certa de abrir a próxima
  #crash                 encerra o processo imediatamente (os._exit), sem
                          desconexão graciosa - simula uma queda real
  # (qualquer outra)      comentário, ignorado

Qualquer outra linha não-vazia é tratada como um comando normal da CLI
(ex: "/msg oi", "/choose Feijoada").

Uso:
  python demo_runner.py --data-dir demo/alice/data --port 6001 \
      --username Alice --script demo/script_alice.txt
"""
import argparse
import os
import random
import sys
import time
import uuid
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
PROJECT_DIR = DEMO_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

import storage
from cli import CLI
from connection import ConnectionState
from peer import Peer
from server import PeerServer

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PAUSE_BETWEEN_COMMANDS = 4.5
TYPING_CHARS_PER_SECOND = 13


def load_or_create_identity(data_dir: Path, port: int, username: str):
    existing = storage.load_peer(data_dir)
    if existing and existing.get("username"):
        return existing["peerId"], existing["port"], existing["username"]
    peer_id = existing["peerId"] if existing else str(uuid.uuid4())
    final_port = existing["port"] if existing else port
    storage.save_peer(data_dir, peer_id, final_port, username)
    return peer_id, final_port, username


def type_line(prompt: str, text: str) -> None:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(random.uniform(0.8, 1.4) / TYPING_CHARS_PER_SECOND)
    sys.stdout.write("\n")
    sys.stdout.flush()


def wait_for_group(peer, name: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if peer.group_manager.resolve_by_name(name):
            return
        time.sleep(0.3)
    print(f"[demo] aviso: grupo '{name}' nao apareceu em {timeout}s (continuando mesmo assim)")


def wait_for_offer(peer, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with peer.file_transfers_lock:
            if peer.file_transfers_incoming:
                return
        time.sleep(0.3)
    print(f"[demo] aviso: nenhuma oferta de arquivo chegou em {timeout}s (continuando mesmo assim)")


def wait_online(peer, username: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        peer_id = next((pid for pid, name in peer.usernames.items() if name == username), None)
        if peer_id:
            conn = peer.get_connection(peer_id)
            if conn and conn.state == ConnectionState.ONLINE:
                return
        time.sleep(0.3)
    print(f"[demo] aviso: '{username}' nao ficou online em {timeout}s (continuando mesmo assim)")


def signal(name: str) -> None:
    (DEMO_DIR / f".signal_{name}").touch()


def accept_last_offer(peer, cli) -> None:
    with peer.file_transfers_lock:
        if not peer.file_transfers_incoming:
            print("[demo] aviso: nenhuma oferta de arquivo pendente para aceitar")
            return
        file_id = list(peer.file_transfers_incoming.keys())[-1]
    line = f"/accept {file_id[:8]}"
    type_line(cli._current_prompt(), line)
    cli._dispatch(line)


def run_script(peer, cli, script_path: Path) -> None:
    for raw_line in script_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        if line.startswith("#pause:"):
            time.sleep(float(line.split(":", 1)[1]))
            continue
        if line.startswith("#note:"):
            print(f"\n=== {line.split(':', 1)[1].strip()} ===\n")
            time.sleep(3.0)
            continue
        if line.startswith("#wait_group:"):
            wait_for_group(peer, line.split(":", 1)[1].strip())
            continue
        if line.strip() == "#wait_offer":
            wait_for_offer(peer)
            continue
        if line.startswith("#wait_online:"):
            wait_online(peer, line.split(":", 1)[1].strip())
            continue
        if line.startswith("#signal:"):
            signal(line.split(":", 1)[1].strip())
            continue
        if line.strip() == "#accept_last":
            accept_last_offer(peer, cli)
            time.sleep(1.5)
            continue
        if line.strip() == "#crash":
            print("\n*** processo encerrado abruptamente (simulando falha) ***")
            sys.stdout.flush()
            os._exit(1)
        if line.startswith("#"):
            continue

        prompt = cli._current_prompt()
        type_line(prompt, line)
        try:
            cli._dispatch(line)
        except Exception as e:
            print(f"[demo] erro ao executar '{line}': {e}")
        time.sleep(DEFAULT_PAUSE_BETWEEN_COMMANDS)

        if not cli._running:
            return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--script", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    (data_dir / "messages").mkdir(parents=True, exist_ok=True)

    peer_id, port, username = load_or_create_identity(data_dir, args.port, args.username)
    peer = Peer(peer_id, DEFAULT_HOST, port, username, data_dir)
    peer.group_manager.load()

    for group in peer.group_manager.list_groups():
        for member in group.members:
            if member.peer_id != peer.peer_id and member.username:
                peer.usernames[member.peer_id] = member.username

    for group in peer.group_manager.list_groups():
        for member in group.members:
            if member.peer_id != peer.peer_id:
                peer.ensure_connected(member.peer_id, member.host, member.port)

    server = PeerServer(peer, peer.dispatcher)
    peer.server = server
    server.start()

    cli = CLI(peer)
    peer.cli = cli

    print(f"=== zKAIP DEMO - {username} (porta {port}) ===\n")
    time.sleep(0.5)

    run_script(peer, cli, Path(args.script))

    print("\n=== roteiro concluido ===")
    time.sleep(2)


if __name__ == "__main__":
    main()
