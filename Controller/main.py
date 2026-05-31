import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from config import DEFAULT_SECRET, load_config
from network.agent_manager import AgentManager
from ui.main_window import MainWindow


def main():
    cfg = load_config()
    secret = os.environ.get("AGENT_SECRET") or cfg.get("secret") or DEFAULT_SECRET
    manager = AgentManager(secret=secret)
    MainWindow(manager, secret=secret).run()


if __name__ == "__main__":
    main()
