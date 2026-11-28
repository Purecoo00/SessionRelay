"""Qt views for the same sidebar, setup, conversation and activity layout as SwiftUI."""
import html
import re
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLocale, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from windows.model import ROOT, last_path_part
from windows.symbols import RoundLimit, button_icon, pixmap, symbol_label

PAGE = {"setup": ("设置", "sliders"), "chat": ("对话", "conversation"), "log": ("运行记录", "activity")}
ACCENT = "#d97757"
COLORS = {
    "light": dict(bg="#fdfdfd", side="#f8f8f8", card="#f5f5f5", bubble="#ffffff", text="#222222",
                  muted="#747474", edge="#e9e9e9", control="#e9e9e9", hover="#dfdfdf", selected="#f7e8e2",
                  prompt="#fcf1ec", prompt_edge="#edd1c3", green="#247a3c", green_bg="#daf1dd",
                  orange="#a45e15", orange_bg="#fce9d1", red="#ad3333", red_bg="#fae3e1"),
    "dark": dict(bg="#1e1e1e", side="#1b1b1b", card="#292929", bubble="#1e1e1e", text="#eeeeee",
                 muted="#a5a5a5", edge="#303030", control="#353535", hover="#474747", selected="#362923",
                 prompt="#2d2522", prompt_edge="#50382f", green="#71da85", green_bg="#223c2a",
                 orange="#eea15d", orange_bg="#433223", red="#fa8585", red_bg="#442828"),
}


def mono_families():
    if sys.platform == "win32":
        return '"Cascadia Mono", "Consolas", "Microsoft YaHei UI"'
    return '"' + QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family() + '"'


def style(c):
    return f"""
    QWidget {{ color: {c['text']}; font-size: 13px; }}
    QMainWindow, QWidget#surface, QScrollArea {{ background: {c['bg']}; }}
    QWidget#sidebar, QWidget#brand {{ background: {c['side']}; }}
    QWidget#sidebar {{ border-right: 1px solid {c['edge']}; }}
    QWidget#header {{ border-bottom: 1px solid {c['edge']}; }}
    QWidget#actions {{ border-top: 1px solid {c['edge']}; }}
    QLabel[muted="true"] {{ color: {c['muted']}; }}
    QLabel[caption="true"] {{ font-size: 11px; }}
    QLabel[strong="true"] {{ font-weight: 600; }}
    QLabel[mono="true"], QLineEdit[mono="true"] {{ font-family: {mono_families()}; }}
    QFrame#line {{ background: {c['edge']}; max-height: 1px; min-height: 1px; }}
    QFrame#group {{ background: {c['card']}; border-radius: 12px; }}
    QPushButton {{ background: {c['control']}; border: 0; border-radius: 6px; padding: 4px 12px; }}
    QPushButton:hover {{ background: {c['hover']}; }}
    QPushButton:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
    QPushButton:disabled {{ color: {c['muted']}; }}
    QPushButton[primary="true"] {{ background: {ACCENT}; color: white; font-weight: 600; }}
    QPushButton[primary="true"]:hover {{ background: #c96d4f; }}
    QPushButton[primary="true"]:disabled {{ background: {c['control']}; color: {c['muted']}; }}
    QPushButton[tool="true"] {{ background: transparent; color: {c['muted']}; padding: 3px 7px; }}
    QPushButton[tool="true"]:hover {{ background: {c['control']}; }}
    QPushButton[tool="true"]:disabled {{ color: {c['edge']}; }}
    QPushButton[page="true"] {{ background: transparent; text-align: left; padding-left: 11px; }}
    QPushButton[page="true"]:hover, QWidget[pair="true"]:hover {{ background: {c['card']}; }}
    QPushButton[page="true"]:checked, QWidget[pair="true"][current="true"] {{
        background: {c['selected']}; border-radius: 8px; font-weight: 600;
    }}
    QWidget[pair="true"] {{ border-radius: 8px; }}
    QFrame#segments {{ background: {c['control']}; border-radius: 6px; }}
    QFrame#segments QPushButton {{ background: transparent; border-radius: 5px; }}
    QFrame#segments QPushButton:checked {{ background: {c['hover']}; }}
    QLineEdit {{ background: transparent; border: 1px solid transparent; padding: 3px; }}
    QLineEdit:focus, QTextEdit:focus {{ border: 1px solid {ACCENT}; border-radius: 4px; }}
    QSpinBox, QTextEdit {{ background: {c['control']}; border: 1px solid {c['edge']};
                                     border-radius: 5px; padding: 3px 6px; }}
    QSpinBox {{ padding-right: 20px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 19px; height: 13px;
                                                 background: {c['control']}; }}
    QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 5px; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 5px; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {c['hover']}; }}
    QSpinBox::up-arrow, QSpinBox::down-arrow {{ width: 0px; height: 0px; }}
    QWidget#actions QPushButton {{ border-radius: 14px; padding: 4px 14px; }}
    QFrame#toolbar {{ background: {c['bg']}; border: 1px solid {c['edge']}; border-radius: 17px; }}
    QPushButton#sidebarSwitch {{ border: 1px solid {c['edge']}; border-radius: 17px; padding: 0; }}
    QMenu, QListView {{ background: {c['card']}; border: 1px solid {c['edge']}; }}
    QMenu::item:selected, QListView::item:selected {{ background: {c['selected']}; }}
    QScrollBar:vertical {{ width: 8px; margin: 1px; background: transparent; }}
    QScrollBar::handle:vertical {{ background: {c['edge']}; border-radius: 3px; min-height: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        height: 0; background: transparent;
    }}
    """


