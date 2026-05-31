import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, List, Any


@dataclass
class KeyboardData:
    key_code: int
    modifiers: List[str] = field(default_factory=list)
    text: Optional[str] = None

    def to_dict(self):
        return {"keyCode": self.key_code, "modifiers": self.modifiers, "text": self.text}


@dataclass
class MouseData:
    x: int = 0
    y: int = 0
    absolute: bool = True
    button: str = "left"
    scroll_delta: int = 0

    def to_dict(self):
        return {
            "x": self.x, "y": self.y,
            "absolute": self.absolute,
            "button": self.button,
            "scrollDelta": self.scroll_delta,
        }


class Command:
    def __init__(self, cmd_type: str, action: str,
                 keyboard: Optional[KeyboardData] = None,
                 mouse: Optional[MouseData] = None,
                 data: Optional[dict[str, Any]] = None,
                 request_id: Optional[str] = None):
        self.type = cmd_type
        self.action = action
        self.keyboard = keyboard
        self.mouse = mouse
        self.data = data
        self.request_id = request_id
        self.ts = int(time.time() * 1000)

    def to_json(self) -> bytes:
        d = {"type": self.type, "action": self.action, "ts": self.ts}
        if self.request_id:
            d["requestId"] = self.request_id
        if self.keyboard:
            d["keyboard"] = self.keyboard.to_dict()
        if self.mouse:
            d["mouse"] = self.mouse.to_dict()
        if self.data is not None:
            d["data"] = self.data
        return json.dumps(d).encode("utf-8")

    # ---- 팩토리 메서드 ----

    @staticmethod
    def key_press(key_code: int, modifiers: Optional[List[str]] = None) -> "Command":
        return Command("keyboard", "press", keyboard=KeyboardData(key_code, modifiers or []))

    @staticmethod
    def key_release(key_code: int, modifiers: Optional[List[str]] = None) -> "Command":
        return Command("keyboard", "release", keyboard=KeyboardData(key_code, modifiers or []))

    @staticmethod
    def mouse_move(x: int, y: int, absolute: bool = True) -> "Command":
        return Command("mouse", "move", mouse=MouseData(x=x, y=y, absolute=absolute))

    @staticmethod
    def mouse_down(button: str = "left") -> "Command":
        return Command("mouse", "down", mouse=MouseData(button=button))

    @staticmethod
    def mouse_up(button: str = "left") -> "Command":
        return Command("mouse", "up", mouse=MouseData(button=button))

    @staticmethod
    def mouse_scroll(delta: int) -> "Command":
        return Command("mouse", "scroll", mouse=MouseData(scroll_delta=delta))

    @staticmethod
    def request(cmd_type: str, action: str, data: Optional[dict[str, Any]] = None) -> "Command":
        return Command(cmd_type, action, data=data, request_id=str(uuid.uuid4()))
