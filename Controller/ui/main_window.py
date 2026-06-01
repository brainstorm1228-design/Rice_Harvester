import base64
import ctypes
import io
import os
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageGrab, ImageTk

from config import DEFAULT_PORT, FLOWS_DIR, delete_workflow_file, load_config, load_workflows, save_config, save_workflow_file
from models.command import Command
from network.agent_manager import AgentConnection, AgentManager
from network.screen_client import ScreenClient

ctk.set_appearance_mode("dark")

ACTION_TYPES = ["대기", "키 입력", "마우스 이동", "자연 이동", "클릭", "랜덤 클릭", "스크롤", "이미지 찾기", "이미지 대기", "이미지 감지"]
BUTTON_VALUES = ["left", "right", "middle"]
KEY_OPTIONS = [
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "Enter", "Space", "Tab", "Esc", "Backspace", "Delete",
    "Left", "Right", "Up", "Down", "F1", "F2", "F3", "F4", "F5", "F6",
    "F7", "F8", "F9", "F10", "F11", "F12",
]
KEY_NAME_TO_VK = {
    "ENTER": 0x0D,
    "SPACE": 0x20,
    "TAB": 0x09,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "BACKSPACE": 0x08,
    "DELETE": 0x2E,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
}
for _n in range(1, 13):
    KEY_NAME_TO_VK[f"F{_n}"] = 0x6F + _n

FIELD_LABELS = {
    "ms": "대기 시간(초)",
    "key": "키",
    "mods": "보조키(ctrl, alt, shift)",
    "x": "X 좌표",
    "y": "Y 좌표",
    "duration": "이동 시간(초)",
    "jitter": "자연스러운 흔들림(px)",
    "button": "마우스 버튼",
    "x1": "시작 X",
    "y1": "시작 Y",
    "x2": "끝 X",
    "y2": "끝 Y",
    "delta": "스크롤 양",
    "image_path": "이미지 파일",
    "threshold": "유사도",
    "timeout": "제한 시간(초)",
    "match_mode": "매칭",
    "offset_x": "클릭 보정 X",
    "offset_y": "클릭 보정 Y",
    "interval": "감지 주기(초)",
    "detect_action": "감지 행동",
}


def _rgb_image(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    return image.convert("RGB")


def _debug_placeholder(detail: str = "") -> Image.Image:
    image = Image.new("RGB", (1280, 720), "#080c11")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1279, 719), outline="#314255", width=4)
    draw.text((48, 48), "Debug screen preview", fill="#f4f8fc")
    draw.text((48, 86), "Local screen capture is not available yet.", fill="#93a5ba")
    if detail:
        draw.text((48, 124), detail[:150], fill="#ff6b7a")
    return image


if os.name == "nt":
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ULONG_PTR),
        )

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = (
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ULONG_PTR),
        )

    class _INPUTUNION(ctypes.Union):
        _fields_ = (("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT))

    class _INPUT(ctypes.Structure):
        _fields_ = (("type", ctypes.c_ulong), ("ii", _INPUTUNION))

    _INPUT_MOUSE = 0
    _INPUT_KEYBOARD = 1
    _KEYEVENTF_KEYUP = 0x0002
    _MOUSEEVENTF_MOVE = 0x0001
    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004
    _MOUSEEVENTF_RIGHTDOWN = 0x0008
    _MOUSEEVENTF_RIGHTUP = 0x0010
    _MOUSEEVENTF_MIDDLEDOWN = 0x0020
    _MOUSEEVENTF_MIDDLEUP = 0x0040
    _MOUSEEVENTF_WHEEL = 0x0800
    _MOUSEEVENTF_ABSOLUTE = 0x8000
    _MOUSEEVENTF_VIRTUALDESK = 0x4000
    _SM_XVIRTUALSCREEN = 76
    _SM_YVIRTUALSCREEN = 77
    _SM_CXVIRTUALSCREEN = 78
    _SM_CYVIRTUALSCREEN = 79
else:
    _INPUT = None


def _local_vk_for_modifier(name: str) -> int:
    return {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B}.get(name.lower(), 0)


def _send_input_record(record) -> bool:
    if os.name != "nt" or _INPUT is None:
        return False
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(record), ctypes.sizeof(record))
    return sent == 1


def _send_local_key(vk: int, down: bool):
    if os.name != "nt" or not vk:
        return
    flags = 0 if down else _KEYEVENTF_KEYUP
    record = _INPUT(type=_INPUT_KEYBOARD, ii=_INPUTUNION(ki=_KEYBDINPUT(vk, 0, flags, 0, 0)))
    _send_input_record(record)


def _send_local_mouse_move(x: int, y: int, absolute: bool):
    if os.name != "nt":
        return
    flags = _MOUSEEVENTF_MOVE
    dx, dy = x, y
    if absolute:
        user32 = ctypes.windll.user32
        vx = user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
        vw = max(1, user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN) - 1)
        vh = max(1, user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN) - 1)
        dx = int((x - vx) * 65535 / vw)
        dy = int((y - vy) * 65535 / vh)
        flags |= _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK
    record = _INPUT(type=_INPUT_MOUSE, ii=_INPUTUNION(mi=_MOUSEINPUT(dx, dy, 0, flags, 0, 0)))
    _send_input_record(record)


def _send_local_mouse_button(button: str, down: bool):
    if os.name != "nt":
        return
    table = {
        "left": (_MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP),
        "right": (_MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP),
        "middle": (_MOUSEEVENTF_MIDDLEDOWN, _MOUSEEVENTF_MIDDLEUP),
    }
    flags = table.get(button.lower(), table["left"])[0 if down else 1]
    record = _INPUT(type=_INPUT_MOUSE, ii=_INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, flags, 0, 0)))
    _send_input_record(record)


def _send_local_input(command: Command) -> bool:
    if os.name != "nt":
        return False
    if command.type == "keyboard" and command.keyboard:
        mods = [_local_vk_for_modifier(m) for m in command.keyboard.modifiers]
        mods = [m for m in mods if m]
        if command.action == "press":
            for mod in mods:
                _send_local_key(mod, True)
            _send_local_key(command.keyboard.key_code, True)
        elif command.action == "release":
            _send_local_key(command.keyboard.key_code, False)
            for mod in reversed(mods):
                _send_local_key(mod, False)
        return True
    if command.type == "mouse" and command.mouse:
        mouse = command.mouse
        if command.action == "move":
            _send_local_mouse_move(mouse.x, mouse.y, mouse.absolute)
        elif command.action == "down":
            _send_local_mouse_button(mouse.button, True)
        elif command.action == "up":
            _send_local_mouse_button(mouse.button, False)
        elif command.action == "scroll":
            record = _INPUT(type=_INPUT_MOUSE, ii=_INPUTUNION(mi=_MOUSEINPUT(0, 0, mouse.scroll_delta, _MOUSEEVENTF_WHEEL, 0, 0)))
            _send_input_record(record)
        return True
    return False


THEMES = {
    "dark": {
        "bg": "#080c11",
        "surface": "#101722",
        "panel": "#172231",
        "panel2": "#202d3d",
        "hover": "#29394c",
        "stroke": "#314255",
        "text": "#f4f8fc",
        "muted": "#93a5ba",
        "faint": "#62758a",
        "blue": "#6ea8fe",
        "green": "#5be0a0",
        "red": "#ff6b7a",
        "yellow": "#f0c66e",
    },
    "light": {
        "bg": "#f4f7fb",
        "surface": "#ffffff",
        "panel": "#eef3f8",
        "panel2": "#e3ebf3",
        "hover": "#d8e4ef",
        "stroke": "#c8d5e2",
        "text": "#15202d",
        "muted": "#5c6d80",
        "faint": "#8292a3",
        "blue": "#2f73da",
        "green": "#238c5a",
        "red": "#d64255",
        "yellow": "#a66d00",
    },
}


def _resource_path(*parts: str) -> str:
    base = getattr(
        sys,
        "_MEIPASS",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
    )
    return os.path.join(base, *parts)


ICON_PATH = _resource_path("assets", "icon.ico")


class DebugAgent:
    latency_ms = 0.0
    auto_reconnect = False
    is_debug = True
    vhf_installed = True

    def __init__(self, index: int = 1):
        self.index = index
        self.host = f"debug-local-{index}"
        self.port = -index
        self.label = f"Debug PC {index}"
        self.last_status = self.status()

    @property
    def is_connected(self) -> bool:
        return True

    def connect(self, timeout: float = 0.0) -> bool:
        return True

    def disconnect(self, permanent: bool = False):
        return None

    def send(self, command: Command) -> bool:
        _send_local_input(command)
        return True

    def status(self) -> dict:
        x, y = 0, 0
        return {
            "ok": True,
            "cursor": {"x": x, "y": y},
            "screen": {"width": 1920, "height": 1080},
            "virtualScreen": {"x": 0, "y": 0, "width": 1920, "height": 1080},
        }

    def find_image(self, image_data: str, **options) -> dict:
        return {"ok": False, "msg": "Debug Agent does not run image detection."}

    def __str__(self) -> str:
        return f"{self.label} / 현재 PC"


class AgentCard(ctk.CTkFrame):
    def __init__(self, parent, app: "MainWindow", agent):
        self.app = app
        self.agent = agent
        c = app.colors
        super().__init__(parent, fg_color=c["panel"], corner_radius=10, border_width=1, border_color=c["stroke"])
        self.grid_columnconfigure(1, weight=1)

        self._dot = ctk.CTkLabel(self, text="●", width=18, text_color=c["red"])
        self._dot.grid(row=0, column=0, rowspan=2, padx=(12, 5), pady=10)

        self._title = ctk.CTkLabel(
            self,
            text=str(agent),
            anchor="w",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=c["text"],
        )
        self._title.grid(row=0, column=1, sticky="ew", pady=(10, 0))

        self._meta = ctk.CTkLabel(
            self,
            text="연결 끊김",
            anchor="w",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color=c["muted"],
        )
        self._meta.grid(row=1, column=1, sticky="ew", pady=(0, 10))

        self._disconnect = ctk.CTkButton(
            self,
            text="끊기",
            width=54,
            height=28,
            fg_color=c["panel2"],
            hover_color=c["hover"],
            text_color=c["text"],
            corner_radius=7,
            command=lambda: app.disconnect_agent(agent),
        )
        self._disconnect.grid(row=0, column=2, rowspan=2, padx=(8, 12), pady=10)

        for widget in (self, self._dot, self._title, self._meta):
            widget.bind("<Button-1>", lambda _e: app.select_agent(agent))

    def refresh(self, selected: bool):
        c = self.app.colors
        online = bool(getattr(self.agent, "is_connected", False))
        self.configure(fg_color=c["panel2"] if selected else c["panel"], border_color=c["blue"] if selected else c["stroke"])
        self._dot.configure(text_color=c["green"] if online else c["red"])
        self._title.configure(text_color=c["text"])
        if online:
            latency = getattr(self.agent, "latency_ms", -1)
            text = "Debug / VHF OK" if getattr(self.agent, "is_debug", False) else f"{latency:.0f} ms / VHF 확인 필요"
            status = getattr(self.agent, "last_status", {}) or {}
            cursor = status.get("cursor") if isinstance(status, dict) else None
            if isinstance(cursor, dict):
                text += f" / X {cursor.get('x', 0)} Y {cursor.get('y', 0)}"
            self._meta.configure(text=text, text_color=c["muted"])
        else:
            self._meta.configure(text="연결 끊김", text_color=c["red"])


