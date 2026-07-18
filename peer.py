import socket
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from connection import Connection, ConnectionState
from dispatcher import Dispatcher
from group_manager import GroupManager
from lamport import LamportClock

RECONNECT_BACKOFFS = [5, 10, 30]


class Peer:
    """Central state of the local peer: identity, clock, connection table,
    group manager and file-transfer bookkeeping."""

    def __init__(self, peer_id: str, host: str, port: int, username: str, data_dir: Path):
        self.peer_id = peer_id
        self.host = host
        self.port = port
        self.username = username
        self.data_dir = data_dir
        self.downloads_dir = data_dir.parent / "downloads"

        self.clock = LamportClock()
        self.group_manager = GroupManager(data_dir)
        self.dispatcher = Dispatcher(self)

        self.connections: Dict[str, Connection] = {}
        self.connections_lock = threading.RLock()

        # peerId -> username, for display purposes only. IDs are never
        # shown to the user; this lets us print a name for any peer we've
        # ever handshaked with or seen listed as a group member, even
        # while it's offline.
        self.usernames: Dict[str, str] = {}

        self._reconnecting = set()
        self._reconnecting_lock = threading.Lock()

        self.file_transfers_outgoing: Dict[str, Dict[str, Any]] = {}
        self.file_transfers_incoming: Dict[str, Dict[str, Any]] = {}
        self.file_transfers_lock = threading.RLock()

        self.server = None
        self.cli = None
        self.shutting_down = False

    def display_name(self, peer_id: str) -> str:
        if peer_id == self.peer_id:
            return self.username
        return self.usernames.get(peer_id, peer_id[:8])

    # -- connection table --------------------------------------------------

    def register_connection(self, conn: Connection) -> Tuple[str, Optional[Connection]]:
        """Registers conn as the canonical connection for its remote peer.

        Two peers can end up dialing each other at nearly the same time,
        producing two independent TCP connections between the same pair.
        Deciding which one to keep based on local arrival order is unsafe:
        each side observes handshakes completing in its own order, so the
        two peers can each keep a *different* one of the two connections
        - and since the other side closed "its" loser, both survivors
        eventually error out, triggering a reconnect, which recreates the
        same race forever (this was the cause of the repeated "conectado"/
        "ficou offline" flapping seen when testing two peers locally).

        Instead we resolve duplicates deterministically: both sides know
        both peerIds after the handshake, so both independently keep the
        connection dialed by whichever peerId is smaller. That decision
        doesn't depend on timing, so both sides always converge on the
        exact same surviving connection.

        Returns (outcome, old_conn):
          outcome is "new" (first connection to this peer - caller should
          notify the user), "replace" (a duplicate resolved in favor of
          conn - silent, not a real reconnect) or "rejected" (conn is the
          losing duplicate and must be closed by the caller, silently).
          old_conn is the connection conn replaced, if any (caller must
          close it).
        """
        with self.connections_lock:
            existing = self.connections.get(conn.remote_peer_id)
            if existing is None or existing is conn or existing.state != ConnectionState.ONLINE:
                self.connections[conn.remote_peer_id] = conn
                return "new", None
            if self._is_preferred_dialer(conn):
                self.connections[conn.remote_peer_id] = conn
                return "replace", existing
            return "rejected", None

    def _is_preferred_dialer(self, conn: Connection) -> bool:
        smaller = min(self.peer_id, conn.remote_peer_id)
        dialer_id = self.peer_id if conn.initiator else conn.remote_peer_id
        return dialer_id == smaller

    def get_connection(self, peer_id: str) -> Optional[Connection]:
        with self.connections_lock:
            return self.connections.get(peer_id)

    def on_connection_offline(self, conn: Connection) -> None:
        with self.connections_lock:
            if conn.remote_peer_id and self.connections.get(conn.remote_peer_id) is conn:
                del self.connections[conn.remote_peer_id]
        if conn.remote_peer_id and self.cli:
            self.cli.notify(f"[info] {self.display_name(conn.remote_peer_id)} ficou offline")

    # -- outgoing connections ------------------------------------------

    def connect_to(self, host: str, port: int) -> Optional[Connection]:
        try:
            sock = socket.create_connection((host, port), timeout=5)
        except OSError:
            return None
        # socket.create_connection(..., timeout=5) leaves that 5s timeout
        # permanently attached to the socket - without resetting it here,
        # recv() would raise a timeout (treated as a dead connection) after
        # every 5s of normal idle chat, causing endless reconnect flapping.
        sock.settimeout(None)
        conn = Connection(sock, self, self.dispatcher, host=host, port=port, initiator=True)
        conn.start()
        return conn

    def connect_blocking(self, host: str, port: int, timeout: float = 5.0) -> Optional[Connection]:
        conn = self.connect_to(host, port)
        if conn is None:
            return None
        if conn.wait_online(timeout=timeout):
            return conn
        return None

    def ensure_connected(self, peer_id: str, host: str, port: int, then_send: Optional[Dict[str, Any]] = None) -> None:
        with self.connections_lock:
            conn = self.connections.get(peer_id)
            if conn and conn.state == ConnectionState.ONLINE:
                if then_send:
                    conn.send(then_send)
                return

        def worker():
            conn = self.connect_to(host, port)
            if conn and conn.wait_online(timeout=10):
                if then_send:
                    conn.send(then_send)

        threading.Thread(target=worker, daemon=True).start()

    def schedule_reconnect(self, host: str, port: int) -> None:
        if self.shutting_down:
            return
        key = (host, port)
        with self._reconnecting_lock:
            if key in self._reconnecting:
                return
            self._reconnecting.add(key)
        threading.Thread(target=self._reconnect_worker, args=(host, port), daemon=True).start()

    def _reconnect_worker(self, host: str, port: int) -> None:
        try:
            i = 0
            while not self.shutting_down:
                delay = RECONNECT_BACKOFFS[min(i, len(RECONNECT_BACKOFFS) - 1)]
                time.sleep(delay)
                i += 1
                conn = self.connect_to(host, port)
                if conn is not None and conn.wait_online(timeout=5):
                    return
        finally:
            with self._reconnecting_lock:
                self._reconnecting.discard((host, port))

    # -- group broadcasting -----------------------------------------------

    def broadcast_to_group(self, group_id: str, envelope: Dict[str, Any], exclude_peer_id: Optional[str] = None) -> None:
        group = self.group_manager.get(group_id)
        if not group:
            return
        exclude = exclude_peer_id or self.peer_id
        for m in group.members:
            if m.peer_id == exclude:
                continue
            conn = self.get_connection(m.peer_id)
            if conn and conn.state == ConnectionState.ONLINE:
                conn.send(envelope)
            else:
                self.ensure_connected(m.peer_id, m.host, m.port, then_send=envelope)

    # -- file transfer lookups -------------------------------------------

    def resolve_incoming_file(self, file_id_prefix: str):
        with self.file_transfers_lock:
            if file_id_prefix in self.file_transfers_incoming:
                return file_id_prefix, self.file_transfers_incoming[file_id_prefix]
            matches = [fid for fid in self.file_transfers_incoming if fid.startswith(file_id_prefix)]
            if len(matches) == 1:
                return matches[0], self.file_transfers_incoming[matches[0]]
            return None, None

    # -- shutdown -----------------------------------------------------------

    def shutdown(self) -> None:
        self.shutting_down = True
        if self.server:
            self.server.stop()
        with self.connections_lock:
            conns = list(self.connections.values())
        for conn in conns:
            conn.close()
