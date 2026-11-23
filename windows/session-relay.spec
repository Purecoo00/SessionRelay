# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH).resolve().parent
assets = root / "windows"
icon = str(assets / "app.ico")
translations = [(str(root / lang / "Localizable.strings"), lang) for lang in ("en.lproj", "zh-Hans.lproj")]

frontend = Analysis(
    [str(assets / "app.py")], pathex=[str(root)],
    datas=translations + [(icon, "windows"), (str(assets / "icons"), "windows/icons")],
)
worker = Analysis([str(assets / "worker.py")], pathex=[str(root)])
gui_exe = EXE(
    PYZ(frontend.pure), frontend.scripts, [], exclude_binaries=True,
    name="Session Relay", console=False, icon=icon, upx=False,
)
worker_exe = EXE(
    PYZ(worker.pure), worker.scripts, [], exclude_binaries=True,
    name="relay-worker", console=True, upx=False,
)
bundle = COLLECT(
    gui_exe, worker_exe, frontend.binaries, frontend.datas, worker.binaries, worker.datas,
    name="Session Relay", upx=False,
)