def label(text="", muted=False, caption=False, strong=False, wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    for key, value in dict(muted=muted, caption=caption, strong=strong).items():
        widget.setProperty(key, value)
    widget.setWordWrap(wrap)
    return widget


def button(text, action, *, tool=False, primary=False, tip=""):
    widget = QPushButton(text)
    widget.setProperty("tool", tool)
    widget.setProperty("primary", primary)
    widget.setToolTip(tip)
    if not text:
        widget.setAccessibleName(tip)
    widget.clicked.connect(action)
    return widget


def layout(parent=None, orientation="v", margins=(0, 0, 0, 0), spacing=0):
    result = (QVBoxLayout if orientation == "v" else QHBoxLayout)(parent)
    result.setContentsMargins(*margins)
    result.setSpacing(spacing)
    return result


def line():
    frame = QFrame()
    frame.setObjectName("line")
    return frame


def clear(container):
    while container.count():
        item = container.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        elif item.layout() is not None:
            clear(item.layout())


def scroll(widget):
    area = QScrollArea()
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidgetResizable(True)
    area.setWidget(widget)
    return area


def open_path(path):
    if path:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def file_label(text):
    widget = label(text)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


class PairRow(QWidget):
    def __init__(self, window, pair):
        super().__init__()
        self.window, self.pair = window, pair
        self.setProperty("pair", True)
        self.setProperty("current", window.store.selected == pair.id)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedHeight(44)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = layout(self, "h", (8, 0, 8, 0), 10)
        current = window.store.selected == pair.id
        name = "link" if pair.relayMode == "live" else "cycle"
        self.icon = symbol_label(name, "white" if current else ACCENT, 16)
        self.icon.setStyleSheet(f"background: {ACCENT if current else window.colors['selected']};"
                                f"color: {'white' if current else ACCENT}; border-radius: 7px;")
        self.icon.setFixedSize(26, 26)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.icon)
        names = layout(spacing=1)
        name = label(window.store.title(pair), strong=current)
        name.setToolTip(name.text())
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        name.setText(name.fontMetrics().elidedText(name.text(), Qt.TextElideMode.ElideRight, 133))
        names.addWidget(name)
        folder = Path(pair.project).name if pair.project else window.L("未选择项目")
        mode = window.L("原会话接力" if pair.relayMode == "live" else "App 驱动")
        subtitle = label(f"{folder} · {mode}", muted=True, caption=True)
        subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        names.addWidget(subtitle)
        row.addLayout(names, 1)
        run = window.store.run(pair.id)
        tone = ("good" if run.busy else ("warn" if run.live_paused else "good")
                if pair.relayMode == "live" and run.live_enabled else run.tone)
        dot = label()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f"background: {window.tone_color(tone)}; border-radius: 3px;")
        row.addWidget(dot)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.store.select(self.pair.id)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Space):
            self.window.store.select(self.pair.id)
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        self.window.pair_menu(self.pair, event.globalPos())


