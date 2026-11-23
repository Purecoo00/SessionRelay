"""PySide6 frontend. Run from the repository with python -m windows.app."""
import argparse
import os
import sys

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication

from windows.demo import Snapshot, seed
from windows.model import Language, Store
from windows.window import Window


def main():
    parser = argparse.ArgumentParser(prog="Session Relay")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--snapshot", metavar="FOLDER", default=os.environ.get("SESSION_RELAY_SNAPSHOT"))
    parser.add_argument("--lang", choices=("en", "zh"))
    parser.add_argument("--theme", choices=("system", "light", "dark"), default="system")
    args = parser.parse_args()
    demo = args.demo or bool(args.snapshot) or "SESSION_RELAY_DEMO" in os.environ
    language = args.lang or os.environ.get("SESSION_RELAY_LANG") or QLocale.system().name()
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Session Relay")
    app.setStyle("Fusion")
    if sys.platform == "win32":
        font = app.font()
        font.setFamilies(["Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI"])
        app.setFont(font)
    store = Store(Language("zh" if language.lower().startswith("zh") else "en"), demo=demo)
    if demo:
        seed(store)
    window = Window(store, args.theme)
    window.show()
    if args.snapshot:
        snapshot = Snapshot(app, window, args.snapshot)
        snapshot.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