class StatusDock(ctk.CTkFrame):
    def __init__(self, parent, app: "MainWindow"):
        self.app = app
        c = app.colors
        super().__init__(parent, fg_color=c["surface"], corner_radius=12, border_width=1, border_color=c["stroke"])
        self.dropdown: Optional[ctk.CTkFrame] = None
        self._items: list[ctk.CTkLabel] = []
        self._dropdown_signature: tuple = ()
        self.grid_columnconfigure(0, weight=1)
        self._toggle = ctk.CTkButton(
            self,
            text="🖥",
            width=36,
            height=32,
            fg_color=c["panel2"],
            hover_color=c["hover"],
            text_color=c["blue"],
            corner_radius=8,
            command=self.toggle,
        )
        self._toggle.grid(row=0, column=0, padx=(8, 4), pady=6, sticky="e")
        self._health = ctk.CTkLabel(
            self,
            text="●",
            width=24,
            text_color=c["red"],
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self._health.grid(row=0, column=1, padx=(0, 8), pady=6)

    def toggle(self):
        if self.dropdown is not None and self.dropdown.winfo_exists():
            self.dropdown.destroy()
            self.dropdown = None
            self._dropdown_signature = ()
            self._toggle.configure(text="🖥")
            return
        c = self.app.colors
        self.dropdown = ctk.CTkFrame(self.app.root, fg_color=c["surface"], corner_radius=12, border_width=1, border_color=c["stroke"])
        self.dropdown.place(relx=1.0, y=62, x=-18, anchor="ne")
        self._toggle.configure(text="🖥")
        self.refresh(self.app.all_agents())

    def refresh(self, agents: list):
        c = self.app.colors
        self.configure(fg_color=c["surface"], border_color=c["stroke"])
        health_color = self._connection_color(agents)
        health_text = "정상" if health_color == c["green"] else "불안정" if health_color == c["yellow"] else "끊김"
        self._toggle.configure(
            text="🖥",
            fg_color=c["panel2"],
            hover_color=c["hover"],
            text_color=c["blue"],
        )
        self._health.configure(text_color=health_color)
        self._health.configure(text="●")
        self._health.bind("<Button-1>", lambda _e: self.toggle())
        if self.dropdown is None or not self.dropdown.winfo_exists():
            return
        signature = (
            self.app.theme_name,
            health_text,
            tuple((_agent_key(agent), bool(getattr(agent, "is_connected", False)), str(agent)) for agent in agents[:16]),
        )
        if signature == self._dropdown_signature:
            return
        self._dropdown_signature = signature
        for item in self._items:
            item.destroy()
        self._items.clear()
        self.dropdown.configure(fg_color=c["surface"], border_color=c["stroke"])
        summary = ctk.CTkLabel(
            self.dropdown,
            text=f"연결 상태: {health_text}",
            text_color=health_color,
            font=ctk.CTkFont(size=12, weight="bold"),
            padx=10,
            pady=6,
        )
        summary.grid(row=0, column=0, columnspan=4, padx=6, pady=(8, 2), sticky="ew")
        self._items.append(summary)
        visible = agents[:16]
        cols = 4
        for idx, agent in enumerate(visible):
            online = bool(getattr(agent, "is_connected", False))
            row = 1 + idx // cols
            label = ctk.CTkLabel(
                self.dropdown,
                text=f"{'●' if online else '○'} {agent}",
                fg_color=c["panel"],
                corner_radius=8,
                text_color=c["green"] if online else c["red"],
                font=ctk.CTkFont(family="Consolas", size=10),
                padx=8,
                pady=5,
            )
            label.grid(row=row, column=idx % cols, padx=6, pady=6, sticky="ew")
            self._items.append(label)

    def _connection_color(self, agents: list) -> str:
        c = self.app.colors
        if not agents:
            return c["red"]
        if any(not bool(getattr(agent, "is_connected", False)) for agent in agents):
            return c["red"]
        for agent in agents:
            latency = float(getattr(agent, "latency_ms", -1) or -1)
            if not getattr(agent, "is_debug", False) and (latency < 0 or latency >= 800):
                return c["yellow"]
        return c["green"]


class ScreenTile(ctk.CTkFrame):
    def __init__(self, parent, app: "MainWindow", agent):
        self.app = app
        self.agent = agent
        self._remote_w = 16
        self._remote_h = 9
        self._frame: Optional[bytes] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._status_text = "대기"
        self._editing = False
        self._selected = False
        self._render_pending = False
        self._last_render_time = 0.0
        self._min_render_interval = 0.1
        self._drag_start: Optional[tuple[int, int]] = None
        self._dragging = False
        self._lock = threading.Lock()
        c = app.colors
        super().__init__(parent, fg_color=c["panel"], corner_radius=12, border_width=1, border_color=c["stroke"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, bg="#05080c", height=240, highlightthickness=0, cursor="hand2")
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self._image_id = self.canvas.create_image(0, 0, anchor="nw")
        for widget in (self, self.canvas):
            widget.bind("<Button-1>", self._on_press)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<Configure>", lambda _e: self._schedule_render(force=True))

        self.name_badge = ctk.CTkLabel(
            self,
            text=self.display_name(),
            fg_color="#07140d",
            corner_radius=8,
            padx=9,
            pady=4,
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=c["green"],
        )
        self.name_badge.bind("<Button-1>", self._on_press)
        self.name_badge.bind("<B1-Motion>", self._on_drag)
        self.name_badge.bind("<ButtonRelease-1>", self._on_release)

        self.edit_panel = ctk.CTkFrame(self, fg_color=c["surface"], corner_radius=10, border_width=1, border_color=c["stroke"])
        self.edit_panel.grid_columnconfigure(0, weight=1)
        self.name_entry = _entry(self.edit_panel, app, "", width=180)
        self.name_entry.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.name_entry.bind("<Return>", lambda _e: self.commit_name())
        self.name_entry.bind("<FocusOut>", lambda _e: self.commit_name())
        self.set_edit_mode(False)
        if getattr(agent, "is_debug", False):
            self.set_status("Debug 화면 준비 중")
            self.after(50, lambda: self.on_image(_debug_placeholder("Waiting for local screen capture.")))

    def display_name(self) -> str:
        return self.app.get_monitor_name(self.agent)

    def _select_from_event(self, event):
        self.app.select_monitor_agent(self.agent, multi=bool(event.state & 0x0001))

    def _on_press(self, event):
        self._select_from_event(event)
        if self._editing:
            self._drag_start = (event.x_root, event.y_root)
            self._dragging = False
            self.canvas.configure(cursor="fleur")
        return "break"

    def _on_drag(self, event):
        if not self._editing or self._drag_start is None:
            return
        dx = abs(event.x_root - self._drag_start[0])
        dy = abs(event.y_root - self._drag_start[1])
        if dx + dy >= 8:
            self._dragging = True
            self.configure(border_color=self.app.colors["yellow"])
        return "break"

    def _on_release(self, event):
        if self._editing and self._dragging:
            self.app.reorder_monitor_tile_to_point(self.agent, event.x_root, event.y_root)
        self._drag_start = None
        self._dragging = False
        self.canvas.configure(cursor="fleur" if self._editing else "hand2")
        self.set_selected(self._selected)
        return "break"

    def _on_double_click(self, event):
        if not self._editing:
            self.app.open_monitor(self.agent)
        return "break"

    def refresh_name(self):
        name = self.display_name()
        self.name_badge.configure(text=name)
        if self.name_entry.get() != name:
            self.name_entry.delete(0, "end")
            self.name_entry.insert(0, name)

    def commit_name(self):
        name = self.name_entry.get().strip() or str(self.agent)
        self.app.set_monitor_name(self.agent, name)
        self.refresh_name()

    def set_edit_mode(self, editing: bool):
        self._editing = editing
        self.refresh_name()
        if editing:
            self.canvas.configure(cursor="fleur")
            self.name_badge.place(x=14, y=14, anchor="nw")
            self.edit_panel.place(relx=0.5, rely=1.0, y=-14, anchor="s", relwidth=0.94)
        else:
            self.canvas.configure(cursor="hand2")
            self.name_badge.place_forget()
            self.edit_panel.place_forget()

    def set_selected(self, selected: bool):
        self._selected = selected
        c = self.app.colors
        self.configure(border_width=4 if selected else 1, border_color=c["blue"] if selected else c["stroke"], fg_color=c["panel"])
        if self._editing:
            self.name_badge.configure(text_color=c["green"])

    def apply_theme(self):
        c = self.app.colors
        self.canvas.configure(bg="#05080c")
        self.edit_panel.configure(fg_color=c["surface"], border_color=c["stroke"])
        self.name_badge.configure(fg_color="#07140d", text_color=c["green"])
        self.set_selected(self._selected)

    def set_status(self, text: str):
        self._status_text = text

    def set_monitor_load(self, tile_count: int):
        self._min_render_interval = 0.22 if tile_count >= 9 else 0.16 if tile_count >= 5 else 0.1

    def on_frame(self, jpeg: bytes, w: int, h: int):
        with self._lock:
            self._frame = jpeg
            self._remote_w = max(1, w)
            self._remote_h = max(1, h)
        self._schedule_render()

    def on_image(self, image: Image.Image):
        image = _rgb_image(image)
        with self._lock:
            self._remote_w, self._remote_h = image.size
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=70)
            self._frame = buf.getvalue()
        self._schedule_render()

    def _schedule_render(self, force: bool = False):
        if self._render_pending:
            return
        delay_ms = 0
        if not force:
            elapsed = time.monotonic() - self._last_render_time
            delay_ms = max(0, int((self._min_render_interval - elapsed) * 1000))
        self._render_pending = True
        self.after(delay_ms, self._render_frame)

    def _render_frame(self):
        self._render_pending = False
        with self._lock:
            frame = self._frame
        if not frame:
            return
        try:
            cw = max(1, self.canvas.winfo_width())
            ch = max(1, self.canvas.winfo_height())
            scale = min(cw / self._remote_w, ch / self._remote_h)
            width = max(1, int(self._remote_w * scale))
            height = max(1, int(self._remote_h * scale))
            x = (cw - width) // 2
            y = (ch - height) // 2
            image = Image.open(io.BytesIO(frame))
            image.draft("RGB", (width, height))
            image = image.resize((width, height), Image.BILINEAR)
            self._photo = ImageTk.PhotoImage(image)
            self.canvas.itemconfigure(self._image_id, image=self._photo)
            self.canvas.coords(self._image_id, x, y)
            self._last_render_time = time.monotonic()
        except Exception as exc:
            self.set_status(f"표시 오류: {exc.__class__.__name__}")


class LocalScreenPump:
    def __init__(self, tile: ScreenTile):
        self.tile = tile
        self.running = False

    def start(self) -> bool:
        self.running = True
        self.tile.set_status("Debug 캡처 준비 중")
        self._tick()
        return True

    def stop(self):
        self.running = False

    def _tick(self):
        if not self.running:
            return
        try:
            try:
                image = ImageGrab.grab(all_screens=True)
            except TypeError:
                image = ImageGrab.grab()
            image.thumbnail((960, 540), Image.BILINEAR)
            self.tile.on_image(image)
            self.tile.set_status("현재 PC 화면")
        except Exception as exc:
            self.tile.on_image(_debug_placeholder(str(exc)))
            self.tile.set_status(f"캡처 실패: {exc.__class__.__name__}")
        wait = 1400 if self.tile._min_render_interval >= 0.22 else 900 if self.tile._min_render_interval >= 0.16 else 500
        self.tile.after(wait, self._tick)


class ScreenWall(ctk.CTkFrame):
    def __init__(self, parent, app: "MainWindow"):
        self.app = app
        c = app.colors
        super().__init__(parent, fg_color="transparent")
        self._tiles: dict[str, ScreenTile] = {}
        self._agents: dict[str, object] = {}
        self._clients: dict[str, object] = {}
        self._preset_names: list[str] = []
        self._preset_delete_mode = False
        self._preset_picker: Optional[ctk.CTkFrame] = None
        self._edit_mode = False
        self._preset_height = 26
        self.columns = 1
        self._layout_signature: tuple[str, ...] = ()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(5, 4))
        head.grid_columnconfigure(1, weight=1)
        self.select_all_var = tk.BooleanVar(master=app.root, value=False)
        ctk.CTkCheckBox(
            head,
            text="전체선택",
            variable=self.select_all_var,
            command=self.toggle_select_all,
            width=92,
            checkbox_width=16,
            checkbox_height=16,
            fg_color=c["blue"],
            hover_color=c["hover"],
            text_color=c["muted"],
        ).grid(row=0, column=0, sticky="w")
        self.count = ctk.CTkLabel(head, text="0대", anchor="e", text_color=c["muted"])
        self.count.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.edit_button = _button(head, app, "편집", self.toggle_edit_mode, width=58, color=c["panel2"])
        self.edit_button.grid(row=0, column=2, sticky="e")

        self.tile_grid = ctk.CTkFrame(self, fg_color="transparent")
        self.tile_grid.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 4))
        self.tile_grid.grid_columnconfigure(0, weight=1)
        self.tile_grid.bind("<Button-1>", lambda _e: self.clear_selection())
        self.empty = ctk.CTkFrame(self.tile_grid, fg_color=c["panel"], corner_radius=12, border_width=1, border_color=c["stroke"])
        self.empty.grid_columnconfigure(0, weight=1)
        self.empty.bind("<Button-1>", lambda _e: self.clear_selection())
        ctk.CTkLabel(self.empty, text="연결된 PC가 없습니다", font=ctk.CTkFont(size=16, weight="bold"), text_color=c["text"]).grid(row=0, column=0, pady=(28, 6))
        self.empty_hint = ctk.CTkLabel(self.empty, text="연결된 Agent가 화면에 표시됩니다.", text_color=c["muted"])
        self.empty_hint.grid(row=1, column=0, pady=(0, 14))
        self.empty_debug_button = _button(self.empty, app, "Debug PC 추가", app.add_debug_from_monitor, width=130, color=c["blue"])
        self.workflow_bar = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.workflow_bar.configure(height=self._preset_height)
        self.workflow_bar.grid(row=2, column=0, sticky="ew")
        self.workflow_bar.grid_propagate(False)
        self.preset_strip = ctk.CTkFrame(self.workflow_bar, fg_color=c["surface"], corner_radius=8, height=24)
        self.preset_strip.pack(side="left", fill="x", expand=True, padx=(14, 14), pady=(0, 2))
        self.preset_strip.pack_propagate(False)
        self.preset_items = ctk.CTkFrame(self.preset_strip, fg_color="transparent")
        self.preset_items.pack(side="left", fill="x", expand=True)
        self.preset_trash_slot = ctk.CTkFrame(self.preset_strip, fg_color="transparent", width=42)
        self.preset_trash_slot.pack(side="right", fill="y")
        self.preset_trash_slot.pack_propagate(False)
        self.refresh_workflows()

    def sync(self, agents: list):
        online = [a for a in agents if getattr(a, "is_connected", False)]
        keys = {_agent_key(a) for a in online}
        changed = False
        self.app.monitor_order = [key for key in self.app.monitor_order if key in keys]
        for agent in online:
            key = _agent_key(agent)
            if key not in self.app.monitor_order:
                self.app.monitor_order.append(key)
                changed = True
        online.sort(key=lambda a: self.app.monitor_order.index(_agent_key(a)) if _agent_key(a) in self.app.monitor_order else 9999)
        ordered_keys = tuple(_agent_key(agent) for agent in online)
        self._agents = {_agent_key(agent): agent for agent in online}
        for key in list(self._clients):
            if key not in keys:
                self._clients[key].stop()
                del self._clients[key]
                changed = True
        for key in list(self._tiles):
            if key not in keys:
                self._tiles[key].destroy()
                del self._tiles[key]
                changed = True
        self.app.monitor_selected_keys.intersection_update(keys)
        if self.app.debug_agents:
            self.empty_hint.configure(text="Debug PC를 추가하면 현재 PC 화면으로 모니터링 그리드를 확인할 수 있습니다.")
            self.empty_debug_button.grid(row=2, column=0, pady=(0, 28))
        else:
            self.empty_hint.configure(text="연결된 Agent가 화면에 표시됩니다.")
            self.empty_debug_button.grid_forget()
        for agent in online:
            key = _agent_key(agent)
            if key not in self._tiles:
                self._tiles[key] = ScreenTile(self.tile_grid, self.app, agent)
                self._tiles[key].set_edit_mode(self._edit_mode)
                changed = True
            self._tiles[key].set_monitor_load(len(online))
            if key not in self._clients:
                tile = self._tiles[key]
                if getattr(agent, "is_debug", False):
                    client = LocalScreenPump(tile)
                    tile.set_status("Debug / 현재 PC")
                else:
                    client = ScreenClient(agent.host, int(agent.port) + 1, self.app.secret, tile.on_frame)
                if client.start():
                    self._clients[key] = client
        self.count.configure(text=f"{len(online)}대")
        if changed or ordered_keys != self._layout_signature:
            self._layout()
            self._layout_signature = ordered_keys
        self.select_keys(self.app.monitor_selected_keys)

    def toggle_edit_mode(self):
        self.set_edit_mode(not self._edit_mode)

    def set_edit_mode(self, enabled: bool):
        self._edit_mode = enabled
        self.edit_button.configure(text="완료" if enabled else "편집")
        for tile in self._tiles.values():
            tile.set_edit_mode(enabled)
        self.app.set_status("모니터링 편집 모드" if enabled else "모니터링 편집 종료")

    def select(self, agent):
        key = _agent_key(agent)
        if key:
            self.app.monitor_selected_keys = {key}
        self.select_keys(self.app.monitor_selected_keys)

    def select_keys(self, keys: set[str]):
        for tile_key, tile in self._tiles.items():
            tile.set_selected(tile_key in keys)
        self.select_all_var.set(bool(self._tiles) and len(keys) == len(self._tiles))

    def toggle_select_all(self):
        if self.select_all_var.get():
            self.select_all()
        else:
            self.clear_selection()

    def select_all(self):
        self.app.monitor_selected_keys = set(self._tiles.keys())
        self.select_keys(self.app.monitor_selected_keys)
        self.app.set_status(f"{len(self.app.monitor_selected_keys)}대 선택됨")

    def clear_selection(self):
        self.app.monitor_selected_keys.clear()
        self.app.selected_agent = None
        self.select_keys(self.app.monitor_selected_keys)
        self.app.set_status("선택 해제됨")

    def selected_agents(self) -> list:
        return [self._agents[key] for key in self.app.monitor_order if key in self.app.monitor_selected_keys and key in self._agents]

    def reorder_tile_to_point(self, agent, x_root: int, y_root: int):
        source_key = _agent_key(agent)
        if source_key not in self.app.monitor_order:
            return
        target_key = ""
        for key, tile in self._tiles.items():
            if key == source_key:
                continue
            left = tile.winfo_rootx()
            top = tile.winfo_rooty()
            right = left + tile.winfo_width()
            bottom = top + tile.winfo_height()
            if left <= x_root <= right and top <= y_root <= bottom:
                target_key = key
                break
        if not target_key:
            return
        order = [key for key in self.app.monitor_order if key in self._tiles]
        old_idx = order.index(source_key)
        new_idx = order.index(target_key)
        if old_idx == new_idx:
            return
        order.pop(old_idx)
        if old_idx < new_idx:
            new_idx -= 1
        order.insert(new_idx, source_key)
        self.app.monitor_order = order + [key for key in self.app.monitor_order if key not in order]
        self.app.cfg["monitor_order"] = self.app.monitor_order
        save_config(self.app.cfg)
        self._layout_signature = ()
        self._layout()
        self.select_keys(self.app.monitor_selected_keys)
        self.app.set_status("모니터링 위치 변경됨")

    def apply_theme(self):
        c = self.app.colors
        self.configure(fg_color=c["bg"])
        self.count.configure(text_color=c["muted"])
        self.edit_button.configure(fg_color=c["panel2"], hover_color=c["hover"], text_color=c["text"])
        self.empty.configure(fg_color=c["panel"], border_color=c["stroke"])
        self.empty_hint.configure(text_color=c["muted"])
        self.workflow_bar.configure(fg_color="transparent")
        self.preset_strip.configure(fg_color=c["surface"])
        for tile in self._tiles.values():
            tile.apply_theme()
        self.refresh_workflows()
        self.select_keys(self.app.monitor_selected_keys)

    def refresh_workflows(self):
        for child in self.preset_items.winfo_children():
            child.destroy()
        for child in self.preset_trash_slot.winfo_children():
            child.destroy()
        c = self.app.colors
        if not self._preset_names:
            ctk.CTkLabel(self.preset_items, text="프리셋 없음", text_color=c["muted"], font=ctk.CTkFont(size=10), height=18).pack(side="left", padx=(8, 5), pady=3)
        for name in list(self._preset_names):
            row = ctk.CTkFrame(self.preset_items, fg_color="transparent")
            row.pack(side="left", padx=2, pady=2)
            _button(row, self.app, name, lambda n=name: self.app.run_monitor_workflow(n), width=88, height=20, color=c["panel"]).pack(side="left")
            if self._preset_delete_mode:
                _button(row, self.app, "X", lambda n=name: self.remove_preset(n), width=22, height=20, color=c["red"]).pack(side="left", padx=(2, 0))
        self.add_preset_button = _button(self.preset_items, self.app, "+", self.show_preset_picker, width=28, height=20, color=c["panel2"])
        self.add_preset_button.pack(side="left", padx=(4, 3), pady=2)
        _button(self.preset_trash_slot, self.app, "🗑", self.toggle_preset_delete_mode, width=36, height=24, color=c["panel2"]).pack(side="right", padx=(0, 0), pady=0)

    def show_preset_picker(self):
        if self._preset_picker is not None and self._preset_picker.winfo_exists():
            self._preset_picker.destroy()
            self._preset_picker = None
            return
        self.app.reload_workflows_from_disk(update_ui=False)
        c = self.app.colors
        self._preset_picker = ctk.CTkToplevel(self.app.root)
        self._preset_picker.withdraw()
        self._preset_picker.overrideredirect(True)
        self._preset_picker.transient(self.app.root)
        self._preset_picker.configure(fg_color=c["surface"])
        self._preset_picker.bind("<Escape>", lambda _e: self._close_preset_picker())
        panel = ctk.CTkFrame(self._preset_picker, fg_color=c["surface"], corner_radius=10, border_width=1, border_color=c["stroke"])
        panel.pack(fill="both", expand=True)
        workflows = [w.get("name") for w in self.app.cfg.get("workflows", []) if w.get("name")]
        available = [name for name in workflows if name not in self._preset_names]
        if not workflows:
            ctk.CTkLabel(panel, text="저장된 워크플로우 없음", text_color=c["muted"]).pack(padx=14, pady=12)
            self._place_preset_picker()
            return
        if not available:
            ctk.CTkLabel(panel, text="모든 워크플로우가 추가됨", text_color=c["muted"]).pack(padx=14, pady=12)
            self._place_preset_picker()
            return
        for name in available:
            _button(panel, self.app, name, lambda n=name: self.add_preset(n), width=180, height=28, color=c["panel"]).pack(fill="x", padx=8, pady=(8, 0))
        ctk.CTkFrame(panel, height=8, fg_color="transparent").pack()
        self._place_preset_picker()

    def _place_preset_picker(self):
        owner = getattr(self, "add_preset_button", None)
        if self._preset_picker is None or not self._preset_picker.winfo_exists():
            return
        self.app.root.update_idletasks()
        self._preset_picker.update_idletasks()
        width = max(200, self._preset_picker.winfo_reqwidth())
        height = max(46, self._preset_picker.winfo_reqheight())
        root_x = self.app.root.winfo_rootx()
        root_y = self.app.root.winfo_rooty()
        root_w = self.app.root.winfo_width()
        if owner is None or not owner.winfo_exists():
            x = root_x + 14
            y = root_y + self.app.root.winfo_height() - height - self._preset_height - 8
        else:
            x = owner.winfo_rootx() + owner.winfo_width() + 6
            y = owner.winfo_rooty() - height - 6
        x = min(max(root_x + 8, x), root_x + root_w - width - 8)
        y = max(root_y + 64, y)
        self._preset_picker.geometry(f"{width}x{height}+{x}+{y}")
        self._preset_picker.deiconify()
        self._preset_picker.lift()

    def _close_preset_picker(self):
        if self._preset_picker is not None and self._preset_picker.winfo_exists():
            self._preset_picker.destroy()
        self._preset_picker = None

    def add_preset(self, name: str):
        if name not in self._preset_names:
            self._preset_names.append(name)
        self._close_preset_picker()
        self.refresh_workflows()

    def remove_preset(self, name: str):
        self._preset_names = [n for n in self._preset_names if n != name]
        self.refresh_workflows()

    def toggle_preset_delete_mode(self):
        self._preset_delete_mode = not self._preset_delete_mode
        self.refresh_workflows()

    def stop_all(self):
        for client in self._clients.values():
            client.stop()
        self._clients.clear()

    def _layout(self):
        if not self._tiles:
            self.empty.grid(row=0, column=0, padx=8, pady=8, sticky="ew")
            return
        self.empty.grid_forget()
        count = max(1, len(self._tiles))
        cols = 1 if count == 1 else 2 if count <= 4 else 3 if count <= 9 else 4
        self.columns = cols
        for col in range(4):
            self.tile_grid.grid_columnconfigure(col, weight=1 if col < cols else 0, uniform="monitor" if col < cols else "")
        for row in range(8):
            self.tile_grid.grid_rowconfigure(row, weight=0)
        ordered_tiles = [self._tiles[key] for key in self.app.monitor_order if key in self._tiles]
        for idx, tile in enumerate(ordered_tiles):
            self.tile_grid.grid_rowconfigure(idx // cols, weight=1)
            tile.grid(row=idx // cols, column=idx % cols, padx=6, pady=6, sticky="nsew")


class WorkflowStepRow(ctk.CTkFrame):
    def __init__(self, parent, app: "MainWindow", index: int, step: Optional[dict] = None):
        self.app = app
        c = app.colors
        super().__init__(parent, fg_color=c["panel"], corner_radius=10, border_width=1, border_color=c["stroke"])
        self.index = index
        self.entries: dict[str, ctk.CTkEntry] = {}
        self.menus: dict[str, ctk.CTkOptionMenu] = {}
        self.action_var = tk.StringVar(value=(step or {}).get("type", "대기"))
        self.grid_columnconfigure(2, weight=1)
        self.num = ctk.CTkLabel(self, text=f"{index + 1:02d}", width=42, font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), text_color=c["blue"])
        self.num.grid(row=0, column=0, padx=(10, 4), pady=10)
        ctk.CTkOptionMenu(
            self,
            values=ACTION_TYPES,
            variable=self.action_var,
            width=140,
            fg_color=c["panel2"],
            button_color=c["blue"],
            button_hover_color=c["hover"],
            dropdown_fg_color=c["panel"],
            command=lambda _v: self.rebuild(),
        ).grid(row=0, column=1, padx=6, pady=10)
        self.fields = ctk.CTkFrame(self, fg_color="transparent")
        self.fields.grid(row=0, column=2, sticky="ew", padx=6, pady=8)
        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.grid(row=0, column=3, padx=(6, 10), pady=8)
        _mini_button(tools, app, "↑", lambda: app.move_step(self, -1)).pack(side="left", padx=2)
        _mini_button(tools, app, "↓", lambda: app.move_step(self, 1)).pack(side="left", padx=2)
        _mini_button(tools, app, "삭제", lambda: app.delete_step(self), width=52, color=c["red"]).pack(side="left", padx=2)
        self.rebuild()
        if step:
            self.set_step(step)

    def renumber(self, index: int):
        self.index = index
        self.num.configure(text=f"{index + 1:02d}")

    def get_step(self) -> dict:
        data: dict[str, object] = {"type": self.action_var.get()}
        for key, entry in self.entries.items():
            value = entry.get().strip()
            if key in {"key", "mods", "image_path"}:
                data[key] = value
            elif key in {"ms", "duration", "timeout", "interval"}:
                data[key] = _seconds_to_ms(value)
            elif key in {"jitter", "threshold", "offset_x", "offset_y"}:
                data[key] = _float(value, 0.0)
            else:
                data[key] = _int(value, 0)
        for key, menu in self.menus.items():
            data[key] = menu.get()
        return data

    def set_step(self, step: dict):
        self.action_var.set(step.get("type", "대기"))
        self.rebuild()
        for key, value in step.items():
            if key in self.entries:
                self.entries[key].delete(0, "end")
                if key in {"ms", "duration", "timeout", "interval"}:
                    self.entries[key].insert(0, _format_seconds(_ms_to_seconds(value)))
                elif key == "jitter":
                    self.entries[key].insert(0, f"{_float(value, 0.0):.1f}")
                else:
                    self.entries[key].insert(0, str(value))
            if key in self.menus:
                self.menus[key].set(_display_key(value) if key == "key" else str(value))

    def rebuild(self):
        for child in self.fields.winfo_children():
            child.destroy()
        self.entries.clear()
        self.menus.clear()
        kind = self.action_var.get()
        if kind == "대기":
            self.add_entry("ms", "0.5")
        elif kind == "키 입력":
            self.add_entry("key", "A")
            self.add_entry("mods", "ctrl+shift")
        elif kind == "마우스 이동":
            self.add_entry("x", "960")
            self.add_entry("y", "540")
        elif kind == "자연 이동":
            self.add_entry("x", "960")
            self.add_entry("y", "540")
            self.add_entry("duration", "0.65")
            self.add_entry("jitter", "3.0")
        elif kind == "클릭":
            self.add_menu("button", BUTTON_VALUES)
        elif kind == "랜덤 클릭":
            self.add_entry("x1", "850")
            self.add_entry("y1", "450")
            self.add_entry("x2", "1070")
            self.add_entry("y2", "630")
            self.add_menu("button", BUTTON_VALUES)
        elif kind == "스크롤":
            self.add_entry("delta", "-120")
        elif kind == "이미지 찾기":
            self.add_entry("image_path", "")
            self.add_entry("threshold", "0.92")
            self.add_entry("timeout", "3.0")
            self.add_menu("match_mode", ["similar", "exact"])
            self.add_entry("offset_x", "0.0")
            self.add_entry("offset_y", "0.0")
        elif kind == "이미지 대기":
            self.add_entry("image_path", "")
            self.add_entry("threshold", "0.92")
            self.add_entry("timeout", "10.0")
            self.add_menu("match_mode", ["similar", "exact"])
        elif kind == "이미지 감지":
            self.add_entry("image_path", "")
            self.add_entry("threshold", "0.92")
            self.add_entry("interval", "0.5")
            self.add_entry("timeout", "1.2")
            self.add_menu("match_mode", ["similar", "exact"])
            self.add_menu("detect_action", ["click", "stop_agent", "stop_all", "notify"])
            self.add_entry("offset_x", "0.0")
            self.add_entry("offset_y", "0.0")

    def add_entry(self, key: str, value: str):
        idx = len(self.entries) + len(self.menus)
        frame = ctk.CTkFrame(self.fields, fg_color="transparent")
        frame.grid(row=0, column=idx, padx=4)
        ctk.CTkLabel(frame, text=FIELD_LABELS.get(key, key), text_color=self.app.colors["faint"], font=ctk.CTkFont(size=10)).pack(anchor="w")
        width = 280 if key == "image_path" else 136 if key == "mods" else 100
        entry = _entry(frame, self.app, "", width=width)
        entry.insert(0, value)
        entry.pack()
        if key == "image_path":
            _mini_button(frame, self.app, "찾기", lambda e=entry: self.pick_image(e), width=54).pack(pady=(5, 0), anchor="w")
        self.entries[key] = entry

    def pick_image(self, entry: ctk.CTkEntry):
        path = filedialog.askopenfilename(
            title="탐색 이미지 선택",
            filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.bmp"), ("All files", "*.*")],
        )
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def add_menu(self, key: str, values: list[str]):
        idx = len(self.entries) + len(self.menus)
        frame = ctk.CTkFrame(self.fields, fg_color="transparent")
        frame.grid(row=0, column=idx, padx=4)
        ctk.CTkLabel(frame, text=FIELD_LABELS.get(key, key), text_color=self.app.colors["faint"], font=ctk.CTkFont(size=10)).pack(anchor="w")
        menu = ctk.CTkOptionMenu(frame, values=values, width=120 if key == "key" else 100, fg_color=self.app.colors["bg"], button_color=self.app.colors["blue"])
        menu.set(values[0])
        menu.pack()
        self.menus[key] = menu


class MainWindow:
    def __init__(self, manager: AgentManager, secret: str = "change-this-secret"):
        self.manager = manager
        self.secret = secret
        self.cfg = load_config()
        self.theme_name = self.cfg.get("theme", "dark")
        self.colors = THEMES.get(self.theme_name, THEMES["dark"])
        self.cards: list[AgentCard] = []
        self._agent_card_keys: list[str] = []
        self.palette_frames: dict[str, object] = {}
        self._last_agent_signature: tuple = ()
        self.workflow_rows: list[WorkflowStepRow] = []
        self.debug_logs: list[str] = []
        self.debug_agents: list[DebugAgent] = []
        self.selected_agent = None
        self.wall: Optional[ScreenWall] = None
        self.settings_dropdown: Optional[ctk.CTkFrame] = None
        self.monitor_order: list[str] = list(self.cfg.get("monitor_order", []))
        self.monitor_selected_keys: set[str] = set()
        self.monitor_names: dict[str, str] = dict(self.cfg.get("monitor_names", {}))
        self.current_palette = "연결"
        self._active_palette: Optional[str] = None
        self.macro_stop = False
        self.last_positions: dict[str, tuple[int, int]] = {}

        self.root = ctk.CTk()
        self.mirror_mode = tk.BooleanVar(master=self.root, value=False)
        self.root.title("Rice Harvester Controller")
        self.root.geometry("1380x820")
        self.root.minsize(1180, 720)
        self.root.configure(fg_color=self.colors["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Alt-F12>", lambda _e: self.toggle_mirror())

        if os.path.exists(ICON_PATH):
            try:
                self.root.iconbitmap(ICON_PATH)
            except Exception:
                pass

        self.manager.on_status_change = lambda _agent: self.root.after(0, self.refresh_all)
        self.build()
        self.restore_agents()
        self.root.after(1000, self.tick)

    def all_agents(self) -> list:
        agents = list(self.manager.all_agents())
        agents.extend(self.debug_agents)
        return agents

    def add_debug_agent(self) -> DebugAgent:
        used = {agent.index for agent in self.debug_agents}
        index = 1
        while index in used:
            index += 1
        agent = DebugAgent(index)
        self.debug_agents.append(agent)
        self.debug_logs.append(f"Debug agent added: {agent.label}")
        self.debug_badge.configure(text=f"DEBUG MODE ({len(self.debug_agents)})")
        return agent

    def add_debug_from_monitor(self):
        if not self.debug_agents:
            self.set_status("Debug 모드에서만 Debug PC를 추가할 수 있습니다.")
            return
        agent = self.add_debug_agent()
        self.select_agent(agent)
        self.set_status(f"{agent.label} 추가됨")
        if self.wall is not None and self.wall.winfo_exists():
            self.wall.sync(self.all_agents())
            self.wall.select(agent)
        else:
            self.refresh_all()

    def build(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self.build_left_panel()
        self.build_topbar()
        self.palette = ctk.CTkFrame(self.root, fg_color=self.colors["bg"], corner_radius=0)
        self.palette.grid(row=1, column=1, sticky="nsew")
        self.palette.grid_columnconfigure(0, weight=1)
        self.palette.grid_rowconfigure(0, weight=1)
        self.status = ctk.CTkLabel(self.root, text="준비됨", anchor="w", fg_color=self.colors["surface"], text_color=self.colors["muted"], height=30)
        self.status.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.show_palette("연결")

    def build_left_panel(self):
        c = self.colors
        self.left = ctk.CTkFrame(self.root, width=250, fg_color=c["surface"], corner_radius=0)
        self.left.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.left.grid_propagate(False)
        self.left.grid_columnconfigure(0, weight=1)
        brand = ctk.CTkFrame(self.left, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 22))
        r = ctk.CTkLabel(brand, text="R", font=ctk.CTkFont(size=24, weight="bold"), text_color=c["blue"], cursor="hand2")
        r.pack(side="left")
        r.bind("<Button-1>", lambda _e: self.toggle_debug())
        ctk.CTkLabel(brand, text="ice Harvester", font=ctk.CTkFont(size=21, weight="bold"), text_color=c["text"]).pack(side="left")
        self.nav_buttons = {}
        for idx, name in enumerate(("연결", "모니터링", "워크플로우")):
            btn = ctk.CTkButton(
                self.left,
                text=name,
                height=44,
                fg_color=c["panel2"] if name == self.current_palette else "transparent",
                hover_color=c["hover"],
                text_color=c["text"],
                anchor="w",
                corner_radius=10,
                command=lambda n=name: self.show_palette(n),
            )
            btn.grid(row=1 + idx, column=0, sticky="ew", padx=14, pady=5)
            self.nav_buttons[name] = btn

        self.debug_badge = ctk.CTkLabel(self.left, text="", text_color=c["yellow"], anchor="w")
        self.debug_badge.grid(row=5, column=0, sticky="ew", padx=18, pady=(20, 0))

    def build_topbar(self):
        c = self.colors
        self.topbar = ctk.CTkFrame(self.root, fg_color=c["bg"], corner_radius=0)
        self.topbar.grid(row=0, column=1, sticky="ew", padx=18, pady=(14, 6))
        self.topbar.grid_columnconfigure(0, weight=1)
        self.title = ctk.CTkLabel(self.topbar, text="연결", anchor="w", font=ctk.CTkFont(size=24, weight="bold"), text_color=c["text"])
        self.title.grid(row=0, column=0, sticky="ew")
        controls = ctk.CTkFrame(self.topbar, fg_color="transparent")
        controls.grid(row=0, column=1, sticky="e")
        _button(controls, self, "⚙", self.open_settings, width=38, height=34, color=c["panel2"], text_color=c["blue"]).pack(side="left", padx=3)
        _button(controls, self, self.theme_icon(), self.toggle_theme, width=38, height=34, color=c["panel2"], text_color=c["yellow"]).pack(side="left", padx=3)
        self.theme_button = controls.winfo_children()[-1]
        self.status_dock = StatusDock(controls, self)
        self.status_dock.pack(side="left", padx=(6, 0))

    def theme_icon(self) -> str:
        return "☀" if self.theme_name == "dark" else "◐"

    def show_palette(self, name: str):
        self.current_palette = name
        for frame in self.palette_frames.values():
            if frame.winfo_exists():
                frame.grid_forget()
        self.title.configure(text=name)
        for key, btn in self.nav_buttons.items():
            btn.configure(fg_color=self.colors["panel2"] if key == name else "transparent")
        frame = self.palette_frames.get(name)
        if frame is None or not frame.winfo_exists():
            if name == "연결":
                frame = self.build_connect_palette()
            elif name == "모니터링":
                frame = self.build_monitor_palette()
            else:
                frame = self.build_workflow_palette()
            self.palette_frames[name] = frame
        frame.grid(row=0, column=0, sticky="nsew")
        self._active_palette = name
        if name == "연결":
            self.rebuild_agent_cards()
        elif name == "모니터링":
            if self.wall is not None and self.wall.winfo_exists():
                self.wall.sync(self.all_agents())
                if self.monitor_selected_keys:
                    self.wall.select_keys(self.monitor_selected_keys)
                else:
                    self.wall.select(self.selected_agent)

    def build_connect_palette(self):
        c = self.colors
        frame = ctk.CTkFrame(self.palette, fg_color="transparent")
        frame.configure(border_width=0)
        frame.grid_columnconfigure(0, weight=1)
        connect = _section(frame, self)
        connect.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 0))
        connect.grid_columnconfigure(0, weight=1)
        self.host_entry = _entry(connect, self, "IP 또는 호스트")
        self.host_entry.grid(row=0, column=0, sticky="ew", padx=(14, 8), pady=14)
        self.port_entry = _entry(connect, self, str(DEFAULT_PORT), width=90)
        self.port_entry.grid(row=0, column=1, padx=(0, 8), pady=14)
        _button(connect, self, "연결", self.connect_from_form, width=96, color=c["green"], text_color="#07140d").grid(row=0, column=2, padx=(0, 14), pady=14)

        self.agent_list = ctk.CTkScrollableFrame(frame, fg_color="transparent", scrollbar_button_color=c["stroke"], scrollbar_button_hover_color=c["hover"])
        self.agent_list.grid(row=1, column=0, sticky="nsew", padx=22, pady=(16, 18))
        self.agent_list.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        self.rebuild_agent_cards()
        return frame

    def build_monitor_palette(self):
        self.wall = ScreenWall(self.palette, self)
        self.wall.sync(self.all_agents())
        if self.monitor_selected_keys:
            self.wall.select_keys(self.monitor_selected_keys)
        else:
            self.wall.select(self.selected_agent)
        return self.wall

    def build_workflow_palette(self):
        c = self.colors
        frame = ctk.CTkFrame(self.palette, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(frame, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 12))
        bar.grid_columnconfigure(1, weight=1)
        self.workflow_name = _entry(bar, self, "워크플로우 이름", width=190)
        self.workflow_name.grid(row=0, column=0, padx=(0, 8))
        self.workflow_var = tk.StringVar(value=self.workflow_names()[0])
        self.workflow_menu = ctk.CTkOptionMenu(bar, variable=self.workflow_var, values=self.workflow_names(), fg_color=c["panel"], button_color=c["blue"], dropdown_fg_color=c["panel"], command=lambda _v: self.load_workflow())
        self.workflow_menu.grid(row=0, column=1, sticky="ew", padx=8)
        _button(bar, self, "저장", self.save_workflow, width=78, color=c["green"], text_color="#07140d").grid(row=0, column=2, padx=4)
        _button(bar, self, "삭제", self.delete_workflow, width=78, color=c["red"]).grid(row=0, column=3, padx=4)

        self.step_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent", scrollbar_button_color=c["stroke"], scrollbar_button_hover_color=c["hover"])
        self.step_scroll.grid(row=1, column=0, sticky="nsew", padx=22)
        self.step_scroll.grid_columnconfigure(0, weight=1)

        runbar = _section(frame, self)
        runbar.grid(row=2, column=0, sticky="ew", padx=22, pady=(12, 0))
        runbar.grid_columnconfigure(8, weight=1)
        ctk.CTkLabel(runbar, text="반복", text_color=c["muted"]).grid(row=0, column=0, padx=(14, 6), pady=12)
        self.repeat_var = tk.StringVar(value="1")
        ctk.CTkEntry(runbar, textvariable=self.repeat_var, width=64, fg_color=c["bg"], border_color=c["stroke"], text_color=c["text"]).grid(row=0, column=1, padx=(0, 12), pady=12)
        ctk.CTkLabel(runbar, text="PC별 랜덤 지연(초)", text_color=c["muted"]).grid(row=0, column=2, padx=(4, 6), pady=12)
        self.delay_min_entry = _entry(runbar, self, "최소", width=72)
        self.delay_max_entry = _entry(runbar, self, "최대", width=72)
        self.delay_min_entry.insert(0, _format_seconds(_ms_to_seconds(self.cfg.get("delay_min_ms", 0))))
        self.delay_max_entry.insert(0, _format_seconds(_ms_to_seconds(self.cfg.get("delay_max_ms", 0))))
        self.delay_min_entry.grid(row=0, column=3, padx=4, pady=12)
        self.delay_max_entry.grid(row=0, column=4, padx=4, pady=12)
        _button(runbar, self, "실행", self.run_workflow, width=92, color=c["green"], text_color="#07140d").grid(row=0, column=5, padx=4, pady=12)
        _button(runbar, self, "중지", self.stop_workflow, width=92, color=c["red"]).grid(row=0, column=6, padx=4, pady=12)
        self.workflow_status = ctk.CTkLabel(runbar, text="", text_color=c["muted"], anchor="w")
        self.workflow_status.grid(row=0, column=8, sticky="ew", padx=12)

        addbar = ctk.CTkFrame(frame, fg_color="transparent")
        addbar.grid(row=3, column=0, sticky="ew", padx=22, pady=(12, 18))
        self.add_action_var = tk.StringVar(value="대기")
        ctk.CTkOptionMenu(addbar, variable=self.add_action_var, values=ACTION_TYPES, width=150, fg_color=c["panel"], button_color=c["blue"]).pack(side="left")
        _button(addbar, self, "단계 추가", self.add_step, width=110).pack(side="left", padx=8)
        _button(addbar, self, "초기화", self.reset_workflow, width=90, color=c["panel2"]).pack(side="left")

        self.load_initial_workflow()
        return frame

    def connect_from_form(self):
        if self.debug_agents:
            agent = self.add_debug_agent()
            self.select_agent(agent)
            self.set_status(f"{agent.label} 추가됨")
            self.refresh_all()
            return
        host = self.host_entry.get().strip()
        if not host:
            self.set_status("IP 또는 호스트를 입력하세요.")
            return
        port = _int(self.port_entry.get(), DEFAULT_PORT)
        agent = self.manager.add(host, port)
        self.select_agent(agent)
        self.save_agent_list()
        threading.Thread(target=lambda: (agent.connect(timeout=3.0), self.root.after(0, self.refresh_all)), daemon=True).start()

    def rebuild_agent_cards(self):
        if not hasattr(self, "agent_list"):
            return
        agents = self.all_agents()
        keys = [_agent_key(agent) for agent in agents]
        if keys == self._agent_card_keys and len(self.cards) == len(agents):
            for card, agent in zip(self.cards, agents):
                card.agent = agent
            self.refresh_agent_cards()
            return
        for child in self.agent_list.winfo_children():
            child.destroy()
        self.cards.clear()
        for agent in agents:
            card = AgentCard(self.agent_list, self, agent)
            card.grid(row=len(self.cards), column=0, sticky="ew", padx=2, pady=5)
            self.cards.append(card)
        self._agent_card_keys = keys
        self.refresh_agent_cards()

    def refresh_agent_cards(self):
        for card in self.cards:
            card.refresh(card.agent is self.selected_agent)

    def select_monitor_agent(self, agent, multi: bool = False):
        key = _agent_key(agent)
        if not key:
            return
        self.selected_agent = agent
        if multi:
            if key in self.monitor_selected_keys:
                self.monitor_selected_keys.remove(key)
            else:
                self.monitor_selected_keys.add(key)
        else:
            self.monitor_selected_keys = {key}
        self.refresh_agent_cards()
        if self.wall is not None and self.wall.winfo_exists():
            self.wall.select_keys(self.monitor_selected_keys)

    def select_agent(self, agent):
        self.selected_agent = agent
        key = _agent_key(agent)
        if key:
            self.monitor_selected_keys = {key}
        self.refresh_agent_cards()
        if self.wall is not None and self.wall.winfo_exists():
            self.wall.select_keys(self.monitor_selected_keys)

    def get_monitor_name(self, agent) -> str:
        key = _agent_key(agent)
        return self.monitor_names.get(key) or str(agent)

    def set_monitor_name(self, agent, name: str):
        key = _agent_key(agent)
        if not key:
            return
        clean = name.strip() or str(agent)
        if clean == str(agent):
            self.monitor_names.pop(key, None)
        else:
            self.monitor_names[key] = clean
        self.cfg["monitor_names"] = self.monitor_names
        save_config(self.cfg)
        if self.wall is not None and self.wall.winfo_exists():
            tile = self.wall._tiles.get(key)
            if tile is not None:
                tile.refresh_name()

    def move_monitor_tile(self, agent, direction: int):
        key = _agent_key(agent)
        if key not in self.monitor_order:
            return
        idx = self.monitor_order.index(key)
        new_idx = max(0, min(len(self.monitor_order) - 1, idx + direction))
        if new_idx == idx:
            return
        self.monitor_order[idx], self.monitor_order[new_idx] = self.monitor_order[new_idx], self.monitor_order[idx]
        self.cfg["monitor_order"] = self.monitor_order
        save_config(self.cfg)
        if self.wall is not None and self.wall.winfo_exists():
            self.wall._layout()
            self.wall.select_keys(self.monitor_selected_keys)

    def reorder_monitor_tile_to_point(self, agent, x_root: int, y_root: int):
        if self.wall is not None and self.wall.winfo_exists():
            self.wall.reorder_tile_to_point(agent, x_root, y_root)

    def disconnect_agent(self, agent):
        if getattr(agent, "is_debug", False):
            if agent in self.debug_agents:
                self.debug_agents.remove(agent)
                self.debug_logs.append(f"Debug agent removed: {agent.label}")
            if self.selected_agent is agent:
                self.selected_agent = self.debug_agents[0] if self.debug_agents else None
            self.debug_badge.configure(text=f"DEBUG MODE ({len(self.debug_agents)})" if self.debug_agents else "")
            self.refresh_all()
            return
        self.manager.remove(agent.host, agent.port)
        if self.selected_agent is agent:
            self.selected_agent = None
        self.save_agent_list()
        self.refresh_all()

    def open_monitor(self, agent):
        from ui.remote_view import RemoteViewWindow
        RemoteViewWindow(
            agent,
            self.secret,
            followers=[] if getattr(agent, "is_debug", False) else self.mirror_targets(agent),
            workflows_provider=lambda: self.reload_workflows_from_disk(update_ui=False),
            workflow_runner=lambda name, agents, steps=None: self.run_saved_workflow_for_agents(name, agents, steps),
            local_workflow_runner=self.run_workflow_on_current_pc,
        )

    def mirror_targets(self, primary) -> list:
        return [a for a in self.all_agents() if a is not primary and getattr(a, "is_connected", False)]

    def toggle_debug(self, force: Optional[bool] = None):
        enable = (not self.debug_agents) if force is None else force
        if enable and not self.debug_agents:
            agent = self.add_debug_agent()
            self.debug_logs.append("Debug mode enabled")
            self.select_agent(agent)
        elif not enable and self.debug_agents:
            self.debug_logs.append("Debug mode disabled")
            self.debug_agents.clear()
            if getattr(self.selected_agent, "is_debug", False):
                self.selected_agent = None
        self.debug_badge.configure(text=f"DEBUG MODE ({len(self.debug_agents)})" if self.debug_agents else "")
        self.refresh_all(force=True)

    def toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.colors = THEMES.get(self.theme_name, THEMES["dark"])
        self.cfg["theme"] = self.theme_name
        save_config(self.cfg)
        self.apply_theme_colors()
        self.set_status("테마 변경됨")

    def apply_theme_colors(self):
        c = self.colors
        self.root.configure(fg_color=c["bg"])
        if hasattr(self, "left"):
            self.left.configure(fg_color=c["surface"])
        if hasattr(self, "topbar"):
            self.topbar.configure(fg_color=c["bg"])
        if hasattr(self, "palette"):
            self.palette.configure(fg_color=c["bg"])
        if hasattr(self, "title"):
            self.title.configure(text_color=c["text"])
        if hasattr(self, "status"):
            self.status.configure(fg_color=c["surface"], text_color=c["muted"])
        if hasattr(self, "debug_badge"):
            self.debug_badge.configure(text_color=c["yellow"])
        if hasattr(self, "theme_button"):
            self.theme_button.configure(text=self.theme_icon(), fg_color=c["panel2"], hover_color=c["hover"], text_color=c["yellow"])
        for name in ("연결", "워크플로우"):
            frame = self.palette_frames.pop(name, None)
            if frame is not None and frame.winfo_exists():
                frame.destroy()
        self.cards.clear()
        self._agent_card_keys.clear()
        self.workflow_rows.clear()
        for key, btn in getattr(self, "nav_buttons", {}).items():
            btn.configure(
                fg_color=c["panel2"] if key == self.current_palette else "transparent",
                hover_color=c["hover"],
                text_color=c["text"],
            )
        if getattr(self, "status_dock", None) is not None:
            self.status_dock.refresh(self.all_agents())
        if self.settings_dropdown is not None and self.settings_dropdown.winfo_exists():
            self.settings_dropdown.configure(fg_color=c["surface"], border_color=c["stroke"])
        if self.wall is not None and self.wall.winfo_exists():
            self.wall.apply_theme()
        if self.current_palette != "모니터링":
            self.show_palette(self.current_palette)

    def rebuild_shell(self):
        current = self.current_palette
        selected_keys = set(self.monitor_selected_keys)
        if self.wall is not None:
            self.wall.stop_all()
            self.wall = None
        if self.settings_dropdown is not None and self.settings_dropdown.winfo_exists():
            self.settings_dropdown.destroy()
            self.settings_dropdown = None
        for child in self.root.winfo_children():
            child.destroy()
        self.cards.clear()
        self._agent_card_keys.clear()
        self.palette_frames.clear()
        self.workflow_rows.clear()
        self.root.configure(fg_color=self.colors["bg"])
        self.build_left_panel()
        self.build_topbar()
        self.palette = ctk.CTkFrame(self.root, fg_color=self.colors["bg"], corner_radius=0)
        self.palette.grid(row=1, column=1, sticky="nsew")
        self.palette.grid_columnconfigure(0, weight=1)
        self.palette.grid_rowconfigure(0, weight=1)
        self.status = ctk.CTkLabel(self.root, text="준비됨", anchor="w", fg_color=self.colors["surface"], text_color=self.colors["muted"], height=30)
        self.status.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.monitor_selected_keys = selected_keys
        self.show_palette(current)

    def open_settings(self):
        if self.settings_dropdown is not None and self.settings_dropdown.winfo_exists():
            self.settings_dropdown.destroy()
            self.settings_dropdown = None
            return
        c = self.colors
        panel = ctk.CTkFrame(self.root, fg_color=c["surface"], corner_radius=12, border_width=1, border_color=c["stroke"])
        panel.place(relx=1.0, y=62, x=-228, anchor="ne")
        self.settings_dropdown = panel
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(head, text="설정", font=ctk.CTkFont(size=16, weight="bold"), text_color=c["text"]).pack(side="left")
        _mini_button(head, self, "X", lambda: self.open_settings(), width=30, color=c["panel2"]).pack(side="right")
        ctk.CTkLabel(panel, text=f"워크플로우 폴더\n{FLOWS_DIR}", justify="left", text_color=c["muted"]).pack(anchor="w", padx=14, pady=(4, 10))
        _button(panel, self, "워크플로우 다시 불러오기", self.reload_workflows_from_disk, width=190, color=c["panel2"]).pack(anchor="w", padx=14, pady=(0, 12))
        if self.debug_agents:
            ctk.CTkLabel(panel, text="Debug 로그", text_color=c["yellow"]).pack(anchor="w", padx=14, pady=(4, 4))
            box = ctk.CTkTextbox(panel, width=360, height=120, fg_color=c["panel"], text_color=c["text"])
            box.pack(fill="both", expand=True, padx=14, pady=(0, 14))
            box.insert("end", "\n".join(self.debug_logs[-50:]))

    def add_step(self, step: Optional[dict] = None):
        if not hasattr(self, "step_scroll"):
            return
        step = step or {"type": self.add_action_var.get()}
        row = WorkflowStepRow(self.step_scroll, self, len(self.workflow_rows), step)
        row.grid(row=len(self.workflow_rows), column=0, sticky="ew", padx=2, pady=5)
        self.workflow_rows.append(row)

    def delete_step(self, row: WorkflowStepRow):
        self.workflow_rows.remove(row)
        row.destroy()
        self.renumber_steps()

    def move_step(self, row: WorkflowStepRow, delta: int):
        idx = self.workflow_rows.index(row)
        new = idx + delta
        if 0 <= new < len(self.workflow_rows):
            self.workflow_rows[idx], self.workflow_rows[new] = self.workflow_rows[new], self.workflow_rows[idx]
            self.renumber_steps()

    def renumber_steps(self):
        for idx, row in enumerate(self.workflow_rows):
            row.renumber(idx)
            row.grid(row=idx, column=0, sticky="ew", padx=2, pady=5)

    def workflow_steps(self) -> list[dict]:
        return [row.get_step() for row in self.workflow_rows]

    def workflow_names(self) -> list[str]:
        names = [w.get("name", "") for w in self.cfg.get("workflows", []) if w.get("name")]
        return names or ["새 워크플로우"]

    def reload_workflows_from_disk(self, update_ui: bool = True) -> list[dict]:
        disk_workflows = load_workflows()
        if disk_workflows:
            self.cfg["workflows"] = disk_workflows
        else:
            self.cfg["workflows"] = self.cfg.get("workflows", [])
        if update_ui:
            if hasattr(self, "workflow_menu"):
                self.workflow_menu.configure(values=self.workflow_names())
                self.workflow_var.set(self.workflow_names()[0])
            if self.wall is not None and self.wall.winfo_exists():
                self.wall.refresh_workflows()
            self.set_status(f"워크플로우 불러옴: {len(self.cfg['workflows'])}개")
        return self.cfg["workflows"]

    def load_initial_workflow(self):
        if self.cfg.get("workflows"):
            self.load_workflow(self.cfg["workflows"][0].get("name"))
        else:
            for step in default_workflow():
                self.add_step(step)

    def load_workflow(self, name: Optional[str] = None):
        name = name or self.workflow_var.get()
        for wf in self.cfg.get("workflows", []):
            if wf.get("name") == name:
                self.reset_workflow(empty=True)
                self.workflow_name.delete(0, "end")
                self.workflow_name.insert(0, name)
                for step in wf.get("steps", []):
                    self.add_step(step)

    def save_workflow(self):
        name = self.workflow_name.get().strip() or self.workflow_var.get().strip()
        if not name or name == "새 워크플로우":
            self.set_status("워크플로우 이름을 입력하세요.")
            return
        save_workflow_file({"name": name, "steps": self.workflow_steps()})
        self.reload_workflows_from_disk(update_ui=False)
        self.workflow_menu.configure(values=self.workflow_names())
        self.workflow_var.set(name)
        self.save_settings(silent=True)
        if self.wall is not None and self.wall.winfo_exists():
            self.wall.refresh_workflows()
        self.set_status(f"워크플로우 저장됨: {name} ({FLOWS_DIR})")

    def delete_workflow(self):
        name = self.workflow_var.get()
        delete_workflow_file(name)
        self.cfg["workflows"] = [w for w in self.cfg.get("workflows", []) if w.get("name") != name]
        self.workflow_menu.configure(values=self.workflow_names())
        self.workflow_var.set(self.workflow_names()[0])
        self.save_settings(silent=True)
        if self.wall is not None and self.wall.winfo_exists():
            self.wall.refresh_workflows()

    def reset_workflow(self, empty: bool = False):
        for row in self.workflow_rows:
            row.destroy()
        self.workflow_rows.clear()
        if not empty:
            for step in default_workflow():
                self.add_step(step)

    def run_workflow(self):
        targets = self.targets()
        if not targets:
            self.set_status("실행 대상이 없습니다.")
            return
        repeat = max(1, _int(self.repeat_var.get(), 1))
        steps = self.workflow_steps()
        self.run_steps_for_agents(steps, targets, repeat)

    def find_workflow(self, name: str) -> Optional[dict]:
        for wf in self.cfg.get("workflows", []):
            if wf.get("name") == name:
                return wf
        return None

    def run_monitor_workflow(self, name: str):
        targets = self.wall.selected_agents() if self.wall is not None and self.wall.winfo_exists() else []
        if not targets and self.selected_agent and getattr(self.selected_agent, "is_connected", False):
            targets = [self.selected_agent]
        self.run_saved_workflow_for_agents(name, targets)

    def run_saved_workflow_for_agents(self, name: str, agents: list, draft_steps: Optional[list[dict]] = None):
        if draft_steps is None:
            wf = self.find_workflow(name)
            if not wf:
                self.set_status(f"워크플로우를 찾을 수 없습니다: {name}")
                return
            steps = wf.get("steps", [])
        else:
            steps = draft_steps
        targets = [a for a in agents if getattr(a, "is_connected", False)]
        if not targets:
            self.set_status("선택된 모니터링 PC가 없습니다.")
            return
        repeat = max(1, _int(self.repeat_var.get(), 1)) if hasattr(self, "repeat_var") else 1
        self.run_steps_for_agents(steps, targets, repeat)
        self.set_status(f"{name} 실행: {len(targets)}대")

    def run_workflow_on_current_pc(self, steps: list[dict]):
        tester = DebugAgent(0)
        threading.Thread(target=self.run_workflow_for_agent, args=(tester, steps, 1), daemon=True).start()
        self.set_status("현재 PC 테스트 실행")

    def run_steps_for_agents(self, steps: list[dict], agents: list, repeat: int = 1):
        self.macro_stop = False
        for agent in agents:
            threading.Thread(target=self.run_workflow_for_agent, args=(agent, steps, repeat), daemon=True).start()

    def run_workflow_for_agent(self, agent, steps: list[dict], repeat: int):
        lo, hi = self.delay_range()
        if hi > 0:
            time.sleep(random.uniform(lo, hi) / 1000.0)
        detectors = [s for s in steps if s.get("type") == "이미지 감지"]
        runnable_steps = [s for s in steps if s.get("type") != "이미지 감지"]
        detector_stop = threading.Event()
        agent_stop = threading.Event()
        detector_threads = [
            threading.Thread(target=self.run_detector_for_agent, args=(agent, step, detector_stop, agent_stop), daemon=True)
            for step in detectors
        ]
        for thread in detector_threads:
            thread.start()

        total = max(1, len(runnable_steps) * repeat)
        done = 0
        try:
            for _ in range(repeat):
                for step in runnable_steps:
                    if self.macro_stop or agent_stop.is_set():
                        break
                    self.execute_step(agent, step)
                    done += 1
                    pct = int(done / total * 100)
                    self.root.after(0, lambda p=pct, a=agent: self.update_workflow_progress(a, p))
                    if hi > 0:
                        time.sleep(random.uniform(lo, hi) / 1000.0)
        finally:
            detector_stop.set()

    def run_detector_for_agent(self, agent, step: dict, stop_event: threading.Event, agent_stop: threading.Event):
        interval = max(100, int(_float(step.get("interval"), 500.0))) / 1000.0
        while not stop_event.is_set() and not self.macro_stop and not agent_stop.is_set():
            result = self.find_image_for_agent(agent, step, quiet=True)
            if result and result.get("ok"):
                action = str(step.get("detect_action", "click"))
                if action == "click":
                    x = _int(result.get("x"), 0) + int(_float(step.get("offset_x"), 0))
                    y = _int(result.get("y"), 0) + int(_float(step.get("offset_y"), 0))
                    self.natural_move(agent, x, y, 180.0, 1.0)
                    self.click(agent, "left")
                elif action == "stop_agent":
                    agent_stop.set()
                elif action == "stop_all":
                    self.macro_stop = True
                self.root.after(0, lambda a=agent, act=action: self.set_status(f"{a} 이미지 감지 행동: {act}"))
                break
            stop_event.wait(interval)

    def update_workflow_progress(self, agent, pct: int):
        if hasattr(self, "workflow_status") and self.workflow_status.winfo_exists():
            self.workflow_status.configure(text=f"{agent} {pct}%", text_color=self.colors["green"])
        self.set_status(f"{agent} 워크플로우 {pct}%")

    def execute_step(self, agent, step: dict):
        kind = step.get("type")
        if kind == "대기":
            time.sleep(_float(step.get("ms"), 500.0) / 1000.0)
        elif kind == "키 입력":
            key_text, key_mods = _parse_key_combo(str(step.get("key", "A")), step.get("mods", ""))
            self.tap_key(agent, _parse_vk(key_text), key_mods)
        elif kind == "마우스 이동":
            s = self.step_for_agent(step, agent)
            self.move(agent, _int(s.get("x"), 960), _int(s.get("y"), 540))
        elif kind == "자연 이동":
            s = self.step_for_agent(step, agent)
            self.natural_move(agent, _int(s.get("x"), 960), _int(s.get("y"), 540), _float(s.get("duration"), 650.0), _float(s.get("jitter"), 3))
        elif kind == "클릭":
            self.click(agent, str(step.get("button", "left")))
        elif kind == "랜덤 클릭":
            s = self.step_for_agent(step, agent)
            x1, y1, x2, y2 = _int(s.get("x1"), 850), _int(s.get("y1"), 450), _int(s.get("x2"), 1070), _int(s.get("y2"), 630)
            self.natural_move(agent, random.randint(min(x1, x2), max(x1, x2)), random.randint(min(y1, y2), max(y1, y2)), 650.0, 3)
            self.click(agent, str(step.get("button", "left")))
        elif kind == "스크롤":
            agent.send(Command.mouse_scroll(_int(step.get("delta"), -120)))
        elif kind == "이미지 찾기":
            found = self.find_image_for_agent(agent, step)
            if found and found.get("ok"):
                x = _int(found.get("x"), 0) + int(_float(step.get("offset_x"), 0))
                y = _int(found.get("y"), 0) + int(_float(step.get("offset_y"), 0))
                self.natural_move(agent, x, y, 250.0, 1.0)
                self.click(agent, "left")
        elif kind == "이미지 대기":
            self.find_image_for_agent(agent, step)

    def step_for_agent(self, step: dict, agent) -> dict:
        overrides = step.get("perAgent") or step.get("per_agent") or {}
        if not isinstance(overrides, dict):
            return step
        key = _agent_key(agent)
        alt = overrides.get(key) or overrides.get(str(agent))
        if not isinstance(alt, dict):
            return step
        merged = dict(step)
        merged.update(alt)
        return merged

    def find_image_for_agent(self, agent, step: dict, quiet: bool = False) -> Optional[dict]:
        path = str(step.get("image_path", "")).strip()
        if not path:
            if not quiet:
                self.root.after(0, lambda: self.set_status("이미지 파일 경로가 비어 있습니다."))
            return None
        try:
            image_data = _image_file_to_data_url(path)
        except Exception as exc:
            if not quiet:
                self.root.after(0, lambda e=exc: self.set_status(f"이미지 로드 실패: {e}"))
            return None
        if not hasattr(agent, "find_image"):
            if not quiet:
                self.root.after(0, lambda: self.set_status("Agent가 이미지 탐색을 지원하지 않습니다."))
            return None
        result = agent.find_image(
            image_data,
            threshold=max(0.0, min(1.0, _float(step.get("threshold"), 0.92))),
            timeoutMs=max(100, int(_float(step.get("timeout"), 3000.0))),
            matchMode=str(step.get("match_mode", "similar")),
        )
        if result and result.get("ok"):
            self.last_positions[_agent_key(agent)] = (_int(result.get("x"), 0), _int(result.get("y"), 0))
            if not quiet:
                self.root.after(0, lambda r=result, a=agent: self.set_status(f"{a} 이미지 감지: {r.get('x')}, {r.get('y')} / {r.get('score', '')}"))
        else:
            msg = result.get("msg") if isinstance(result, dict) else "응답 없음"
            if not quiet:
                self.root.after(0, lambda a=agent, m=msg: self.set_status(f"{a} 이미지 미감지: {m}"))
        return result

    def stop_workflow(self):
        self.macro_stop = True

    def targets(self) -> list:
        agents = [a for a in self.all_agents() if getattr(a, "is_connected", False)]
        # 현재 UI에서는 복제 선택을 제거하고 선택/전체만 운용한다.
        if self.selected_agent and getattr(self.selected_agent, "is_connected", False):
            return [self.selected_agent]
        return agents

    def tap_key(self, agent, vk: int, key_mods: list[str]):
        agent.send(Command.key_press(vk, key_mods))
        time.sleep(random.uniform(0.035, 0.08))
        agent.send(Command.key_release(vk, key_mods))

    def move(self, agent, x: int, y: int):
        agent.send(Command.mouse_move(x, y, absolute=True))
        self.last_positions[_agent_key(agent)] = (x, y)

    def natural_move(self, agent, x: int, y: int, duration: float, jitter: float):
        start = self.last_positions.get(_agent_key(agent), (x, y))
        steps = max(3, min(80, int(duration / 16)))
        for i in range(1, steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)
            nx = start[0] + (x - start[0]) * eased
            ny = start[1] + (y - start[1]) * eased
            if i != steps:
                nx += random.uniform(-jitter, jitter)
                ny += random.uniform(-jitter, jitter)
            agent.send(Command.mouse_move(int(nx), int(ny), absolute=True))
            time.sleep(max(0.001, duration / steps / 1000.0))
        self.last_positions[_agent_key(agent)] = (x, y)

    def click(self, agent, button: str):
        agent.send(Command.mouse_down(button))
        time.sleep(random.uniform(0.035, 0.09))
        agent.send(Command.mouse_up(button))

    def delay_range(self) -> tuple[int, int]:
        if not hasattr(self, "delay_min_entry"):
            return 0, 0
        lo = int(_seconds_to_ms(self.delay_min_entry.get()))
        hi = int(_seconds_to_ms(self.delay_max_entry.get()))
        return min(lo, hi), max(lo, hi)

    def toggle_mirror(self):
        self.mirror_mode.set(not self.mirror_mode.get())

    def save_settings(self, silent: bool = False):
        self.cfg["theme"] = self.theme_name
        self.cfg["secret"] = self.secret
        lo, hi = self.delay_range()
        self.cfg["delay_min_ms"] = lo
        self.cfg["delay_max_ms"] = hi
        self.cfg["monitor_names"] = self.monitor_names
        self.cfg["monitor_order"] = self.monitor_order
        self.save_agent_list(write=False)
        save_config(self.cfg)
        if not silent:
            self.set_status("설정 저장됨")

    def save_agent_list(self, write: bool = True):
        self.cfg["agents"] = [
            {"host": a.host, "port": a.port}
            for a in self.manager.all_agents()
            if not getattr(a, "is_debug", False)
        ]
        if write:
            save_config(self.cfg)

    def restore_agents(self):
        for entry in self.cfg.get("agents", []):
            host = entry.get("host")
            if not host:
                continue
            agent = self.manager.add(host, int(entry.get("port", DEFAULT_PORT)))
            if not self.selected_agent:
                self.select_agent(agent)
            threading.Thread(target=lambda a=agent: (a.connect(timeout=3.0), self.root.after(0, self.refresh_all)), daemon=True).start()

    def agent_refresh_signature(self) -> tuple:
        signature = []
        for agent in self.all_agents():
            latency = float(getattr(agent, "latency_ms", -1) or -1)
            if latency < 0:
                latency_bucket = -1
            elif latency >= 800:
                latency_bucket = 8
            else:
                latency_bucket = int(latency // 100)
            signature.append(
                (
                    _agent_key(agent),
                    bool(getattr(agent, "is_connected", False)),
                    latency_bucket,
                    bool(getattr(agent, "vhf_installed", False)),
                    str(agent),
                )
            )
        return tuple(signature)

    def refresh_all(self, force: bool = False):
        signature = self.agent_refresh_signature()
        if not force and signature == self._last_agent_signature:
            return
        self._last_agent_signature = signature
        self.rebuild_agent_cards()
        if hasattr(self, "status_dock"):
            self.status_dock.refresh(self.all_agents())
        if self.wall is not None and self.wall.winfo_exists():
            self.wall.sync(self.all_agents())
            self.wall.select_keys(self.monitor_selected_keys)

    def tick(self):
        self.refresh_all()
        self.root.after(1000, self.tick)

    def set_status(self, text: str):
        self.status.configure(text=text)

    def on_close(self):
        if self.wall is not None:
            self.wall.stop_all()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def _section(parent, app: MainWindow) -> ctk.CTkFrame:
    c = app.colors
    return ctk.CTkFrame(parent, fg_color=c["panel"], corner_radius=12, border_width=1, border_color=c["stroke"])


def _entry(parent, app: MainWindow, placeholder: str, width: int = 160) -> ctk.CTkEntry:
    c = app.colors
    return ctk.CTkEntry(parent, placeholder_text=placeholder, width=width, fg_color=c["bg"], border_color=c["stroke"], text_color=c["text"], font=ctk.CTkFont(family="Consolas", size=12))


def _button(parent, app: MainWindow, text: str, command, width: int = 110, height: int = 34, color: Optional[str] = None, text_color: Optional[str] = None) -> ctk.CTkButton:
    c = app.colors
    base = color or c["blue"]
    return ctk.CTkButton(parent, text=text, width=width, height=height, fg_color=base, hover_color=c["hover"], text_color=text_color or c["text"], corner_radius=8, command=command)


def _mini_button(parent, app: MainWindow, text: str, command, width: int = 32, color: Optional[str] = None) -> ctk.CTkButton:
    c = app.colors
    return ctk.CTkButton(parent, text=text, width=width, height=28, fg_color=color or c["panel2"], hover_color=c["hover"], text_color=c["text"], corner_radius=7, command=command)


def _agent_key(agent) -> str:
    if agent is None:
        return ""
    return f"{getattr(agent, 'host', '')}:{getattr(agent, 'port', '')}"


def _parse_vk(value: str) -> int:
    text = value.strip()
    upper = text.upper()
    if upper in KEY_NAME_TO_VK:
        return KEY_NAME_TO_VK[upper]
    if len(text) == 1:
        return ord(text.upper())
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def _display_key(value) -> str:
    text = str(value).strip()
    try:
        vk = int(text, 16) if text.lower().startswith("0x") else int(text)
    except Exception:
        return text
    for name, code in KEY_NAME_TO_VK.items():
        if code == vk:
            return "Esc" if name == "ESC" else name.title()
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    return text


def mods(value) -> list[str]:
    if isinstance(value, list):
        return value
    return [part.strip().lower() for part in str(value).replace("+", ",").split(",") if part.strip()]


def _parse_key_combo(key_value: str, mod_value) -> tuple[str, list[str]]:
    parts = [part.strip() for part in key_value.replace(",", "+").split("+") if part.strip()]
    key = parts[-1] if parts else key_value
    combo_mods = [part.lower() for part in parts[:-1] if part.lower() in {"ctrl", "control", "shift", "alt", "win", "windows"}]
    normalized = []
    for mod in combo_mods + mods(mod_value):
        mod = {"control": "ctrl", "windows": "win"}.get(mod, mod)
        if mod in {"ctrl", "shift", "alt", "win"} and mod not in normalized:
            normalized.append(mod)
    return key, normalized


def _image_file_to_data_url(path: str) -> str:
    path = os.path.expandvars(os.path.expanduser(path))
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    ext = os.path.splitext(path)[1].lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".bmp": "image/bmp",
    }.get(ext, "application/octet-stream")
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _int(value, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _float(value, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _seconds_to_ms(value, fallback_seconds: float = 0.0) -> float:
    return max(0.0, _float(value, fallback_seconds) * 1000.0)


def _ms_to_seconds(value, fallback_ms: float = 0.0) -> float:
    return max(0.0, _float(value, fallback_ms) / 1000.0)


def _format_seconds(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def default_workflow() -> list[dict]:
    return [
        {"type": "대기", "ms": 400},
        {"type": "자연 이동", "x": 960, "y": 540, "duration": 650, "jitter": 3},
        {"type": "랜덤 클릭", "x1": 850, "y1": 450, "x2": 1070, "y2": 630, "button": "left"},
        {"type": "대기", "ms": 700},
        {"type": "키 입력", "key": "0x52", "mods": ""},
    ]
