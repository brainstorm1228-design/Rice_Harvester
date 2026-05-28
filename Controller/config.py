import json
import os

DEFAULT_PORT   = 9000
DEFAULT_SECRET = "change-this-secret"
APP_NAME       = "Rice_Harvester"
CONFIG_PATH    = os.path.join(os.path.dirname(__file__), "rice_harvester.json")


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"secret": DEFAULT_SECRET, "agents": [], "fps": 10}


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
