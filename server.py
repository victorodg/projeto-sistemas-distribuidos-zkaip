import socket
import threading

from connection import Connection


class PeerServer:
    """Accepts incoming TCP connections and hands them off as Connections."""

    def __init__(self, peer, dispatcher):
        self.peer = peer
        self.dispatcher = dispatcher
        self.sock: socket.socket = None
        self._stop = threading.Event()

    def start(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", self.peer.port))
        self.sock.listen(20)
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                client_sock, _addr = self.sock.accept()
            except OSError:
                break
            client_sock.settimeout(None)
            conn = Connection(client_sock, self.peer, self.dispatcher, initiator=False)
            conn.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
