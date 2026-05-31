import io
import threading
import time
import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageGrab, ImageTk

from models.command import Command
from network.agent_manager import AgentConnection
from network.screen_client import ScreenClient

BG = "#080c11"
SURFACE = "#101722"
PANEL = "#172231"
STROKE = "#314255"
TEXT = "#f4f8fc"
MUTED = "#93a5ba"
BLUE = "#6ea8fe"
GREEN = "#5be0a0"


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


class RemoteViewWindow:
    def __init__(
        self,
        agent: AgentConnection,
        secret: str,
        followers: Optional[list[AgentConnection]] = None,
        workflows_provider: Optional[Callable[[], list[dict]]] = None,
        workflow_runner: Optional[Callable[[str, list], None]] = None,
    ):
        self.agent = agent
        self.followers = [a for a in (followers or []) if a is not agent]
        self._workflows_provider = workflows_provider or (lambda: [])
        self._workflow_runner = workflow_runner
        self._preset_names: list[str] = []
        self._preset_delete_mode = False
        self._preset_picker: Optional[ctk.CTkFrame] = None
        self._preset_height = 26
        self._secret = secret
        self._remote_w = 1920
        self._remote_h = 1080
        self._image_rect = (0, 0, 1, 1)
        self._last_motion = 0.0
        self._mirror_var = tk.BooleanVar(value=False)

        self._lock = threading.Lock()
        self._latest_frame: Optional[bytes] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._screen_client: Optional[ScreenClient] = None
        self._local_running = False

        self._frame_count = 0
        self._last_fps_time = time.monotonic()

        self._build_window()
        self._bring_to_front()
        self._connect_stream()

    def _build_window(self):
        self.win = ctk.CTkToplevel()
        self.win.title(f"모니터링 확대 - {self.agent}")
        self.win.geometry("1280x760")
        self.win.minsize(900, 560)
        self.win.configure(fg_color=BG)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self.win.bind("<Alt-F12>", lambda _e: self._toggle_mirror())

        toolbar = ctk.CTkFrame(self.win, fg_color=SURFACE, height=52, corner_radius=0)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        ctk.CTkLabel(
            toolbar,
            text=f"대상  {self.agent}",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color=TEXT,
        ).pack(side="left", padx=14)

        self._mirror = ctk.CTkCheckBox(
            toolbar,
            text=f"행동 미러링 ({len(self.followers)}대)",
            variable=self._mirror_var,
            checkbox_width=18,
            checkbox_height=18,
            fg_color=BLUE,
            hover_color="#5792e6",
            text_color=MUTED,
            command=self._apply_mirror_cursor,
        )
        self._mirror.pack(side="left", padx=12)

        self._status_var = tk.StringVar(value="연결 중")
        ctk.CTkLabel(
            toolbar,
            textvariable=self._status_var,
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color=MUTED,
        ).pack(side="left", padx=12)

        self._fps_var = tk.StringVar(value="-- fps")
        ctk.CTkLabel(
            toolbar,
            textvariable=self._fps_var,
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color=GREEN,
        ).pack(side="right", padx=14)

        self.workflow_bar = ctk.CTkFrame(self.win, fg_color=BG, height=self._preset_height, corner_radius=0)
        self.workflow_bar.pack(side="bottom", fill="x")
        self.workflow_bar.pack_propagate(False)
        self.preset_strip = ctk.CTkFrame(self.workflow_bar, fg_color=SURFACE, corner_radius=8, height=24)
        self.preset_strip.pack(side="left", fill="x", expand=True, padx=(14, 14), pady=(0, 2))
        self.preset_strip.pack_propagate(False)
        self.preset_items = ctk.CTkFrame(self.preset_strip, fg_color="transparent")
        self.preset_items.pack(side="left", fill="x", expand=True)
        self.preset_trash_slot = ctk.CTkFrame(self.preset_strip, fg_color="transparent", width=42)
        self.preset_trash_slot.pack(side="right", fill="y")
        self.preset_trash_slot.pack_propagate(False)
        self._build_workflow_bar()

        self._canvas = tk.Canvas(self.win, bg="#05080c", cursor="crosshair", highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._image_id = self._canvas.create_image(0, 0, anchor="nw")

        self._canvas.bind("<Configure>", lambda _event: self._draw_latest())
        self._canvas.bind("<Motion>", self._on_mouse_move)
        self._canvas.bind("<ButtonPress-1>", lambda e: self._mouse_btn(e, "left", True))
        self._canvas.bind("<ButtonRelease-1>", lambda e: self._mouse_btn(e, "left", False))
        self._canvas.bind("<ButtonPress-2>", lambda e: self._mouse_btn(e, "middle", True))
        self._canvas.bind("<ButtonRelease-2>", lambda e: self._mouse_btn(e, "middle", False))
        self._canvas.bind("<ButtonPress-3>", lambda e: self._mouse_btn(e, "right", True))
        self._canvas.bind("<ButtonRelease-3>", lambda e: self._mouse_btn(e, "right", False))
        self._canvas.bind("<MouseWheel>", self._on_scroll)

        self.win.bind("<KeyPress>", self._on_key_press)
        self.win.bind("<KeyRelease>", self._on_key_release)
        self.win.focus_set()
        self.win.after(20, self._refresh_canvas)

    def _bring_to_front(self):
        def activate():
            try:
                self.win.lift()
                self.win.attributes("-topmost", True)
                self.win.focus_force()
                self.win.after(250, lambda: self.win.attributes("-topmost", False))
            except Exception:
                pass

        self.win.after(30, activate)

    def _build_workflow_bar(self):
        for child in self.preset_items.winfo_children():
            child.destroy()
        for child in self.preset_trash_slot.winfo_children():
            child.destroy()
        if not self._preset_names:
            ctk.CTkLabel(self.preset_items, text="프리셋 없음", text_color=MUTED, font=ctk.CTkFont(size=10), height=18).pack(side="left", padx=(8, 5), pady=3)
        for name in list(self._preset_names):
            row = ctk.CTkFrame(self.preset_items, fg_color="transparent")
            row.pack(side="left", padx=2, pady=2)
            ctk.CTkButton(
                row,
                text=name,
                width=88,
                height=20,
                fg_color=PANEL,
                hover_color="#29394c",
                text_color=TEXT,
                corner_radius=8,
                command=lambda n=name: self._run_workflow(n),
            ).pack(side="left")
            if self._preset_delete_mode:
                ctk.CTkButton(
                    row,
                    text="X",
                    width=22,
                    height=20,
                    fg_color="#ff6b7a",
                    hover_color="#29394c",
                    text_color=TEXT,
                    corner_radius=8,
                    command=lambda n=name: self._remove_preset(n),
                ).pack(side="left", padx=(3, 0))
        self.add_preset_button = ctk.CTkButton(
            self.preset_items,
            text="+",
            width=28,
            height=20,
            fg_color=PANEL,
            hover_color="#29394c",
            text_color=TEXT,
            corner_radius=8,
            command=self._show_preset_picker,
        )
        self.add_preset_button.pack(side="left", padx=(4, 3), pady=2)
        ctk.CTkButton(
            self.preset_trash_slot,
            text="🗑",
            width=36,
            height=24,
            fg_color=PANEL,
            hover_color="#29394c",
            text_color=TEXT,
            corner_radius=8,
            command=self._toggle_preset_delete_mode,
        ).pack(side="right", padx=(0, 0), pady=0)

    def _show_preset_picker(self):
        if self._preset_picker is not None and self._preset_picker.winfo_exists():
            self._preset_picker.destroy()
            self._preset_picker = None
            return
        workflows = self._workflows_provider()
        self._preset_picker = ctk.CTkToplevel(self.win)
        self._preset_picker.withdraw()
        self._preset_picker.overrideredirect(True)
        self._preset_picker.transient(self.win)
        self._preset_picker.configure(fg_color=SURFACE)
        self._preset_picker.bind("<Escape>", lambda _e: self._close_preset_picker())
        panel = ctk.CTkFrame(self._preset_picker, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=STROKE)
        panel.pack(fill="both", expand=True)
        if not workflows:
            ctk.CTkLabel(panel, text="저장된 워크플로우 없음", text_color=MUTED).pack(padx=14, pady=12)
            self._place_preset_picker()
            return
        available = [wf.get("name") for wf in workflows if wf.get("name") and wf.get("name") not in self._preset_names]
        if not available:
            ctk.CTkLabel(panel, text="모든 워크플로우가 추가됨", text_color=MUTED).pack(padx=14, pady=12)
            self._place_preset_picker()
            return
        for name in available:
            ctk.CTkButton(
                panel,
                text=name,
                width=160,
                height=30,
                fg_color=PANEL,
                hover_color="#29394c",
                text_color=TEXT,
                corner_radius=8,
                command=lambda n=name: self._add_preset(n),
            ).pack(fill="x", padx=8, pady=(8, 0))
        ctk.CTkFrame(panel, height=8, fg_color="transparent").pack()
        self._place_preset_picker()

    def _place_preset_picker(self):
        owner = getattr(self, "add_preset_button", None)
        if self._preset_picker is None or not self._preset_picker.winfo_exists():
            return
        self.win.update_idletasks()
        self._preset_picker.update_idletasks()
        width = max(190, self._preset_picker.winfo_reqwidth())
        height = max(46, self._preset_picker.winfo_reqheight())
        root_x = self.win.winfo_rootx()
        root_y = self.win.winfo_rooty()
        root_w = self.win.winfo_width()
        if owner is None or not owner.winfo_exists():
            x = root_x + 14
            y = root_y + self.win.winfo_height() - height - self._preset_height - 8
        else:
            x = owner.winfo_rootx() + owner.winfo_width() + 6
            y = owner.winfo_rooty() - height - 6
        x = min(max(root_x + 8, x), root_x + root_w - width - 8)
        y = max(root_y + 48, y)
        self._preset_picker.geometry(f"{width}x{height}+{x}+{y}")
        self._preset_picker.deiconify()
        self._preset_picker.lift()

    def _close_preset_picker(self):
        if self._preset_picker is not None and self._preset_picker.winfo_exists():
            self._preset_picker.destroy()
        self._preset_picker = None

    def _add_preset(self, name: str):
        if name not in self._preset_names:
            self._preset_names.append(name)
        self._close_preset_picker()
        self._build_workflow_bar()

    def _remove_preset(self, name: str):
        self._preset_names = [n for n in self._preset_names if n != name]
        self._build_workflow_bar()

    def _toggle_preset_delete_mode(self):
        self._preset_delete_mode = not self._preset_delete_mode
        self._build_workflow_bar()

    def _run_workflow(self, name: str):
        if not self._workflow_runner:
            self._status_var.set("워크플로우 실행기를 찾을 수 없습니다")
            return
        self._workflow_runner(name, [self.agent])
        self._status_var.set(f"워크플로우 실행: {name}")

    def _connect_stream(self):
        if getattr(self.agent, "is_debug", False):
            self._local_running = True
            self._status_var.set("현재 PC 화면")
            self._local_capture_tick()
            return

        self._screen_client = ScreenClient(
            host=self.agent.host,
            screen_port=int(self.agent.port) + 1,
            secret=self._secret,
            on_frame=self._on_frame_received,
        )
        self._status_var.set("화면 수신 중" if self._screen_client.start() else "화면 연결 실패")

    def _local_capture_tick(self):
        if not self._local_running:
            return
        try:
            try:
                image = ImageGrab.grab(all_screens=True)
            except TypeError:
                image = ImageGrab.grab()
            self._on_image_received(image)
        except Exception as exc:
            self._status_var.set(f"로컬 캡처 실패: {exc}")
            self._on_image_received(_debug_placeholder(str(exc)))
        self.win.after(500, self._local_capture_tick)

    def _on_image_received(self, image: Image.Image):
        image = _rgb_image(image)
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=75)
        self._on_frame_received(buf.getvalue(), image.width, image.height)

    def _on_frame_received(self, jpeg: bytes, w: int, h: int):
        with self._lock:
            self._latest_frame = jpeg
            self._remote_w = max(1, w)
            self._remote_h = max(1, h)
        self._frame_count += 1

    def _refresh_canvas(self):
        self._draw_latest()
        now = time.monotonic()
        if now - self._last_fps_time >= 1.0:
            self._fps_var.set(f"{self._frame_count} fps")
            self._frame_count = 0
            self._last_fps_time = now
        if self.win.winfo_exists():
            self.win.after(20, self._refresh_canvas)

    def _draw_latest(self):
        with self._lock:
            frame = self._latest_frame
            self._latest_frame = None
        if not frame:
            return
        try:
            image = Image.open(io.BytesIO(frame))
            cw = max(1, self._canvas.winfo_width())
            ch = max(1, self._canvas.winfo_height())
            scale = min(cw / self._remote_w, ch / self._remote_h)
            width = max(1, int(self._remote_w * scale))
            height = max(1, int(self._remote_h * scale))
            x = (cw - width) // 2
            y = (ch - height) // 2
            self._image_rect = (x, y, x + width, y + height)
            image = image.resize((width, height), Image.BILINEAR)
            self._photo = ImageTk.PhotoImage(image)
            self._canvas.itemconfigure(self._image_id, image=self._photo)
            self._canvas.coords(self._image_id, x, y)
        except Exception as exc:
            self._status_var.set(f"프레임 오류: {exc}")

    def _canvas_to_remote(self, cx: int, cy: int) -> Optional[tuple[int, int]]:
        x0, y0, x1, y1 = self._image_rect
        if cx < x0 or cx > x1 or cy < y0 or cy > y1:
            return None
        rx = int((cx - x0) * self._remote_w / max(1, x1 - x0))
        ry = int((cy - y0) * self._remote_h / max(1, y1 - y0))
        return rx, ry

    def _targets(self):
        targets = []
        if not getattr(self.agent, "is_debug", False):
            targets.append(self.agent)
        if self._mirror_var.get():
            targets.extend([a for a in self.followers if a.is_connected])
        return targets

    def _send(self, command: Command):
        for target in self._targets():
            target.send(command)

    def _send_pointer_position(self, event: tk.Event):
        pos = self._canvas_to_remote(event.x, event.y)
        if pos is not None:
            self._send(Command.mouse_move(pos[0], pos[1], absolute=True))

    def _on_mouse_move(self, event: tk.Event):
        now = time.monotonic()
        if now - self._last_motion < 0.01:
            return
        self._last_motion = now
        self._send_pointer_position(event)

    def _mouse_btn(self, event: tk.Event, button: str, down: bool):
        self._send_pointer_position(event)
        self._send(Command.mouse_down(button) if down else Command.mouse_up(button))

    def _on_scroll(self, event: tk.Event):
        self._send(Command.mouse_scroll(event.delta))

    def _on_key_press(self, event: tk.Event):
        vk = self._tk_keysym_to_vk(event.keysym)
        if vk is not None:
            self._send(Command.key_press(vk))

    def _on_key_release(self, event: tk.Event):
        vk = self._tk_keysym_to_vk(event.keysym)
        if vk is not None:
            self._send(Command.key_release(vk))

    def _toggle_mirror(self):
        self._mirror_var.set(not self._mirror_var.get())
        self._apply_mirror_cursor()

    def _apply_mirror_cursor(self):
        self._canvas.configure(cursor="none" if self._mirror_var.get() else "crosshair")

    @staticmethod
    def _tk_keysym_to_vk(keysym: str) -> Optional[int]:
        table = {
            "BackSpace": 0x08,
            "Tab": 0x09,
            "Return": 0x0D,
            "Escape": 0x1B,
            "space": 0x20,
            "Delete": 0x2E,
            "Home": 0x24,
            "End": 0x23,
            "Prior": 0x21,
            "Next": 0x22,
            "Left": 0x25,
            "Up": 0x26,
            "Right": 0x27,
            "Down": 0x28,
            "Insert": 0x2D,
            "Control_L": 0x11,
            "Control_R": 0x11,
            "Shift_L": 0x10,
            "Shift_R": 0x10,
            "Alt_L": 0x12,
            "Alt_R": 0x12,
            "Win_L": 0x5B,
            "Win_R": 0x5C,
        }
        for n in range(1, 13):
            table[f"F{n}"] = 0x6F + n
        if keysym in table:
            return table[keysym]
        if len(keysym) == 1:
            return ord(keysym.upper())
        return None

    def _on_close(self):
        self._local_running = False
        if self._screen_client:
            self._screen_client.stop()
        self.win.destroy()
