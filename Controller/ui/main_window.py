import os
import threading
import time
import tkinter as tk
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from config import load_config, save_config
from models.command import Command
from network.agent_manager import AgentManager, AgentConnection

ctk.set_appearance_mode("dark")

# ── 색상 팔레트 ────────────────────────────────────────────────────────
BG      = "#0d1117"
PANEL   = "#161b22"
CARD    = "#1c2128"
CARD_SEL= "#2d333b"
BORDER  = "#30363d"
GREEN   = "#3fb950"
BLUE    = "#58a6ff"
RED     = "#f85149"
YELLOW  = "#e3b341"
TEXT    = "#e6edf3"
MUTED   = "#8b949e"

FONT_MONO = ("Consolas", 10)
FONT_MONO_SM = ("Consolas", 9)
FONT_UI   = ("Segoe UI", 10)
FONT_TITLE = ("Segoe UI Semibold", 11)

ICON_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "icon.ico")


# ──────────────────────────────────────────────────────────────────────
#  에이전트 카드
# ──────────────────────────────────────────────────────────────────────

class AgentCard(ctk.CTkFrame):
    def __init__(self, parent, agent: AgentConnection,
                 on_select, on_view, **kwargs):
        super().__init__(parent, fg_color=CARD, corner_radius=8,
                         border_width=1, border_color=BORDER, **kwargs)
        self.agent = agent
        self._on_select = on_select
        self._selected  = False

        self.columnconfigure(1, weight=1)

        # 상태 닷
        self._dot = ctk.CTkLabel(self, text="●", width=16,
                                  font=ctk.CTkFont(size=11), text_color=GREEN)
        self._dot.grid(row=0, column=0, rowspan=2, padx=(10, 4), pady=8)

        # 주소
        self._addr = ctk.CTkLabel(self, text=str(agent), anchor="w",
                                   font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
                                   text_color=TEXT)
        self._addr.grid(row=0, column=1, sticky="w", pady=(8, 1))

        # 레이턴시
        self._lat = ctk.CTkLabel(self, text="connecting…", anchor="w",
                                  font=ctk.CTkFont(family="Consolas", size=9),
                                  text_color=MUTED)
        self._lat.grid(row=1, column=1, sticky="w", pady=(0, 8))

        # 뷰 버튼
        self._view_btn = ctk.CTkButton(
            self, text="🖥", width=30, height=26,
            fg_color=BORDER, hover_color="#3d444d",
            font=ctk.CTkFont(size=13), corner_radius=6,
            command=lambda: on_view(self.agent))
        self._view_btn.grid(row=0, column=2, rowspan=2, padx=(4, 10))

        # 클릭 → 선택
        for w in (self, self._dot, self._addr, self._lat):
            w.bind("<Button-1>", lambda _e: on_select(self))

    def refresh(self):
        if self.agent.is_connected:
            self._dot.configure(text_color=GREEN)
            lat = self.agent.latency_ms
            self._lat.configure(
                text=f"{lat:.0f} ms" if lat >= 0 else "online",
                text_color=MUTED)
        else:
            self._dot.configure(text_color=RED)
            self._lat.configure(text="offline", text_color=RED)

    def set_selected(self, v: bool):
        self._selected = v
        self.configure(
            fg_color=CARD_SEL if v else CARD,
            border_color=BLUE if v else BORDER)


# ──────────────────────────────────────────────────────────────────────
#  메인 윈도우
# ──────────────────────────────────────────────────────────────────────

