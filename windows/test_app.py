"""Smoke tests for the Qt client's shared settings and real stdio protocol."""
import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from windows.demo import seed
from windows.model import Language, Request, Store


class FrontendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.settings = self.root / "settings.json"

    def test_migration_and_pair_lifecycle(self):
        original = dict(project=str(self.root), document="task.md", codex="codex", claude="claude",
                        manager="codex", mode="goal", goal="目标", relayMode="app", limit=11,
                        lastRunFolder=str(self.root / "previous"), selectedPair="missing")
        self.settings.write_text(json.dumps(original), encoding="utf-8")
        store = Store(Language("zh"), settings=self.settings)
        pair = store.current
        self.assertEqual(pair.id, "")
        self.assertEqual(pair.live_base, self.root / ".session-relay" / "live")
        self.assertEqual(store.run("").folder, original["lastRunFolder"])
        config = pair.config("start", force=True)
        self.assertEqual(config, dict(command="start", pair="", project=original["project"], document="task.md",
                                      codex="codex", claude="claude", goal="目标", mode="resume", manager="codex",
                                      limit=11, force=True))
        store.add(pair)
        copy = store.current
        self.assertEqual((copy.codex, copy.claude, copy.manager, copy.mode, copy.goal), ("", "", "codex", "goal", "目标"))
        self.assertEqual((copy.project, copy.document, copy.limit, copy.relayMode),
                         (pair.project, pair.document, pair.limit, pair.relayMode))
        self.assertEqual(Store(Language("en"), settings=self.settings).current.id, copy.id)
        store.delete(copy)
        self.assertEqual(Store(Language("en"), settings=self.settings).current.id, "")
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8"))["lastRunFolder"], original["lastRunFolder"])

    def test_utf8_history_request_and_localization(self):
        store = Store(Language("en"), settings=self.settings)
        self.assertEqual(store.language("第 %lld 轮", 2), "Round 2")
        folder = self.root / "测试 project" / ".session-relay" / "run"
        folder.mkdir(parents=True)
        (folder / "state.json").write_text("{}", encoding="utf-8")
        (folder / "000-receipt.txt").write_text("任务回执", encoding="utf-8")
        events, results = [], []
        loop = QEventLoop()

        def finish(*outcome):
            results.append(outcome)
            loop.quit()

        Request(store, dict(command="history", folder=str(folder)), events.append, finish).start()
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        store.stop()
        self.assertEqual(results, [(0, "", "")])
        self.assertEqual(events[0]["kind"], "history")
        self.assertEqual(events[0]["folder"], str(folder))
        self.assertEqual(events[0]["messages"][0]["text"], "任务回执")

    def test_demo_uses_no_worker_or_settings_file(self):
        store = Store(Language("zh"), demo=True, settings=self.settings)
        seed(store)
        self.assertEqual(len(store.current.codex), 36)
        self.assertEqual(len(store.run("").chat), 6)
        store.run("").launch(store.current.config("start"))
        store.run("").set_live_pause(store.current)
        store.save()
        self.assertFalse(store.requests)
        self.assertFalse(self.settings.exists())


if __name__ == "__main__":
    unittest.main()