class Window(QMainWindow):
    def __init__(self, store, theme):
        super().__init__()
        self.store, self.L = store, store.language
        self.setWindowTitle("Session Relay")
        self.setWindowIcon(QIcon(str(ROOT / "windows" / "app.ico")))
        self.setMinimumSize(940, 640)
        self.resize(1120, 760)
        self.action_state = self.note_state = None
        self.theme = theme
        self.chat_pending = False
        self.current_page = ""
        self.setting_controls = None

        surface = QWidget()
        surface.setObjectName("surface")
        self.setCentralWidget(surface)
        root = layout(surface, "h")

        sidebar = self.sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        sidebar.setFixedWidth(230)
        left = layout(sidebar, margins=(10, 6, 10, 9), spacing=5)
        self.sidebar_button = button("", self.toggle_sidebar, tool=True, tip=self.L("配对"))
        self.sidebar_button.setObjectName("sidebarSwitch")
        self.sidebar_button.setFixedSize(34, 34)
        left.addWidget(self.sidebar_button, 0, Qt.AlignmentFlag.AlignRight)
        brand = QWidget()
        brand.setObjectName("brand")
        brand_row = layout(brand, "h", (8, 5, 0, 9), 10)
        icon = label()
        icon.setPixmap(self.windowIcon().pixmap(34, 34))
        brand_row.addWidget(icon)
        brand_text = layout()
        brand_text.addWidget(label("Session Relay", strong=True))
        brand_text.addWidget(label("Claude ⇄ Codex", muted=True, caption=True))
        brand_row.addLayout(brand_text, 1)
        left.addWidget(brand)
        pairs_heading = layout(orientation="h", margins=(10, 2, 3, 0))
        pairs_heading.addWidget(label(self.L("配对"), muted=True, caption=True, strong=True), 1)
        self.new_pair = button("", lambda: store.add(), tool=True, tip=self.L("新建配对"))
        pairs_heading.addWidget(self.new_pair)
        self.new_pair.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        left.addLayout(pairs_heading)
        list_view = QWidget()
        self.pair_rows = layout(list_view, spacing=2)
        self.pair_rows.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.pair_scroll = scroll(list_view)
        self.pair_scroll.setStyleSheet("QScrollArea {background: transparent;}")
        list_view.setStyleSheet("QWidget#pairList {background: transparent;}")
        list_view.setObjectName("pairList")
        left.addWidget(self.pair_scroll)
        current_heading = layout(margins=(10, 12, 0, 0))
        current_heading.addWidget(label(self.L("当前配对"), muted=True, caption=True, strong=True))
        left.addLayout(current_heading)
        self.pages = {}
        for key, (title, _) in PAGE.items():
            row = button(self.L(title), lambda _=False, k=key: self.set_page(k))
            row.setProperty("page", True)
            row.setCheckable(True)
            row.setFixedHeight(32)
            row.setAccessibleName(self.L(title))
            self.pages[key] = row
            if key == "chat":
                inside = layout(row, "h", (0, 0, 10, 0))
                inside.addStretch()
                self.badge = label(muted=True, caption=True, strong=True)
                self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.badge.setMinimumWidth(21)
                self.badge.setFixedHeight(16)
                self.badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                inside.addWidget(self.badge)
            left.addWidget(row)
        left.addStretch()
        root.addWidget(sidebar)

        main = QWidget()
        column = layout(main)
        root.addWidget(main, 1)
        header = QWidget()
        header.setObjectName("header")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        header.setFixedHeight(53)
        top = layout(header, "h", (20, 0, 15, 0), 10)
        self.show_sidebar = button("", self.toggle_sidebar, tool=True, tip=self.L("配对"))
        self.show_sidebar.setObjectName("sidebarSwitch")
        self.show_sidebar.setFixedSize(34, 34)
        self.show_sidebar.hide()
        top.addWidget(self.show_sidebar)
        heading = layout()
        self.heading = label(strong=True)
        self.subtitle = label(muted=True, caption=True)
        heading.addWidget(self.heading)
        heading.addWidget(self.subtitle)
        heading_wrap = QWidget()
        heading_wrap.setLayout(heading)
        top.addWidget(heading_wrap, 1, Qt.AlignmentFlag.AlignVCenter)
        self.status = QFrame()
        self.status.setObjectName("statusPill")
        status_row = layout(self.status, "h", (10, 0, 10, 0), 6)
        self.status_icon = label()
        self.status_text = label(strong=True)
        status_row.addWidget(self.status_icon)
        status_row.addWidget(self.status_text)
        self.status.setFixedHeight(25)
        top.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        tools = QWidget()
        right = layout(tools, "h", spacing=4)
        right.addStretch()
        self.toolbar = QFrame()
        self.toolbar.setObjectName("toolbar")
        toolbar = layout(self.toolbar, "h", (4, 0, 4, 0))
        self.digest_button = button("", lambda: open_path(self.run.digest), tool=True, tip=self.L("打开 LATEST.md"))
        self.folder_button = button("", lambda: open_path(self.run.folder) if not store.demo else None,
                                    tool=True, tip=self.L("运行目录"))
        self.digest_button.setAccessibleName(self.L("最新摘要"))
        self.folder_button.setAccessibleName(self.L("运行目录"))
        for control in (self.digest_button, self.folder_button):
            control.setFixedSize(31, 34)
            toolbar.addWidget(control)
        right.addWidget(self.toolbar, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(tools, 1)
        column.addWidget(header)

        self.stack = QStackedWidget()
        self.views = {}
        self.contents = {}
        for page in PAGE:
            frame = QWidget()
            frame.setObjectName("surface")
            self.contents[page] = layout(frame)
            self.views[page] = scroll(frame)
            self.stack.addWidget(self.views[page])
        column.addWidget(self.stack, 1)
        self.note_bar = QWidget()
        self.note_layout = layout(self.note_bar, margins=(16, 0, 16, 10))
        self.note_bar.hide()
        column.addWidget(self.note_bar)
        action_bar = QWidget()
        action_bar.setObjectName("actions")
        action_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        action_bar.setFixedHeight(53)
        self.actions = layout(action_bar, "h", (20, 0, 20, 0), 10)
        column.addWidget(action_bar)

        store.changed.connect(self.changed)
        store.storage_error.connect(self.show_error)
        timer = QTimer(self)
        timer.timeout.connect(self.tick)
        timer.start(4000)
        app = QApplication.instance()
        app.applicationStateChanged.connect(self.app_state)
        app.styleHints().colorSchemeChanged.connect(self.system_theme_changed)
        self.apply_theme(theme)
        self.selection_changed()

    @property
    def pair(self):
        return self.store.current

    @property
    def run(self):
        return self.store.run(self.store.selected)

    def tone_color(self, tone):
        return self.colors[{"warn": "orange", "bad": "red", "good": "green",
                            "active": "green"}.get(tone, "muted")]

    def system_theme_changed(self, _scheme):
        if self.theme == "system":
            self.apply_theme("system")

    def apply_theme(self, theme):
        self.theme = theme
        dark = (theme == "dark" or (theme == "system" and
                QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark))
        self.colors = COLORS["dark" if dark else "light"]
        palette = QPalette()
        for role, key in ((QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.Base, "card"),
                          (QPalette.ColorRole.WindowText, "text"), (QPalette.ColorRole.Text, "text"),
                          (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Button, "control"),
                          (QPalette.ColorRole.Highlight, "selected"), (QPalette.ColorRole.HighlightedText, "text")):
            palette.setColor(role, QColor(self.colors[key]))
        self.setPalette(palette)
        self.setStyleSheet(style(self.colors))
        for control, symbol, color, size in (
                (self.sidebar_button, "sidebar", self.colors["text"], 19),
                (self.show_sidebar, "sidebar", self.colors["text"], 19),
                (self.new_pair, "plus", ACCENT, 16),
                (self.digest_button, "document", self.colors["text"], 18),
                (self.folder_button, "folder", self.colors["text"], 19)):
            button_icon(control, symbol, color, size, self.colors["muted"])
        self.update_page_icons()
        self.action_state = self.note_state = None
        self.render_sidebar()
        self.render_header()
        self.render_setup()
        self.render_chat(reset=True)
        self.render_log()
        self.render_actions()

    def toggle_sidebar(self):
        show = self.sidebar.isHidden()
        self.sidebar.setVisible(show)
        self.show_sidebar.setVisible(not show)
        (self.sidebar_button if show else self.show_sidebar).setFocus()

    def app_state(self, state):
        if state == Qt.ApplicationState.ApplicationActive:
            self.store.discover(self.pair.project)

    def tick(self):
        for pair in self.store.pairs:
            run = self.store.run(pair.id)
            if pair.id == self.store.selected and self.store.tab == "chat" and not run.busy:
                run.refresh_live(pair)
            else:
                run.refresh_flags(pair)

    def selection_changed(self):
        self.render_sidebar()
        self.set_page(self.store.tab, force=True)
        self.store.discover(self.pair.project)
        self.run.refresh_live(self.pair)
        self.select_session()

    def changed(self, id, part):
        if part == "selected":
            self.selection_changed()
            return
        if part == "discovery":
            self.render_sidebar()
            if id == self.pair.project:
                self.render_setup()
                self.render_header()
                self.select_session()
            return
        if part in ("run", "flags"):
            self.render_sidebar()
        if id != self.store.selected:
            return
        if part == "chat":
            self.update_chat_badge()
            if self.store.tab == "chat" and not self.chat_pending:
                self.chat_pending = True
                QTimer.singleShot(25, self.update_chat)
        elif part == "log":
            if self.store.tab == "log":
                self.render_log()
        else:
            if part == "created":
                self.render_setup()
            elif self.setting_controls is not None:
                self.setting_controls.setEnabled(not self.run.busy)
                self.render_live_status()
            self.render_header()
            self.render_actions()

    def set_page(self, page, force=False):
        if self.current_page == page and not force:
            return
        self.store.tab = self.current_page = page
        self.stack.setCurrentWidget(self.views[page])
        self.update_page_icons()
        self.render_header()
        if page == "chat":
            self.render_chat(reset=True)
            self.run.refresh_live(self.pair)
        elif page == "log":
            self.render_log()
        else:
            self.render_setup()
        self.render_actions()

    def update_page_icons(self):
        for key, control in self.pages.items():
            selected = self.store.tab == key
            control.setChecked(selected)
            color = ACCENT if selected else self.colors["muted"]
            button_icon(control, PAGE[key][1], color, 18, self.colors["muted"])

    def render_sidebar(self):
        pos = self.pair_scroll.verticalScrollBar().value()
        clear(self.pair_rows)
        for pair in self.store.pairs:
            self.pair_rows.addWidget(PairRow(self, pair))
        self.pair_scroll.setFixedHeight(min(225, 46 * len(self.store.pairs)))
        self.pair_scroll.verticalScrollBar().setValue(pos)
        self.update_chat_badge()

    def update_chat_badge(self):
        count = len(self.run.chat)
        self.badge.setText(str(count))
        self.badge.setVisible(count > 0)
        self.badge.setStyleSheet(f"background: {self.colors['control']}; padding: 1px 5px; border-radius: 7px;")

    def pair_menu(self, pair, pos):
        menu = QMenu(self)
        menu.addAction(self.L("复制配对"), lambda: self.store.add(pair))
        menu.addSeparator()
        delete = menu.addAction(self.L("删除配对…"), lambda: self.delete_pair(pair))
        delete.setEnabled(len(self.store.pairs) > 1 and not self.store.run(pair.id).busy)
        menu.exec(pos)

    def delete_pair(self, pair):
        if self.confirm(self.L("删除配对「%@」？", self.store.title(pair)),
                        self.L("会关闭它的原会话接力绑定。运行记录保留在项目的 .session-relay 文件夹里。"),
                        "删除", "取消", destructive=True):
            try:
                self.store.delete(pair)
            except OSError as exc:
                self.show_error(str(exc))

    def confirm(self, title, message, accept, cancel, destructive=False):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Session Relay")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(title)
        dialog.setInformativeText(message)
        quit_role = QMessageBox.ButtonRole.DestructiveRole if destructive else QMessageBox.ButtonRole.AcceptRole
        yes = dialog.addButton(self.L(accept), quit_role)
        no = dialog.addButton(self.L(cancel), QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(no if destructive else yes)
        dialog.exec()
        return dialog.clickedButton() is yes

    def show_error(self, message):
        self.run.note = message
        self.render_actions()

    def closeEvent(self, event):
        if (not self.store.demo and any(run.busy for run in self.store.runs.values()) and
                not self.confirm(self.L("交接正在进行"),
                                 self.L("现在退出会中断接力。也可以保留窗口，点「本轮后暂停」保存交接点。"),
                                 "退出", "保留窗口", destructive=True)):
            event.ignore()
            return
        self.store.stop()
        event.accept()

    def render_header(self):
        self.heading.setText(self.L(PAGE[self.store.tab][0]))
        self.subtitle.setText(self.store.title(self.pair))
        run = self.run
        color = self.tone_color(run.tone)
        bg = self.colors[{"good": "green_bg", "active": "green_bg",
                          "warn": "orange_bg", "bad": "red_bg"}.get(run.tone, "control")]
        self.status_text.setText(self.L(run.status))
        self.status_icon.setPixmap(pixmap("progress" if run.busy else "dot", color, 12 if run.busy else 8))
        self.status.setStyleSheet(f"QFrame#statusPill {{background: {bg}; border-radius: 12px;}}")
        self.toolbar.setVisible(self.store.tab != "setup")
        self.digest_button.setVisible(self.store.tab == "chat")
        self.digest_button.setEnabled(bool(run.digest and run.digest.is_file()) and not self.store.demo)
        self.folder_button.setVisible(self.store.tab != "setup")
        self.folder_button.setEnabled(bool(run.folder))

    def action(self, command, force=False):
        if command == "start":
            self.set_page("chat")
        self.run.launch(self.pair.config(command, force))

    def edit(self, key, value, rebuild=False, check=False):
        pair = self.pair
        if getattr(pair, key) == value:
            if check:
                self.select_session()
            return
        setattr(pair, key, value)
        self.store.save()
        if key in ("codex", "claude", "project", "document") and not self.run.busy and not self.store.demo:
            if self.run.checked_pair != pair.checked_key:
                self.run.checked_pair = ""
                self.run.status = "等待检查" if pair.ready else "等待选择会话"
                self.run.note = ""
        if key == "project":
            self.store.discover(pair.project)
            self.run.refresh_live(pair)
        if key in ("name", "codex", "project", "relayMode"):
            self.render_sidebar()
        if rebuild:
            self.render_setup()
        if check:
            self.select_session()
        self.render_header()
        self.render_actions()

    def select_session(self):
        pair, run = self.pair, self.run
        discovery = self.store.discovery.get(pair.project)
        if discovery is None:
            return
        sessions = discovery["sessions"]
        value = pair.claude.strip()
        last = last_path_part(value)
        sid = value
        if not value and len(sessions) == 1 and not self.store.siblings(pair):
            sid = sessions[0]["id"]
        elif last:
            sid = next((s["id"] for s in sessions if s["alias"] and s["alias"] in (last, "local_" + last)), value)
        if pair.claude != sid:
            self.edit("claude", sid, rebuild=True)
        if self.store.demo or run.busy or not pair.configured or pair.relayMode != "app":
            return
        if discovery["loggedIn"] and pair.codex and sid:
            if run.checked_pair != pair.checked_key:
                run.checked_pair = pair.checked_key
                self.action("check")
        elif run.status in ("等待选择会话", "等待登录", "已连接", "等待 Code 会话", "等待检查"):
            run.checked_pair = ""
            run.status = "等待选择会话" if discovery["loggedIn"] else "等待登录"
            self.render_header()

    def choose_project(self):
        pair = self.pair
        value = QFileDialog.getExistingDirectory(self, self.L("选择项目根目录"), pair.project)
        if value and value != pair.project:
            discovery = self.store.discovery.get(pair.project, {})
            if any(s["id"] == pair.claude for s in discovery.get("sessions", [])):
                pair.claude = ""
            if any(s["id"] == last_path_part(pair.codex) for s in discovery.get("codex", [])):
                pair.codex = ""
            self.edit("project", str(Path(value)), rebuild=True, check=True)

    def choose_document(self):
        pair = self.pair
        start = str(Path(pair.document).parent) if pair.document else pair.project
        value, _ = QFileDialog.getOpenFileName(self, self.L("选择任务文档"), start, "*.md *.markdown *.txt")
        if value:
            self.edit("document", str(Path(value)), rebuild=True, check=True)

    def create_session(self):
        if self.confirm(self.L("新建本地 Claude Code 会话？"),
                        self.L("将在项目目录打开 Claude Code 并自动填入新 ID。首次使用时请完成登录。它会先阅读任务文档，你可以补充旧 Chat 中尚未记录的决定。"),
                        "打开终端", "取消"):
            self.action("create")

    def render_setup(self):
        parent = self.contents["setup"]
        area = self.views["setup"]
        pos = area.verticalScrollBar().value()
        clear(parent)
        host = self.centered(parent, 700, bottom=19)
        self.setting_controls = host
        self.setup = layout(host, spacing=0)
        self.setup.setAlignment(Qt.AlignmentFlag.AlignTop)
        pair = self.pair
        discovery = self.store.discovery.get(pair.project, {})
        title_pair = type(pair)(pair.id, project=pair.project, codex=pair.codex)
        try:
            document = str(Path(pair.document).relative_to(pair.project)) if pair.project and pair.document else pair.document
        except ValueError:
            document = pair.document
        self.section("配对信息", [
            ("名称", self.text_field("name", self.store.title(title_pair))),
            ("项目目录", self.file_choice(pair.project, self.choose_project)),
            ("任务文档", self.file_choice(document, self.choose_document, mono=True, tip=pair.document)),
        ], self.L("任务文档是指挥者每轮阅读和更新的 Markdown 文件，可以放在项目里的任何位置。名称留空时使用 Codex 会话的标题。"))

        account = self.store.discovery_error.get(pair.project) or discovery.get("claudeError")
        if not account:
            if not pair.project:
                account = self.L("先选择项目目录")
            elif not discovery:
                account = self.L("正在读取登录状态…")
            else:
                account = self.L("已登录" if discovery["loggedIn"] else "尚未登录")
        signed_in = discovery.get("loggedIn")
        account_icon = symbol_label("check-circle" if signed_in else "user",
                                    self.colors["green" if signed_in else "muted"], 15)
        account_label = label(account, muted=not signed_in)
        if discovery.get("loggedIn"):
            account_label.setStyleSheet(f"color: {self.colors['green']};")
        account_label.setToolTip(account)
        refresh = button(self.L("刷新"), lambda: self.store.discover(self.pair.project))
        refresh.setEnabled(bool(pair.project))
        create = button(self.L("新建会话…"), self.create_session)
        create.setEnabled(pair.configured)
        account_controls = [account_icon, account_label, refresh]
        if discovery.get("loggedIn") is False:
            account_controls.append(button(self.L("登录…"), lambda: self.action("login")))
        account_controls.append(create)
        error = discovery.get("codexError")
        self.section("会话", [
            ("Codex 会话", self.session_field("codex", "粘贴会话 ID 或链接", discovery.get("codex", []))),
            ("Claude Code 会话", self.session_field("claude", "UUID 或 local_ 标识", discovery.get("sessions", []))),
            ("Claude Code", self.controls(*account_controls)),
        ], self.L("读不到本项目的 Codex 会话列表，可以直接粘贴 ID 或链接：") + error if error else
            self.L("两边都可以从本项目的会话里选，也可以粘贴 Codex 会话的 ID 或链接、Claude Code 会话的 UUID 或桌面 Code 的 local_ 标识。"))

        live = pair.relayMode == "live"
        self.section("", [("接力方式", self.segments("relayMode", (("live", "原会话接力"), ("app", "App 驱动"))))],
                     self.L("推荐。审查会话在 Claude 桌面窗口里调用 send_to_codex 派单，并在后台收取回执，全程都在同一个对话里。"
                            if live else "由本 App 通过命令行续接 Claude 会话完成审查。审查轮次不会显示在桌面窗口里，可在「对话」页查看。"))

        limit = RoundLimit(self.colors)
        limit.setRange(1, 100)
        limit.setValue(pair.limit or 10)
        # 0 rounds means no limit: the relay stops only when the work is done, needs the user, or is paused.
        limit_rows = [("轮数上限", self.limit_picker())] + ([(None, None)] if pair.limit else [])
        unlimited = self.L("不设上限时，接力只会在任务完成、需要你确认或你暂停派单时停下。") + "\n" if not pair.limit else ""
        limit.setAccessibleName(self.L("单次接力上限：%lld 轮" if live else "单次执行上限：%lld 轮", pair.limit))
        self.limit_text = self.L("单次接力上限：%lld 轮" if live else "单次执行上限：%lld 轮", "LIMIT")
        self.limit_label = label(self.limit_text.replace("LIMIT", str(pair.limit)))
        limit.valueChanged.connect(self.change_limit)
        self.live_status = None
        if live:
            self.live_status = label()
            self.live_status_icon = label()
            self.render_live_status()
            self.section("原会话接力", [*self.limit_rows(limit_rows, limit),
                                       ("状态", self.controls(self.live_status_icon, self.live_status))],
                         unlimited + self.L("这个项目里还有其他配对。codex_relay 按调用它的 Claude Code 会话找到对应的配对，所以每个配对都要选定自己的 Claude Code 会话。"
                                if self.store.siblings(pair) else
                                "启用时会在本机为这个项目注册 codex_relay 工具，不需要 .mcp.json。注册后在审查会话里开一轮新对话，工具就会出现。"))
        else:
            rows = [
                ("指挥者", self.segments("manager", (("claude", "Claude"), ("codex", "Codex")))),
                ("执行者", self.controls(label(self.L("Codex · MCP 派单") if pair.manager == "claude" else "Claude Code"))),
                *self.limit_rows(limit_rows, limit),
                ("本次起点", self.segments("mode", (("latest", "最新执行回执"), ("goal", "从目标开始"), ("resume", "继续上次")))),
            ]
            if pair.mode != "resume":
                goal = QTextEdit()
                goal.setAcceptRichText(False)
                goal.setFixedHeight(62)
                goal.setPlaceholderText(self.L("交给指挥者的目标" if pair.mode == "goal" else "可选"))
                goal.setPlainText(pair.goal)
                goal.textChanged.connect(lambda: self.edit("goal", goal.toPlainText()))
                rows.append(("目标" if pair.mode == "goal" else "补充说明", goal))
            self.section("App 驱动", rows, unlimited.strip())
        host.setEnabled(not self.run.busy)
        area.verticalScrollBar().setValue(pos)

    def limit_rows(self, rows, limit):
        return [(self.limit_label, self.controls(limit)) if key is None else (key, control) for key, control in rows]

    def limit_picker(self):
        widget = QFrame()
        widget.setObjectName("segments")
        row = layout(widget, "h", (2, 2, 2, 2))
        group = QButtonGroup(widget)
        for value, title in ((10, "设上限"), (0, "不设上限")):
            control = button(self.L(title), lambda _=False, v=value: self.set_unlimited(v))
            control.setCheckable(True)
            control.setChecked((self.pair.limit == 0) == (value == 0))
            group.addButton(control)
            row.addWidget(control)
        return widget

    def set_unlimited(self, value):
        if (self.pair.limit == 0) != (value == 0):
            self.edit("limit", value, rebuild=True)

    def change_limit(self, value):
        self.limit_label.setText(self.limit_text.replace("LIMIT", str(value)))
        self.edit("limit", value)

    def render_live_status(self):
        control = self.live_status
        if control is None:
            return
        run = self.run
        if run.live_enabled:
            text = self.L("派单已暂停" if run.live_paused else "已启用，等待审查会话派单")
            color = self.colors["orange" if run.live_paused else "green"]
        else:
            text, color = self.L("未启用"), self.colors["muted"]
        self.live_status_icon.setVisible(run.live_enabled)
        if run.live_enabled:
            self.live_status_icon.setPixmap(pixmap("pause-circle" if run.live_paused else "check-circle", color, 15))
        control.setText(text)
        control.setStyleSheet(f"color: {color};")

    def section(self, title, rows, footer=""):
        if title:
            wrapper = layout(margins=(9, 0, 9, 9))
            wrapper.addWidget(label(self.L(title), strong=True))
            self.setup.addLayout(wrapper)
        group = QFrame()
        group.setObjectName("group")
        body = layout(group, margins=(9, 0, 9, 0))
        for index, (key, control) in enumerate(rows):
            if index:
                body.addWidget(line())
            row = layout(orientation="h", spacing=12)
            row.addWidget(label(self.L(key)) if isinstance(key, str) else key)
            row.addStretch(1)
            row.addWidget(control)
            entry = QWidget()
            entry.setMinimumHeight(39)
            entry.setLayout(row)
            body.addWidget(entry)
        self.setup.addWidget(group)
        if footer:
            wrapper = layout(margins=(9, 9, 9, 0))
            wrapper.addWidget(label(footer, muted=True, caption=True, wrap=True))
            self.setup.addLayout(wrapper)
        self.setup.addSpacing(25)

    def controls(self, *widgets):
        box = QWidget()
        row = layout(box, "h", spacing=8)
        for widget in widgets:
            row.addWidget(widget)
        return box

    def text_field(self, key, placeholder, mono=False):
        widget = QLineEdit(getattr(self.pair, key))
        widget.setProperty("mono", mono)
        widget.setPlaceholderText(self.L(placeholder))
        widget.setAlignment(Qt.AlignmentFlag.AlignRight)
        widget.setMinimumWidth(305 if mono else 230)
        widget.setAccessibleName(self.L({"name": "名称", "codex": "Codex 会话", "claude": "Claude Code 会话"}[key]))
        widget.textEdited.connect(lambda value: self.edit(key, value))
        return widget

    def session_field(self, key, placeholder, sessions):
        field = self.text_field(key, placeholder, mono=True)
        if not sessions:
            return field
        dropdown = QPushButton()
        dropdown.setMaximumWidth(180)
        dropdown.setMinimumWidth(148)
        dropdown.setAccessibleName(self.L("Codex 会话" if key == "codex" else "Claude Code 会话"))
        menu = QMenu(dropdown)
        dropdown.setMenu(menu)
        by_id = {item["id"]: item["title"] for item in sessions}
        locale = QLocale("en_US" if self.L.code == "en" else "zh_CN")

        def sync(text):
            title = by_id.get(last_path_part(text), self.L("本项目会话"))
            dropdown.setText(dropdown.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, 120))
            dropdown.setToolTip(title)

        def activate(value):
            if key == "claude":
                self.run.checked_pair = ""
            field.setText(value)
            sync(value)
            self.edit(key, value, check=key == "claude")

        for item in sessions:
            dt = datetime.fromtimestamp(item["modified"])
            date = locale.toString(dt, QLocale.FormatType.ShortFormat)
            short_id = f" · {item['id'][:8]}" if key == "claude" else ""
            caption = f"{item['title']} · {date}{short_id}"
            menu.addAction(caption, lambda _checked=False, value=item["id"]: activate(value))
        field.textEdited.connect(sync)
        sync(field.text())
        return self.controls(field, dropdown)

    def file_choice(self, text, action, mono=False, tip=""):
        name = file_label(text or self.L("未选择"))
        name.setProperty("mono", mono)
        name.setProperty("muted", not bool(text))
        name.setToolTip(tip or text)
        name.setText(name.fontMetrics().elidedText(name.text(), Qt.TextElideMode.ElideMiddle, 375))
        change = button(self.L("更改…" if text else "选择…"), action)
        return self.controls(name, change)

    def segments(self, key, choices):
        widget = QFrame()
        widget.setObjectName("segments")
        row = layout(widget, "h", (2, 2, 2, 2))
        group = QButtonGroup(widget)
        for value, title in choices:
            control = button(self.L(title), lambda _=False, v=value: self.edit(key, v, rebuild=True, check=True))
            control.setCheckable(True)
            control.setChecked(getattr(self.pair, key) == value)
            group.addButton(control)
            row.addWidget(control)
        return widget

    def update_chat(self):
        self.chat_pending = False
        if self.store.tab == "chat":
            self.render_chat(follow=True)

    def render_chat(self, reset=False, follow=False):
        area = self.views["chat"]
        pos = 0 if reset else area.verticalScrollBar().value()
        parent = self.contents["chat"]
        clear(parent)
        run = self.run
        if not run.chat and not run.live_text:
            self.empty(parent, "conversation", "还没有对话", "接力开始后，每一轮的审查、发给 Codex 的指令和回执会按顺序显示在这里。")
            return
        host = self.centered(parent, 880, bottom=18)
        column = layout(host, spacing=14)
        previous = None
        for message in run.chat:
            if message["round"] != previous:
                previous = message["round"]
                row = layout(orientation="h", margins=(0, 5, 0, 0), spacing=10)
                row.addWidget(line(), 1)
                row.addWidget(label(self.L("起点") if previous == 0 else self.L("第 %lld 轮", previous),
                                    muted=True, caption=True, strong=True))
                row.addWidget(line(), 1)
                column.addLayout(row)
            column.addWidget(self.card(message))
        if run.busy and run.live_text:
            title = self.L("%@ 正在审查…" if run.stage == "review" else "%@ 正在执行…",
                           "Claude" if run.live_role == "claude" else "Codex")
            column.addWidget(self.card(dict(id="", role="live-" + run.live_role, title=title,
                                            text=run.live_text, path=""), streaming=True))
        column.addStretch()
        bar = area.verticalScrollBar()
        if (follow or reset) and not self.store.demo:
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
        else:
            QTimer.singleShot(0, lambda: bar.setValue(pos))

    def centered(self, parent, width, bottom):
        outer = layout(orientation="h", margins=(24, 18, 24, bottom))
        parent.addLayout(outer, 1)
        host = QWidget()
        host.setMaximumWidth(width)
        outer.addStretch(1)
        outer.addWidget(host, 1000)
        outer.addStretch(1)
        return host

    def card(self, message, streaming=False):
        colors = self.colors
        role, path, title, text = (message[key] for key in ("role", "path", "title", "text"))
        symbol, tint = {
            "review": ("review", ACCENT), "prompt": ("send", ACCENT), "live-claude": ("dots", ACCENT),
            "live-codex": ("dots", colors["text"]), "status": ("hourglass", colors["muted"]),
        }.get(role, ("terminal", colors["text"]))
        if role == "receipt" and path.endswith("000-receipt.txt") and not any(n in title for n in ("Codex", "Claude")):
            symbol, tint = "target", colors["muted"]
        if role == "decision":
            good = path.endswith("mcp.json") and self.L("接力受阻") not in title
            symbol, tint = ("check", colors["green"]) if good else ("alert", colors["orange"])
        fg = colors["bg"] if tint == colors["text"] else "white"
        avatar = symbol_label(symbol, fg, 18)
        avatar.setFixedSize(30, 30)
        avatar.setStyleSheet(f"background: {tint}; color: {fg}; border-radius: 15px;")
        widget = QWidget()
        row = layout(widget, "h", spacing=12)
        row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        body = QFrame()
        body.setObjectName("bubble")
        bg = colors["prompt"] if role == "prompt" else colors["bubble"]
        edge = colors["prompt_edge"] if role == "prompt" else colors["edge"]
        body.setStyleSheet(f"QFrame#bubble {{background: {bg}; border: 1px solid {edge}; border-radius: 12px;}}")
        row.addWidget(body, 1)
        col = layout(body, margins=(14, 14, 14, 14), spacing=8)
        header = layout(orientation="h", spacing=8)
        header.addWidget(label(title, strong=True))
        if streaming:
            spinner = QProgressBar()
            spinner.setRange(0, 0)
            spinner.setTextVisible(False)
            spinner.setFixedSize(35, 5)
            header.addWidget(spinner)
        header.addStretch()
        if path:
            source = button("", lambda: open_path(path) if not self.store.demo else None,
                            tool=True, tip=self.L("打开原始文件"))
            button_icon(source, "open-file", colors["muted"], 15, colors["muted"])
            header.addWidget(source)
        col.addLayout(header)
        expanded = streaming or message["id"] in self.run.expanded
        long = len(text) > 1400 or text.count("\n") >= 18
        if long and not expanded:
            text = "\n".join(text.split("\n")[:16])[:1400].rstrip() + "…"
        prose = label(wrap=True)
        prose.setTextFormat(Qt.TextFormat.RichText)
        prose.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                      Qt.TextInteractionFlag.LinksAccessibleByMouse)
        prose.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        prose.setText(rich_text(text, colors["muted"]))
        col.addWidget(prose)
        if long and not streaming:
            def toggle():
                self.run.expanded.symmetric_difference_update({message["id"]})
                self.render_chat()

            col.addWidget(button(self.L("收起" if expanded else "展开全文"), toggle, tool=True),
                          0, Qt.AlignmentFlag.AlignLeft)
        return widget

    def empty(self, parent, symbol, title, message):
        parent.addStretch(1)
        for widget in (symbol_label(symbol, self.colors["muted"], 44), label(self.L(title), strong=True),
                       label(self.L(message), muted=True, wrap=True)):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            widget.setMaximumWidth(440)
            parent.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
        parent.addStretch(1)

    def render_log(self):
        parent = self.contents["log"]
        clear(parent)
        if not self.run.entries:
            self.empty(parent, "activity", "暂无记录", "本次打开 App 以来这个配对的连接、交接和错误会记录在这里。")
            return
        body = layout(margins=(24, 16, 24, 16))
        parent.addLayout(body)
        for date, message in reversed(self.run.entries):
            row = layout(orientation="h", margins=(4, 8, 4, 8), spacing=14)
            stamp = label(date.strftime("%H:%M:%S"), muted=True, caption=True)
            stamp.setProperty("mono", True)
            stamp.setFixedWidth(70)
            row.addWidget(stamp, 0, Qt.AlignmentFlag.AlignTop)
            text = file_label(message)
            text.setWordWrap(True)
            row.addWidget(text, 1)
            body.addLayout(row)
            body.addWidget(line())
        parent.addStretch()

    def render_actions(self):
        run, pair = self.run, self.pair
        note_state = (run.note, run.tone)
        if self.note_state != note_state:
            self.note_state = note_state
            clear(self.note_layout)
            self.note_bar.setVisible(bool(run.note))
            if run.note:
                frame = QFrame()
                frame.setObjectName("notice")
                color = {"warn": "orange_bg", "bad": "red_bg", "good": "green_bg"}.get(run.tone, "prompt")
                frame.setStyleSheet(f"QFrame#notice {{background: {self.colors[color]}; border-radius: 10px;}}")
                row = layout(frame, "h", (12, 8, 9, 8), 10)
                symbol = {"warn": "alert", "bad": "error", "good": "check-circle"}.get(run.tone, "info")
                icon = symbol_label(symbol, self.tone_color(run.tone), 16)
                row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
                note = file_label(run.note)
                note.setWordWrap(True)
                row.addWidget(note, 1)
                close = button("", self.dismiss_note, tool=True, tip=self.L("关闭"))
                button_icon(close, "x", self.colors["muted"], 14, self.colors["muted"])
                row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
                self.note_layout.addWidget(frame)
        cycle = (self.L("第 %lld 轮", run.round) if run.busy and run.round > 0 else
                 self.L("审查会话派单 → Codex 执行 → 回执唤醒审查会话" if pair.relayMode == "live" else "审查 → 执行 → 回执"))
        state = (pair.id, self.store.tab, cycle, run.busy, bool(run.pause_file), run.paused_requested,
                 run.stage, pair.relayMode, run.live_enabled, run.live_paused, run.desktop_blocked,
                 bool(pair.codex), bool(pair.claude), pair.configured, pair.ready)
        if self.action_state == state:
            return
        self.action_state = state
        clear(self.actions)
        self.actions.addWidget(symbol_label("cycle", self.colors["muted"], 16))
        self.actions.addWidget(label(cycle, muted=True))
        self.actions.addStretch()

        def add(text, callback, icon="", primary=False, enabled=True, tip=""):
            control = button(self.L(text), callback, primary=primary, tip=tip)
            if icon:
                button_icon(control, icon, "white" if primary else self.colors["text"], 16, self.colors["muted"])
            control.setEnabled(enabled)
            control.setMinimumHeight(28)
            self.actions.addWidget(control)

        if run.busy:
            wording = "正在暂停" if run.paused_requested else ("暂停等待" if run.stage == "waiting" else "本轮后暂停")
            add(wording, run.pause, "pause", enabled=bool(run.pause_file) and not run.paused_requested)
        elif pair.relayMode == "live":
            if run.live_enabled:
                add("恢复派单" if run.live_paused else "暂停派单", lambda: run.set_live_pause(pair),
                    "play" if run.live_paused else "pause")
                if self.store.tab != "chat":
                    add("查看对话", lambda: self.set_page("chat"), "conversation")
            add("更新绑定" if run.live_enabled else "启用原会话接力", lambda: self.action("bind"), "link",
                enabled=bool(pair.codex) and pair.configured)
        else:
            if run.desktop_blocked:
                add("仍然继续", lambda: self.action("start", force=True),
                    tip=self.L("忽略桌面窗口刚才的活动，从保存的交接点继续"))
            add("检查连接", lambda: self.action("check"), enabled=bool(pair.codex and pair.claude) and pair.configured)
            add("开始接力", lambda: self.action("start"), "play", primary=True, enabled=pair.ready)

    def dismiss_note(self):
        self.run.note = ""
        self.render_actions()


