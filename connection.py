import json
import queue
import socket
import threading
import time
from typing import Any, Dict, Optional

from models import build_envelope


# ---------------------------------------------------------------------------
# Framing: 4-byte big-endian length prefix + UTF-8 JSON payload.
# TCP does not preserve message boundaries, so every message must be
# length-prefixed on the wire.
# ---------------------------------------------------------------------------

def send_msg(sock: socket.socket, obj: Dict[str, Any]) -> None:
    data = json.dumps(obj).encode("utf-8")
    sock.sendall(len(data).to_bytes(4, "big") + data)


def recvn(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf += chunk
    return buf


def recv_msg(sock: socket.socket) -> Dict[str, Any]:
    raw = recvn(sock, 4)
    n = int.from_bytes(raw, "big")
    return json.loads(recvn(sock, n).decode("utf-8"))


class ConnectionState:
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    ONLINE = "online"
    OFFLINE = "offline"
    CLOSED = "closed"


HEARTBEAT_INTERVAL = 15
HEARTBEAT_TIMEOUT = 10
HEARTBEAT_RETRIES = 3


class Connection:
    """Manages a single persistent TCP connection: a dedicated read thread,
    a dedicated write thread consuming a queue, and heartbeat/reconnection
    logic. Knows nothing about groups."""

    def __init__(self, sock: socket.socket, peer, dispatcher, host: Optional[str] = None,
                 port: Optional[int] = None, initiator: bool = False):
        self.sock = sock
        self.peer = peer
        self.dispatcher = dispatcher
        self.host = host
        self.port = port
        self.initiator = initiator

        self.remote_peer_id: Optional[str] = None
        self.state = ConnectionState.CONNECTING
        self.handshake_sent = False

        self.send_queue: "queue.Queue" = queue.Queue()
        self._stop = threading.Event()
        self._disconnect_lock = threading.Lock()
        self._disconnected = False
        self._hb_acked = threading.Event()
        self.online_event = threading.Event()

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        self.state = ConnectionState.HANDSHAKING
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._write_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        if self.initiator:
            self.send_handshake()

    def send_handshake(self) -> None:
        envelope = build_envelope(self.peer, "HANDSHAKE", None, {
            "peerId": self.peer.peer_id,
            "host": self.peer.host,
            "port": self.peer.port,
        })
        self.handshake_sent = True
        self.send(envelope)

    def send(self, obj: Dict[str, Any]) -> None:
        """Enqueues a message for sending; never blocks the caller."""
        self.send_queue.put(obj)

    def mark_online(self) -> None:
        self.state = ConnectionState.ONLINE
        self.online_event.set()

    def wait_online(self, timeout: float = 5.0) -> bool:
        return self.online_event.wait(timeout) and self.state == ConnectionState.ONLINE

    def on_heartbeat_ack(self) -> None:
        self._hb_acked.set()

    # -- threads ---------------------------------------------------------

    def _write_loop(self) -> None:
        while not self._stop.is_set():
            try:
                obj = self.send_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                send_msg(self.sock, obj)
            except (OSError, ConnectionError):
                self._handle_disconnect()
                return

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = recv_msg(self.sock)
            except (OSError, ConnectionError, ValueError):
                self._handle_disconnect()
                return
            try:
                self.dispatcher.handle(self, msg)
            except Exception as e:  # keep the read loop alive on handler bugs
                print(f"\r\033[K[error] handling message: {e}")

    def _heartbeat_loop(self) -> None:
        # Wait for the connection to come online before heartbeating.
        while not self._stop.is_set():
            time.sleep(HEARTBEAT_INTERVAL)
            if self._stop.is_set():
                return
            if self.state != ConnectionState.ONLINE:
                continue
            if not self._send_heartbeat_and_wait():
                self._handle_disconnect()
                return

    def _send_heartbeat_and_wait(self) -> bool:
        for _ in range(HEARTBEAT_RETRIES):
            self._hb_acked.clear()
            self.send(build_envelope(self.peer, "HEARTBEAT", None, {}))
            if self._hb_acked.wait(timeout=HEARTBEAT_TIMEOUT):
                return True
        return False

    # -- disconnect / reconnect -----------------------------------------

    def _handle_disconnect(self) -> None:
        with self._disconnect_lock:
            if self._disconnected:
                return
            self._disconnected = True
        self.state = ConnectionState.OFFLINE
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self.peer.on_connection_offline(self)
        if self.host and self.port:
            self.peer.schedule_reconnect(self.host, self.port)

    def close(self) -> None:
        with self._disconnect_lock:
            self._disconnected = True
        self._stop.set()
        self.state = ConnectionState.CLOSED
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
