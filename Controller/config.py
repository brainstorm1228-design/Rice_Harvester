import json
import os
import re

DEFAULT_PORT   = 9000
DEFAULT_SECRET = "change-this-secret"
APP_NAME       = "Rice_Harvester"


def _default_config_path() -> str:
    base = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("APPDATA")
        or os.path.expanduser("~")
    )
    return os.path.join(base, APP_NAME, "rice_harvester.json")


CONFIG_PATH = os.environ.get("RICE_HARVESTER_CONFIG", _default_config_path())


def _default_flows_dir() -> str:
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs, "Rice Harvester", "flows")


FLOWS_DIR = os.environ.get("RICE_HARVESTER_FLOWS_DIR", _default_flows_dir())


def _safe_flow_filename(name: str) -> str:
    safe = re.sub(r'[<>:"/\\\\|?*\\x00-\\x1f]', "_", name).strip().strip(".")
    return safe or "workflow"


def load_workflows() -> list[dict]:
    workflows: list[dict] = []
    if not os.path.isdir(FLOWS_DIR):
        return workflows
    for filename in sorted(os.listdir(FLOWS_DIR), key=str.lower):
        if not filename.lower().endswith(".json"):
            continue
        path = os.path.join(FLOWS_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                wf = json.load(f)
            name = wf.get("name") or os.path.splitext(filename)[0]
            steps = wf.get("steps", [])
            if name and isinstance(steps, list):
                workflows.append({"name": name, "steps": steps})
        except Exception:
            continue
    return workflows


def save_workflow_file(workflow: dict):
    name = workflow.get("name", "").strip()
    if not name:
        raise ValueError("workflow name is required")
    os.makedirs(FLOWS_DIR, exist_ok=True)
    path = os.path.join(FLOWS_DIR, f"{_safe_flow_filename(name)}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"name": name, "steps": workflow.get("steps", [])}, f, indent=2, ensure_ascii=False)
    return path


def delete_workflow_file(name: str):
    path = os.path.join(FLOWS_DIR, f"{_safe_flow_filename(name)}.json")
    if os.path.exists(path):
        os.remove(path)


def load_config() -> dict:
    disk_workflows = load_workflows()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return {
                    "theme": cfg.get("theme", "dark"),
                    "secret": cfg.get("secret", DEFAULT_SECRET),
                    "agents": cfg.get("agents", []),
                    "fps": cfg.get("fps", 10),
                    "target_mode": cfg.get("target_mode", "selected"),
                    "presets": cfg.get("presets", []),
                    "workflows": disk_workflows or cfg.get("workflows", cfg.get("presets", [])),
                    "delay_min_ms": cfg.get("delay_min_ms", 0),
                    "delay_max_ms": cfg.get("delay_max_ms", 0),
                    "monitor_names": cfg.get("monitor_names", {}),
                    "monitor_order": cfg.get("monitor_order", []),
                }
        except Exception:
            pass
    return {
        "secret": DEFAULT_SECRET,
        "agents": [],
        "fps": 10,
        "target_mode": "selected",
        "presets": [],
        "workflows": disk_workflows,
        "delay_min_ms": 0,
        "delay_max_ms": 0,
        "monitor_names": {},
        "monitor_order": [],
    }


def save_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