class MainWindow:
    def __init__(self, manager: AgentManager, secret: str = "change-this-secret"):
        self.manager  = manager
        self._secret  = secret
        self._cfg     = load_config()
        self._cards:  list[AgentCard] = []
        self._sel:    Optional[AgentCard] = None
        self._macro_stop = False

        self.root = ctk.CTk()
        self.root.title("Rice_Harvester")
        self.root.geometry("960x620")
        self.root.minsize(860, 560)
        self.root.configure(fg_color=BG)

        if os.path.exists(ICON_PATH):
            try:
                self.root.iconbitmap(ICON_PATH)
            except Exception:
                pass

        manager.on_status_change = lambda _: self.root.after(0, self._refresh_cards)

        self._build()
        self._restore_agents()
        self.root.after(1500, self._tick)

    # ────────────────────────────────────────────────────────────────
    #  레이아웃 구성
    # ────────────────────────────────────────────────────────────────

    def _build(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()
        self._build_statusbar()

    # ── 사이드바 ──────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self.root, width=220, fg_color=PANEL,
                           corner_radius=0)
        sb.grid(row=0, column=0, sticky="ns", padx=0, pady=0)
        sb.grid_propagate(False)
        sb.rowconfigure(3, weight=1)

        # 로고 영역
        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 8))
        ctk.CTkLabel(logo, text="🌾", font=ctk.CTkFont(size=22)).pack(side="left")
        ctk.CTkLabel(logo, text="Rice_Harvester",
                      font=ctk.CTkFont(family="Segoe UI Semibold", size=13),
                      text_color=TEXT).pack(side="left", padx=6)

        ctk.CTkFrame(sb, height=1, fg_color=BORDER).grid(
            row=1, column=0, sticky="ew", padx=12, pady=4)

        # 섹션 레이블
        ctk.CTkLabel(sb, text="AGENTS", font=ctk.CTkFont(size=9, weight="bold"),
                      text_color=MUTED).grid(row=2, column=0, sticky="w", padx=14, pady=(8, 4))

        # 에이전트 스크롤 목록
        self._agent_scroll = ctk.CTkScrollableFrame(
            sb, fg_color="transparent", scrollbar_button_color=BORDER,
            scrollbar_button_hover_color="#3d444d")
        self._agent_scroll.grid(row=3, column=0, sticky="nsew", padx=8, pady=0)
        self._agent_scroll.columnconfigure(0, weight=1)

        # 하단 버튼
        btns = ctk.CTkFrame(sb, fg_color="transparent")
        btns.grid(row=4, column=0, sticky="ew", padx=8, pady=8)

        ctk.CTkButton(btns, text="＋  Connect", height=32,
                       fg_color=GREEN, hover_color="#2ea043", text_color="#0d1117",
                       font=ctk.CTkFont(weight="bold"),
                       command=self._show_connect_dialog).pack(fill="x", pady=2)

        row2 = ctk.CTkFrame(btns, fg_color="transparent")
        row2.pack(fill="x")
        ctk.CTkButton(row2, text="🖥  View", height=28, width=90,
                       fg_color=CARD, hover_color=CARD_SEL,
                       command=self._open_remote_view).pack(side="left", padx=(0, 2))
        ctk.CTkButton(row2, text="✕  Remove", height=28,
                       fg_color=CARD, hover_color="#3d1a1a", text_color=RED,
                       command=self._remove_selected).pack(side="left", fill="x", expand=True, padx=(2, 0))

        ctk.CTkFrame(sb, height=1, fg_color=BORDER).grid(
            row=5, column=0, sticky="ew", padx=12, pady=4)

        # 자동 재연결 토글
        ar_row = ctk.CTkFrame(sb, fg_color="transparent")
        ar_row.grid(row=6, column=0, sticky="ew", padx=14, pady=(4, 14))
        ctk.CTkLabel(ar_row, text="Auto-Reconnect",
                      font=ctk.CTkFont(size=10), text_color=MUTED).pack(side="left")
        self._ar_switch = ctk.CTkSwitch(ar_row, text="", width=36,
                                         onvalue=True, offvalue=False,
                                         progress_color=GREEN)
        self._ar_switch.select()
        self._ar_switch.pack(side="right")

    # ── 메인 패널 ─────────────────────────────────────────────────

    def _build_main(self):
        main = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        main.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)

        tabs = ctk.CTkTabview(main, fg_color=PANEL,
                               segmented_button_fg_color=CARD,
                               segmented_button_selected_color=BLUE,
                               segmented_button_selected_hover_color="#4a8fd4",
                               segmented_button_unselected_color=CARD,
                               segmented_button_unselected_hover_color=CARD_SEL,
                               text_color=TEXT,
                               border_width=0,
                               corner_radius=0)
        tabs.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)

        tabs.add("  Keyboard  ")
        tabs.add("  Mouse  ")
        tabs.add("  Script  ")
        tabs.add("  Settings  ")

        self._build_keyboard_tab(tabs.tab("  Keyboard  "))
        self._build_mouse_tab(tabs.tab("  Mouse  "))
        self._build_script_tab(tabs.tab("  Script  "))
        self._build_settings_tab(tabs.tab("  Settings  "))

    # ── 탭: Keyboard ──────────────────────────────────────────────

    def _build_keyboard_tab(self, parent):
        parent.columnconfigure(0, weight=1)

        # 입력 섹션
        inp = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        inp.pack(fill="x", padx=16, pady=(16, 8))
        inp.columnconfigure(1, weight=1)

        _lbl(inp, "VK Code").grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        self._vk_entry = _entry(inp, "0x41", width=120)
        self._vk_entry.grid(row=0, column=1, sticky="w", padx=8, pady=(12, 4))
        _lbl(inp, "hex — e.g. 0x41 = A", small=True).grid(
            row=0, column=2, sticky="w", padx=4, pady=(12, 4))

        _lbl(inp, "Modifiers").grid(row=1, column=0, sticky="w", padx=14, pady=(4, 12))
        self._mod_entry = _entry(inp, "ctrl, shift, alt, win", width=220)
        self._mod_entry.grid(row=1, column=1, columnspan=2, sticky="w",
                              padx=8, pady=(4, 12))

        # 액션 버튼
        act = ctk.CTkFrame(parent, fg_color="transparent")
        act.pack(fill="x", padx=16, pady=4)
        _action_btn(act, "PRESS",   BLUE,  self._key_press).pack(side="left", padx=(0, 6))
        _action_btn(act, "RELEASE", CARD,  self._key_release).pack(side="left", padx=(0, 6))
        _action_btn(act, "TAP",     GREEN, self._key_tap,
                    text_color="#0d1117").pack(side="left")

        # 구분선
        ctk.CTkFrame(parent, height=1, fg_color=BORDER).pack(
            fill="x", padx=16, pady=12)

        # 퀵 키
        _lbl(parent, "QUICK KEYS", small=True).pack(anchor="w", padx=18, pady=(0, 6))

        qf = ctk.CTkFrame(parent, fg_color="transparent")
        qf.pack(fill="x", padx=14)

        quick = [
            ("Enter",    0x0D, []),  ("Esc",      0x1B, []),
            ("Tab",      0x09, []),  ("Space",    0x20, []),
            ("Del",      0x2E, []),  ("↑",        0x26, []),
            ("↓",        0x28, []),  ("←",        0x25, []),
            ("→",        0x27, []),  ("Ctrl+C",   0x43, ["ctrl"]),
            ("Ctrl+V",   0x56, ["ctrl"]), ("Ctrl+Z",   0x5A, ["ctrl"]),
            ("Ctrl+A",   0x41, ["ctrl"]), ("Ctrl+S",   0x53, ["ctrl"]),
            ("Win+D",    0x44, ["win"]),  ("Alt+F4",   0x73, ["alt"]),
        ]
        for i, (label, vk, mods) in enumerate(quick):
            ctk.CTkButton(
                qf, text=label, width=64, height=28,
                fg_color=CARD, hover_color=CARD_SEL, text_color=TEXT,
                font=ctk.CTkFont(family="Consolas", size=10), corner_radius=6,
                command=lambda v=vk, m=mods: self._quick_tap(v, m)
            ).grid(row=i // 8, column=i % 8, padx=3, pady=3)

    # ── 탭: Mouse ─────────────────────────────────────────────────

    def _build_mouse_tab(self, parent):
        # 좌표 이동
        move = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        move.pack(fill="x", padx=16, pady=(16, 8))

        _lbl(move, "ABSOLUTE MOVE").grid(
            row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(12, 6))

        _lbl(move, "X").grid(row=1, column=0, padx=(14, 4), pady=(0, 12))
        self._mx = _entry(move, "960", width=90)
        self._mx.grid(row=1, column=1, padx=4, pady=(0, 12))
        _lbl(move, "Y").grid(row=1, column=2, padx=4, pady=(0, 12))
        self._my = _entry(move, "540", width=90)
        self._my.grid(row=1, column=3, padx=4, pady=(0, 12))
        _action_btn(move, "MOVE", BLUE, self._mouse_move, width=80).grid(
            row=1, column=4, padx=12, pady=(0, 12))

        # 클릭
        click = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        click.pack(fill="x", padx=16, pady=8)
        _lbl(click, "CLICK").grid(row=0, column=0, sticky="w",
                                   padx=14, pady=(12, 8))
        bf = ctk.CTkFrame(click, fg_color="transparent")
        bf.grid(row=1, column=0, padx=10, pady=(0, 12))
        for label, btn in [("Left", "left"), ("Right", "right"), ("Middle", "middle")]:
            _action_btn(bf, label, CARD if label != "Left" else BLUE,
                         lambda b=btn: self._mouse_click(b), width=90).pack(
                             side="left", padx=4)

        # 스크롤
        scroll = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        scroll.pack(fill="x", padx=16, pady=8)
        _lbl(scroll, "SCROLL").grid(row=0, column=0, sticky="w",
                                     padx=14, pady=(12, 8))
        sf = ctk.CTkFrame(scroll, fg_color="transparent")
        sf.grid(row=1, column=0, padx=10, pady=(0, 12))
        self._scroll_delta = _entry(sf, "120", width=80)
        self._scroll_delta.pack(side="left", padx=(0, 8))
        _action_btn(sf, "▲ Up",   CARD, lambda: self._scroll(1),  width=80).pack(side="left", padx=3)
        _action_btn(sf, "▼ Down", CARD, lambda: self._scroll(-1), width=80).pack(side="left", padx=3)

    # ── 탭: Script ────────────────────────────────────────────────

    def _build_script_tab(self, parent):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        # 헤더
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        _lbl(hdr, "COMMAND SCRIPT").pack(side="left")
        ctk.CTkLabel(hdr,
            text="key_tap <VK>  ·  mouse_move <x> <y>  ·  mouse_click <left|right>  ·  delay <ms>",
            font=ctk.CTkFont(family="Consolas", size=9), text_color=MUTED
        ).pack(side="left", padx=16)

        # 텍스트 에디터
        self._script = ctk.CTkTextbox(
            parent, font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=CARD, text_color=TEXT,
            border_color=BORDER, border_width=1, corner_radius=8)
        self._script.grid(row=1, column=0, sticky="nsew", padx=16, pady=4)
        self._script.insert("end",
            "# Command Script\n"
            "# 주석은 # 으로 시작\n\n"
            "delay 500\n"
            "mouse_move 960 540\n"
            "mouse_click left\n"
            "delay 200\n"
            "key_tap 0x52\n"   # R
        )

        # 실행 컨트롤
        ctrl = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=8)
        ctrl.grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 14))
        ctrl.columnconfigure(2, weight=1)

        _lbl(ctrl, "Repeat").grid(row=0, column=0, padx=(14, 4), pady=10)
        self._repeat_var = ctk.StringVar(value="1")
        ctk.CTkEntry(ctrl, textvariable=self._repeat_var, width=60,
                      fg_color=BG, border_color=BORDER,
                      font=ctk.CTkFont(family="Consolas")).grid(
                          row=0, column=1, padx=4, pady=10)

        _action_btn(ctrl, "▶  RUN", GREEN, self._run_script,
                     text_color="#0d1117").grid(row=0, column=3, padx=4, pady=10)
        _action_btn(ctrl, "■  STOP", RED, self._stop_script, width=80).grid(
            row=0, column=4, padx=(0, 14), pady=10)

        # 진행 표시
        self._script_status = ctk.CTkLabel(
            ctrl, text="", font=ctk.CTkFont(family="Consolas", size=10),
            text_color=MUTED)
        self._script_status.grid(row=0, column=2, sticky="ew")

    # ── 탭: Settings ──────────────────────────────────────────────

    def _build_settings_tab(self, parent):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        card.pack(fill="x", padx=16, pady=16)
        card.columnconfigure(1, weight=1)

        _lbl(card, "SECURITY").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 8))

        _lbl(card, "Shared Secret").grid(row=1, column=0, sticky="w", padx=14, pady=4)
        self._secret_entry = ctk.CTkEntry(
            card, show="●", placeholder_text="encryption key",
            fg_color=BG, border_color=BORDER,
            font=ctk.CTkFont(family="Consolas"))
        self._secret_entry.insert(0, self._secret)
        self._secret_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        _action_btn(card, "Apply", BLUE, self._apply_secret,
                     width=70, height=28).grid(row=1, column=2, padx=(4, 14), pady=4)

        ctk.CTkFrame(card, height=1, fg_color=BORDER).grid(
            row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=8)

        _lbl(card, "STREAMING").grid(
            row=3, column=0, columnspan=3, sticky="w", padx=14, pady=(4, 8))

        _lbl(card, "Target FPS").grid(row=4, column=0, sticky="w", padx=14, pady=4)
        self._fps_label = ctk.CTkLabel(card, text="10",
                                        font=ctk.CTkFont(family="Consolas"),
                                        text_color=GREEN, width=30)
        self._fps_label.grid(row=4, column=2, padx=(0, 14), pady=4)
        fps_slider = ctk.CTkSlider(
            card, from_=1, to=30, number_of_steps=29,
            progress_color=BLUE, button_color=BLUE, button_hover_color="#4a8fd4",
            command=lambda v: self._fps_label.configure(text=str(int(v))))
        fps_slider.set(self._cfg.get("fps", 10))
        fps_slider.grid(row=4, column=1, sticky="ew", padx=8, pady=4)
        self._fps_slider = fps_slider

        ctk.CTkFrame(card, height=1, fg_color=BORDER).grid(
            row=5, column=0, columnspan=3, sticky="ew", padx=14, pady=8)

        _action_btn(card, "  Save Settings", GREEN, self._save_settings,
                     text_color="#0d1117", height=32).grid(
                         row=6, column=0, columnspan=3, padx=14, pady=(0, 14))

    # ── 상태바 ────────────────────────────────────────────────────

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self.root, fg_color=PANEL, height=28, corner_radius=0)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)

        self._stat_conn = ctk.CTkLabel(
            bar, text="◉  0 connected",
            font=ctk.CTkFont(family="Consolas", size=10), text_color=MUTED)
        self._stat_conn.pack(side="left", padx=14)

        ctk.CTkFrame(bar, width=1, fg_color=BORDER).pack(side="left", fill="y", pady=4)

        self._stat_msg = ctk.CTkLabel(
            bar, text="Ready",
            font=ctk.CTkFont(family="Consolas", size=10), text_color=MUTED)
        self._stat_msg.pack(side="left", padx=14)

    # ────────────────────────────────────────────────────────────────
    #  에이전트 관리
    # ────────────────────────────────────────────────────────────────

    def _show_connect_dialog(self):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Connect Agent")
        dlg.geometry("320x160")
        dlg.configure(fg_color=PANEL)
        dlg.grab_set()
        dlg.resizable(False, False)

        ctk.CTkLabel(dlg, text="Host / IP", font=ctk.CTkFont(size=11),
                      text_color=MUTED).grid(row=0, column=0, padx=16, pady=(16, 4), sticky="w")
        host_e = ctk.CTkEntry(dlg, placeholder_text="192.168.1.100",
                               fg_color=BG, border_color=BORDER,
                               font=ctk.CTkFont(family="Consolas"))
        host_e.grid(row=1, column=0, padx=16, pady=4, sticky="ew")

        ctk.CTkLabel(dlg, text="Port", font=ctk.CTkFont(size=11),
                      text_color=MUTED).grid(row=0, column=1, padx=(4, 16), pady=(16, 4), sticky="w")
        port_e = ctk.CTkEntry(dlg, placeholder_text="9000", width=70,
                               fg_color=BG, border_color=BORDER,
                               font=ctk.CTkFont(family="Consolas"))
        port_e.grid(row=1, column=1, padx=(4, 16), pady=4)
        dlg.columnconfigure(0, weight=1)

        def do_connect():
            host = host_e.get().strip()
            port = int(port_e.get().strip() or "9000")
            dlg.destroy()
            agent = self.manager.add(host, port)
            agent.auto_reconnect = self._ar_switch.get()
            agent.connect()
            self._add_card(agent)
            self._save_agent_list()
            self._status(f"Connecting to {agent}…")

        ctk.CTkButton(dlg, text="Connect", fg_color=GREEN, hover_color="#2ea043",
                       text_color="#0d1117", font=ctk.CTkFont(weight="bold"),
                       command=do_connect).grid(
                           row=2, column=0, columnspan=2,
                           padx=16, pady=(8, 16), sticky="ew")
        host_e.focus()
        dlg.bind("<Return>", lambda _: do_connect())

    def _add_card(self, agent: AgentConnection):
        card = AgentCard(
            self._agent_scroll, agent,
            on_select=self._select_card,
            on_view=lambda a: self._open_remote_view_for(a))
        card.grid(row=len(self._cards), column=0, sticky="ew",
                  padx=2, pady=3)
        self._cards.append(card)

    def _select_card(self, card: AgentCard):
        if self._sel:
            self._sel.set_selected(False)
        self._sel = card
        card.set_selected(True)

    def _remove_selected(self):
        if not self._sel:
            return
        agent = self._sel.agent
        self.manager.remove(agent.host, agent.port)
        self._sel.destroy()
        self._cards.remove(self._sel)
        self._sel = None
        self._save_agent_list()
        self._status(f"Removed agent")

    def _refresh_cards(self):
        n = self.manager.connected_count
        self._stat_conn.configure(
            text=f"◉  {n} connected",
            text_color=GREEN if n > 0 else MUTED)
        for card in self._cards:
            card.refresh()

    def _tick(self):
        self._refresh_cards()
        self.root.after(1500, self._tick)

    def _open_remote_view(self):
        if not self._sel:
            self._status("Select an agent first")
            return
        self._open_remote_view_for(self._sel.agent)

    def _open_remote_view_for(self, agent: AgentConnection):
        if not agent.is_connected:
            self._status("Agent is offline")
            return
        from ui.remote_view import RemoteViewWindow
        RemoteViewWindow(agent, self._secret)
        self._status(f"Remote View: {agent}")

    # ────────────────────────────────────────────────────────────────
    #  HID 명령
    # ────────────────────────────────────────────────────────────────

    def _key_press(self):
        vk, mods = self._parse_kb()
        if vk is None: return
        self.manager.broadcast(Command.key_press(vk, mods))
        self._status(f"Key press  0x{vk:02X}  {mods or ''}")

    def _key_release(self):
        vk, mods = self._parse_kb()
        if vk is None: return
        self.manager.broadcast(Command.key_release(vk, mods))
        self._status(f"Key release  0x{vk:02X}")

    def _key_tap(self):
        vk, mods = self._parse_kb()
        if vk is None: return
        self.manager.broadcast(Command.key_press(vk, mods))
        self.manager.broadcast(Command.key_release(vk, mods))
        self._status(f"Key tap  0x{vk:02X}")

    def _quick_tap(self, vk: int, mods: list):
        self.manager.broadcast(Command.key_press(vk, mods))
        self.manager.broadcast(Command.key_release(vk, mods))
        self._status(f"Quick tap  0x{vk:02X}")

    def _parse_kb(self):
        try:
            vk   = int(self._vk_entry.get().strip(), 16)
            mods = [m.strip() for m in self._mod_entry.get().split(",") if m.strip()]
            return vk, mods
        except ValueError:
            self._status("Invalid VK code")
            return None, None

    def _mouse_move(self):
        x, y = int(self._mx.get()), int(self._my.get())
        self.manager.broadcast(Command.mouse_move(x, y))
        self._status(f"Mouse move  ({x}, {y})")

    def _mouse_click(self, button: str):
        self.manager.broadcast(Command.mouse_down(button))
        self.manager.broadcast(Command.mouse_up(button))
        self._status(f"Mouse click  {button}")

    def _scroll(self, direction: int):
        delta = int(self._scroll_delta.get()) * direction
        self.manager.broadcast(Command.mouse_scroll(delta))
        self._status(f"Scroll  {delta:+d}")

    # ────────────────────────────────────────────────────────────────
    #  Script 실행
    # ────────────────────────────────────────────────────────────────

    def _run_script(self):
        self._macro_stop = False
        lines  = self._script.get("1.0", "end").splitlines()
        repeat = max(1, int(self._repeat_var.get() or 1))
        threading.Thread(
            target=self._script_thread, args=(lines, repeat), daemon=True).start()

    def _script_thread(self, lines: list[str], repeat: int):
        total = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
        done  = 0
        for r in range(repeat):
            if self._macro_stop: break
            for line in lines:
                if self._macro_stop: break
                line = line.strip()
                if not line or line.startswith("#"): continue
                parts = line.split()
                try:
                    cmd = parts[0]
                    if cmd == "key_tap":
                        vk = int(parts[1], 16)
                        self.manager.broadcast(Command.key_press(vk))
                        self.manager.broadcast(Command.key_release(vk))
                    elif cmd == "mouse_move":
                        self.manager.broadcast(Command.mouse_move(int(parts[1]), int(parts[2])))
                    elif cmd == "mouse_click":
                        b = parts[1] if len(parts) > 1 else "left"
                        self.manager.broadcast(Command.mouse_down(b))
                        self.manager.broadcast(Command.mouse_up(b))
                    elif cmd == "delay":
                        time.sleep(int(parts[1]) / 1000.0)
                except Exception as e:
                    print(f"[Script] '{line}': {e}")
                done += 1
                pct = int(done / (total * repeat) * 100)
                self.root.after(0, lambda p=pct, ri=r+1: self._script_status.configure(
                    text=f"Run {ri}/{repeat}  ·  {p}%", text_color=GREEN))
        self.root.after(0, lambda: self._script_status.configure(
            text="Completed" if not self._macro_stop else "Stopped",
            text_color=GREEN if not self._macro_stop else YELLOW))

    def _stop_script(self):
        self._macro_stop = True
        self._status("Script stopped")

    # ────────────────────────────────────────────────────────────────
    #  설정
    # ────────────────────────────────────────────────────────────────

    def _apply_secret(self):
        self._secret = self._secret_entry.get()
        self._status("Secret updated — reconnect agents to apply")

    def _save_settings(self):
        self._cfg["fps"]    = int(self._fps_slider.get())
        self._cfg["secret"] = self._secret_entry.get()
        save_config(self._cfg)
        self._status("Settings saved")

    def _save_agent_list(self):
        self._cfg["agents"] = [
            {"host": a.agent.host, "port": a.agent.port}
            for a in self._cards]
        save_config(self._cfg)

    def _restore_agents(self):
        for entry in self._cfg.get("agents", []):
            agent = self.manager.add(entry["host"], entry["port"])
            agent.auto_reconnect = True
            agent.connect()
            self._add_card(agent)

    # ────────────────────────────────────────────────────────────────

    def _status(self, msg: str):
        self._stat_msg.configure(text=msg)

    def run(self):
        self.root.mainloop()


