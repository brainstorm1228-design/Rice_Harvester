import hashlib
import socket
import struct
import threading
from typing import Callable, Optional

from Crypto.Cipher import AES


class ScreenClient:
    """원격 PC의 화면 스트림을 수신합니다."""

    def __init__(self, host: str, screen_port: int, secret: str,
                 on_frame: Callable[[bytes, int, int], None]):
        self.host = host
        self.port = screen_port
        self._key = hashlib.sha256(secret.encode()).digest()
        self._on_frame = on_frame
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> bool:
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=5)
            self._running = True
            self._thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            print(f"[Screen] Cannot connect to {self.host}:{self.port} — {e}")
            return False

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _recv_loop(self):
        try:
            while self._running and self._sock:
                # 4바이트 빅엔디안 길이 프리픽스
                raw_len = self._recvall(4)
                if not raw_len:
                    break
                length = struct.unpack(">I", raw_len)[0]
                if length > 10 * 1024 * 1024:  # 10MB 상한
                    break

                encrypted = self._recvall(length)
                if not encrypted:
                    break

                payload = self._decrypt(encrypted)
                # [4B W][4B H][JPEG]
                w = struct.unpack_from("<i", payload, 0)[0]
                h = struct.unpack_from("<i", payload, 4)[0]
                jpeg = payload[8:]

                self._on_frame(jpeg, w, h)
        except Exception as e:
            if self._running:
                print(f"[Screen] Stream error: {e}")
        finally:
            self._running = False

    def _recvall(self, n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _decrypt(self, data: bytes) -> bytes:
        iv = data[:16]
        cipher = AES.new(self._key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(data[16:])
        # PKCS7 언패딩
        pad_len = decrypted[-1]
        return decrypted[:-pad_len]
