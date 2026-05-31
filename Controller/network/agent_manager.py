import hashlib
import json
import socket
import struct
import threading
import time
from typing import Callable, Optional

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from models.command import Command


class AgentConnection:
    def __init__(self, host: str, port: int, key: bytes,
                 on_status_change: Optional[Callable] = None):
        self.host = host
        self.port = port
        self._key  = key
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._on_status_change = on_status_change

        self.latency_ms: float = -1.0   # 마지막 핑 결과 (ms)
        self.last_status: dict = {}
        self.auto_reconnect = True
        self._reconnect_thread: Optional[threading.Thread] = None

    # ── 연결 / 해제 ─────────────────────────────────────────────────────

    def connect(self, timeout: float = 5.0) -> bool:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
            with self._lock:
                self._sock = sock
            self._notify()
            self._start_ping_loop()
            return True
        except Exception as e:
            print(f"[Manager] Cannot connect {self}: {e}")
            if self.auto_reconnect:
                self._schedule_reconnect()
            return False

    def disconnect(self, permanent: bool = False):
        if permanent:
            self.auto_reconnect = False
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
        self.latency_ms = -1.0
        self._notify()

    # ── 명령 전송 ────────────────────────────────────────────────────────

    def send(self, command: Command) -> bool:
        if not self.is_connected:
            return False
        try:
            payload = self._encrypt(command.to_json())
            packet  = struct.pack(">I", len(payload)) + payload
            with self._lock:
                if self._sock:
                    self._sock.sendall(packet)
            return True
        except Exception as e:
            print(f"[Manager] Send error {self}: {e}")
            self._handle_drop()
            return False

    def request(self, command: Command, timeout: float = 5.0) -> Optional[dict]:
        if not self.is_connected:
            return None
        if not command.request_id:
            command.request_id = f"req-{time.time_ns()}"
        try:
            payload = self._encrypt(command.to_json())
            packet = struct.pack(">I", len(payload)) + payload
            with self._lock:
                if not self._sock:
                    return None
                old_timeout = self._sock.gettimeout()
                self._sock.settimeout(timeout)
                try:
                    self._sock.sendall(packet)
                    header = self._recv_exact(4)
                    length = struct.unpack(">I", header)[0]
                    if length < 1 or length > 10_000_000:
                        raise ValueError(f"invalid response length {length}")
                    encrypted = self._recv_exact(length)
                finally:
                    self._sock.settimeout(old_timeout)
            response = json.loads(self._decrypt(encrypted).decode("utf-8"))
            if response.get("requestId") != command.request_id:
                return None
            return response.get("data")
        except Exception as e:
            print(f"[Manager] Request error {self}: {e}")
            self._handle_drop()
            return None

    # ── 핑 (레이턴시 측정) ───────────────────────────────────────────────
    # 프로토콜: type="ping" 명령 전송 후 응답 시간 측정 (단방향 RTT 추정)

    def ping(self) -> float:
        """전송 왕복 시간(ms)을 측정. 실패 시 -1 반환."""
        from models.command import Command as Cmd
        import time as _t
        if not self.is_connected:
            return -1.0
        try:
            t0 = _t.monotonic()
            ping_cmd = Cmd.request("ping", "ping")
            res = self.request(ping_cmd, timeout=2.0)
            if res and res.get("ok"):
                self.latency_ms = round((_t.monotonic() - t0) * 1000, 1)
                return self.latency_ms
            return -1.0
        except Exception:
            return -1.0

    def _start_ping_loop(self):
        def loop():
            while self.is_connected:
                self.ping()
                self.status()
                self._notify()
                time.sleep(3)
        threading.Thread(target=loop, daemon=True).start()

    # ── 재연결 ──────────────────────────────────────────────────────────

    def _handle_drop(self):
        self.disconnect()
        if self.auto_reconnect:
            self._schedule_reconnect()

    def _schedule_reconnect(self, delay: float = 5.0):
        def attempt():
            print(f"[Manager] Reconnecting to {self} in {delay}s…")
            time.sleep(delay)
            if not self.is_connected:
                self.connect()
        if not (self._reconnect_thread and self._reconnect_thread.is_alive()):
            self._reconnect_thread = threading.Thread(target=attempt, daemon=True)
            self._reconnect_thread.start()

    # ── 암호화 ──────────────────────────────────────────────────────────

    def _encrypt(self, data: bytes) -> bytes:
        iv      = get_random_bytes(16)
        pad_len = 16 - len(data) % 16
        data   += bytes([pad_len] * pad_len)
        return iv + AES.new(self._key, AES.MODE_CBC, iv).encrypt(data)

    def _decrypt(self, data: bytes) -> bytes:
        iv = data[:16]
        body = AES.new(self._key, AES.MODE_CBC, iv).decrypt(data[16:])
        pad_len = body[-1]
        if 1 <= pad_len <= 16:
            return body[:-pad_len]
        return body

    def _recv_exact(self, size: int) -> bytes:
        chunks = []
        remaining = size
        while remaining > 0:
            if not self._sock:
                raise ConnectionError("socket closed")
            chunk = self._sock.recv(remaining)
            if not chunk:
                raise ConnectionError("socket closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def status(self) -> Optional[dict]:
        res = self.request(Command.request("query", "status"), timeout=3.0)
        if isinstance(res, dict):
            self.last_status = res
        return res

    def find_image(self, image_data: str, **options) -> Optional[dict]:
        timeout_ms = int(options.get("timeoutMs", 3000))
        data = {"imageData": image_data, **options}
        return self.request(Command.request("image", "find", data=data), timeout=max(3.0, timeout_ms / 1000.0 + 2.0))

    # ── 상태 ────────────────────────────────────────────────────────────

    def _notify(self):
        if self._on_status_change:
            try:
                self._on_status_change(self)
            except Exception:
                pass

    @property
    def is_connected(self) -> bool:
        return self._sock is not None

    @property
    def status_label(self) -> str:
        if self.is_connected:
            lat = f"  {self.latency_ms:.0f}ms" if self.latency_ms >= 0 else ""
            return f"[ON]  {self}{lat}"
        return f"[OFF] {self}"

    def __str__(self) -> str:
        return f"{self.host}:{self.port}"


class AgentManager:
    def __init__(self, secret: str):
        self._key    = hashlib.sha256(secret.encode()).digest()
        self._agents: dict[str, AgentConnection] = {}
        self.on_status_change: Optional[Callable] = None

    def set_secret(self, secret: str):
        self._key = hashlib.sha256(secret.encode()).digest()
        for agent in self._agents.values():
            agent._key = self._key

    def add(self, host: str, port: int = 9000) -> AgentConnection:
        key  = f"{host}:{port}"
        if key in self._agents:
            return self._agents[key]
        conn = AgentConnection(host, port, self._key,
                               on_status_change=self.on_status_change)
        self._agents[key] = conn
        return conn

    def remove(self, host: str, port: int = 9000):
        key = f"{host}:{port}"
        if key in self._agents:
            self._agents[key].disconnect(permanent=True)
            del self._agents[key]

    def broadcast(self, command: Command):
        for agent in list(self._agents.values()):
            if agent.is_connected:
                agent.send(command)

    def get(self, host: str, port: int = 9000) -> Optional[AgentConnection]:
        return self._agents.get(f"{host}:{port}")

    def all_agents(self) -> list[AgentConnection]:
        return list(self._agents.values())

    @property
    def connected_count(self) -> int:
        return sum(1 for a in self._agents.values() if a.is_connected)