# ──────────────────────────────────────────────────────────────────────
#  UI 헬퍼 함수
# ──────────────────────────────────────────────────────────────────────

def _lbl(parent, text: str, small: bool = False) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent, text=text,
        font=ctk.CTkFont(
            size=9 if small else 10,
            weight="bold" if not small else "normal"),
        text_color=MUTED if small else TEXT)


def _entry(parent, placeholder: str = "", width: int = 160) -> ctk.CTkEntry:
    return ctk.CTkEntry(
        parent, placeholder_text=placeholder, width=width,
        fg_color=BG, border_color=BORDER,
        font=ctk.CTkFont(family="Consolas", size=11),
        text_color=TEXT)


def _action_btn(parent, text: str, color: str,
                command, width: int = 100, height: int = 32,
                text_color: str = TEXT) -> ctk.CTkButton:
    return ctk.CTkButton(
        parent, text=text, width=width, height=height,
        fg_color=color,
        hover_color=_darken(color),
        text_color=text_color,
        font=ctk.CTkFont(weight="bold", size=11),
        corner_radius=7,
        command=command)


def _darken(hex_color: str) -> str:
    """색상을 약간 어둡게."""
    _map = {
        "#3fb950": "#2ea043",
        "#58a6ff": "#4a8fd4",
        "#f85149": "#da3633",
        "#1c2128": "#2d333b",
        "#21262d": "#2d333b",
        "#30363d": "#444c56",
    }
    return _map.get(hex_color, "#444c56")