INLINE = re.compile(r"`([^`\n]+)`|\*\*([^*\n]+)\*\*|(?<!\*)\*([^*\n]+)\*|\[([^\]\n]+)\]\((https?://[^)\s]+)\)")


def rich_text(text, muted):
    def inline(segment):
        pieces, end = [], 0
        for match in INLINE.finditer(segment):
            pieces.append(html.escape(segment[end:match.start()]))
            code, bold, italic, link, url = match.groups()
            if code is not None:
                pieces.append(f"<tt>{html.escape(code)}</tt>")
            elif bold is not None:
                pieces.append(f"<b>{html.escape(bold)}</b>")
            elif italic is not None:
                pieces.append(f"<i>{html.escape(italic)}</i>")
            else:
                pieces.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(link)}</a>')
            end = match.end()
        pieces.append(html.escape(segment[end:]))
        return "".join(pieces).replace("\n", "<br>")

    blocks, previous_tool = [], False
    for paragraph in text.split("\n\n"):
        tool = paragraph.startswith(("▸", "  ✗"))
        if blocks:
            blocks.append("<br>" if tool and previous_tool else "<br><br>")
        if tool:
            content = html.escape(paragraph).replace("\n", "<br>")
            blocks.append(f'<tt style="color:{muted}">{content}</tt>')
        else:
            blocks.append(inline(paragraph))
        previous_tool = tool
    body = "".join(blocks)
    if sys.platform == "win32":
        return f"<style>tt {{font-family: {mono_families()};}}</style>{body}"
    return body
