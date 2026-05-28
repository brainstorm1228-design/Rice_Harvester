import io
import threading
import tkinter as tk
from typing import Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from models.command import Command
from network.agent_manager import AgentConnection
from network.screen_client import ScreenClient

VIEW_W, VIEW_H = 1280, 720

# 팔레트 (main_window와 동일)
BG    = "#0d1117"
PANEL = "#161b22"
CARD  = "#1c2128"
BORDER= "#30363d"
GREEN = "#3fb950"
BLUE  = "#58a6ff"
TEXT  = "#e6edf3"
MUTED = "#8b949e"


class RemoteViewWindow:
    """
    원격 PC 화면을 실시간으로 보여주고,
    클릭/드래그를 실제 HID 마우스 명령으로 변환합니다.
    """

    def __init__(self, agent: AgentConnection, secret: str):
        self.agent  = agent
        self._secret = secret

        self._remote_w = 1920   # 원격 화면 실제 해상도 (첫 프레임 수신 후 갱신)
        self._remote_h = 1080

        self._lock  = threading.Lock()
        self._latest_frame: Optional[bytes] = None
        self._photo: Optional[ImageTk.PhotoImage] = None

        self._screen_client: Optional[ScreenClient] = None
        self._prev_canvas_pos: Optional[tuple[int, int]] = None

        self._build_window()
        self._connect_stream()

    # ------------------------------------------------------------------ #
    #  UI 구성                                                             #
    # ------------------------------------------------------------------ #

    def _build_window(self):
        self.win = ctk.CTkToplevel()
        self.win.title(f"Rice_Harvester  ·  {self.agent}")
        self.win.resizable(True, True)
        self.win.configure(fg_color=BG)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        # 상단 툴바
        toolbar = ctk.CTkFrame(self.win, fg_color=PANEL, height=40, corner_radius=0)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        ctk.CTkLabel(toolbar, text=f"🖥  {self.agent}",
                      font=ctk.CTkFont(family="Consolas", size=11),
                      text_color=TEXT).pack(side="left", padx=12)

        self._fps_var = tk.StringVar(value="-- fps")
        ctk.CTkLabel(toolbar, textvariable=self._fps_var,
                      font=ctk.CTkFont(family="Consolas", size=10),
                      text_color=GREEN).pack(side="right", padx=12)

        self._status_var = tk.StringVar(value="Connecting…")
        ctk.CTkLabel(toolbar, textvariable=self._status_var,
                      font=ctk.CTkFont(family="Consolas", size=10),
                      text_color=MUTED).pack(side="right", padx=4)

        ctk.CTkFrame(toolbar, width=1, fg_color=BORDER).pack(
            side="right", fill="y", pady=6)

        # 화면 캔버스 (tk.Canvas — CTk에는 이미지 캔버스 없음)
        self._canvas = tk.Canvas(self.win, width=VIEW_W, height=VIEW_H,
                                 bg="#000000", cursor="crosshair",
                                 highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)

        # 마우스 이벤트 바인딩
        self._canvas.bind("<Motion>",         self._on_mouse_move)
        self._canvas.bind("<ButtonPress-1>",   lambda e: self._mouse_btn("left",   True))
        self._canvas.bind("<ButtonRelease-1>", lambda e: self._mouse_btn("left",   False))
        self._canvas.bind("<ButtonPress-3>",   lambda e: self._mouse_btn("right",  True))
        self._canvas.bind("<ButtonRelease-3>", lambda e: self._mouse_btn("right",  False))
        self._canvas.bind("<ButtonPress-2>",   lambda e: self._mouse_btn("middle", True))
        self._canvas.bind("<ButtonRelease-2>", lambda e: self._mouse_btn("middle", False))
        self._canvas.bind("<MouseWheel>",      self._on_scroll)

        # 키보드 이벤트
        self.win.bind("<KeyPress>",   self._on_key_press)
        self.win.bind("<KeyRelease>", self._on_key_release)
        self.win.focus_set()

        # 프레임 갱신 루프 시작
        self._frame_count = 0
        self._last_fps_time = 0.0
        self.win.after(50, self._refresh_canvas)

    # ------------------------------------------------------------------ #
    #  스트림 연결                                                          #
    # ------------------------------------------------------------------ #

    def _connect_stream(self):
        screen_port = int(self.agent.port) + 1
        self._screen_client = ScreenClient(
            host=self.agent.host,
            screen_port=screen_port,
            secret=self._secret,
            on_frame=self._on_frame_received,
        )
        if self._screen_client.start():
            self._status_var.set(f"Streaming from {self.agent}")
        else:
            self._status_var.set("Stream connection failed")

    # ------------------------------------------------------------------ #
    #  프레임 수신 (백그라운드 스레드)                                       #
    # ------------------------------------------------------------------ #

    def _on_frame_received(self, jpeg: bytes, w: int, h: int):
        with self._lock:
            self._latest_frame = jpeg
            self._remote_w = w
            self._remote_h = h
        self._frame_count += 1

    # ------------------------------------------------------------------ #
    #  캔버스 갱신 (tkinter 메인 스레드)                                    #
    # ------------------------------------------------------------------ #

    def _refresh_canvas(self):
        frame = None
        with self._lock:
            if self._latest_frame:
                frame = self._latest_frame
                self._latest_frame = None

        if frame:
            try:
                img = Image.open(io.BytesIO(frame)).resize((VIEW_W, VIEW_H), Image.BILINEAR)
                self._photo = ImageTk.PhotoImage(img)
                self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
            except Exception:
                pass

        # FPS 표시 (1초마다 갱신)
        import time
        now = time.monotonic()
        if now - self._last_fps_time >= 1.0:
            self._fps_var.set(f"{self._frame_count} fps")
            self._frame_count = 0
            self._last_fps_time = now

        if self.win.winfo_exists():
            self.win.after(20, self._refresh_canvas)

    # ------------------------------------------------------------------ #
    #  좌표 변환: 캔버스 픽셀 → 원격 화면 절대 좌표                           #
    # ------------------------------------------------------------------ #

    def _canvas_to_remote(self, cx: int, cy: int) -> tuple[int, int]:
        rx = int(cx * self._remote_w / VIEW_W)
        ry = int(cy * self._remote_h / VIEW_H)
        return rx, ry

    # ------------------------------------------------------------------ #
    #  HID 이벤트 → 명령 전송                                               #
    # ------------------------------------------------------------------ #

    def _on_mouse_move(self, event: tk.Event):
        rx, ry = self._canvas_to_remote(event.x, event.y)
        self.agent.send(Command.mouse_move(rx, ry, absolute=True))

    def _mouse_btn(self, button: str, down: bool):
        cmd = Command.mouse_down(button) if down else Command.mouse_up(button)
        self.agent.send(cmd)

    def _on_scroll(self, event: tk.Event):
        # Windows: event.delta는 120 단위
        self.agent.send(Command.mouse_scroll(event.delta))

    def _on_key_press(self, event: tk.Event):
        vk = self._tk_keysym_to_vk(event.keysym)
        if vk:
            self.agent.send(Command.key_press(vk))

    def _on_key_release(self, event: tk.Event):
        vk = self._tk_keysym_to_vk(event.keysym)
        if vk:
            self.agent.send(Command.key_release(vk))

    @staticmethod
    def _tk_keysym_to_vk(keysym: str) -> Optional[int]:
        """tkinter keysym → Windows VK 코드 변환 (자주 쓰는 키)"""
        table = {
            "BackSpace": 0x08, "Tab": 0x09, "Return": 0x0D, "Escape": 0x1B,
            "space": 0x20, "Delete": 0x2E, "Home": 0x24, "End": 0x23,
            "Prior": 0x21, "Next": 0x22, "Left": 0x25, "Up": 0x26,
            "Right": 0x27, "Down": 0x28, "Insert": 0x2D,
            "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
            "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
            "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
            "Control_L": 0x11, "Control_R": 0x11,
            "Shift_L": 0x10, "Shift_R": 0x10,
            "Alt_L": 0x12, "Alt_R": 0x12,
            "Win_L": 0x5B, "Win_R": 0x5C,
        }
        if keysym in table:
            return table[keysym]
        if len(keysym) == 1:
            return ord(keysym.upper())
        return None

    def _on_fps_change(self, val):
        """FPS 슬라이더 변경 시 ScreenServer에 반영 (미래 확장)"""
        pass

    def _on_close(self):
        if self._screen_client:
            self._screen_client.stop()
        self.win.destroy()
