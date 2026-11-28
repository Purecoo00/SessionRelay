"""Protocol-level tests using disposable projects and local CLI doubles."""
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agents import Claude, Codex, cli_command, codex_threads, desktop_notes, project_sessions, resolve_claude_id
import i18n
from relay import (DIGEST, bootstrap, conversation, parse_decision, register_mcp, review_evidence, run_loop, session_locks, task_document,
                   workspace)
from relay_mcp import FINISH, PREFIX, SEND, ReviewHandoff, respond
import live
import relay_platform

HERE = Path(__file__).resolve().parent
DOC = "task.md"

DRIVER = '''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
root=pathlib.Path.cwd()
for stream in (sys.stdin, sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8")
def out(obj):
    print(json.dumps(obj), flush=True)
def reply(prompt):
    if "你是本项目的指挥者" in prompt:
        f=root/"task.md"
        if "NO_WRITE" not in prompt:
            f.write_text(f.read_text()+"\\nreview")
        if "RECEIPT-OK" in prompt:
            assert "TOOL-OUTPUT" in prompt
        plan=dict(action="done" if "FINAL-RECEIPT" in prompt else "continue",reason="reviewed",prompt="exact\\n任务  $HOME")
        return "审查说明与结论\\n<relay-decision>"+json.dumps(plan)+"</relay-decision>\\n仅给指挥者的备注"
    assert prompt=="exact\\n任务  $HOME"
    f=root/"executions"
    n=int(f.read_text())+1 if f.exists() else 1
    f.write_text(str(n))
    return "FINAL-RECEIPT" if n==2 else "RECEIPT-OK"
if sys.argv[1]=="app-server":
    sid=None
    for line in sys.stdin:
        m=json.loads(line)
        name=m["method"]; p=m.get("params",{})
        if name=="initialized":continue
        if name=="initialize": result={}
        elif name=="thread/read":
            sid=p["threadId"]; result={"thread":{"id":sid,"cwd":str(root),"status":{"type":"idle"}}}
        elif name=="thread/turns/list":
            result={"data":[{"id":"initial","status":"completed","items":[{"type":"agentMessage","text":"seed"}]}]}
        elif name=="thread/items/list":
            assert p["turnId"]=="initial"
            result={"data":[{"item":{"type":"agentMessage","text":"seed"}}]}
        elif name=="thread/resume":
            assert p["threadId"]==sid; result={}
        elif name=="thread/list":
            assert p["cwd"]==str(root)
            if os.name=="nt":
                assert set(p.get("sourceKinds", []))=={"cli","vscode","appServer","exec"}
            else:
                assert "sourceKinds" not in p
            result={"data":[{"id":"a","name":"Main","cwd":str(root),"updatedAt":5},
                            {"id":"b","name":None,"preview":"hello   world","cwd":str(root),"updatedAt":3},
                            {"id":"c","parentThreadId":"a","cwd":str(root),"updatedAt":4},
                            {"id":"d","name":"Elsewhere","cwd":"/","updatedAt":6}]}
        elif name=="turn/start":
            assert p["threadId"]==sid
            text=reply(p["input"][0]["text"]); turn="target"
            for target, value in [(sid,{"id":"cmd","type":"commandExecution","aggregatedOutput":"TOOL-OUTPUT"}),("other",{"id":"other","type":"agentMessage","text":"WRONG"}),(sid,{"id":"answer","type":"agentMessage","text":text})]:
                out({"method":"item/completed","params":{"threadId":target,"turnId":turn,"item":value}})
            out({"method":"turn/completed","params":{"threadId":sid,"turn":{"id":turn,"status":"completed"}}})
            result={"turn":{"id":turn}}
        out({"id":m["id"],"result":result})
else:
    sid=sys.argv[sys.argv.index("--resume")+1]
    text=reply(sys.stdin.read())
    if "--mcp-config" in sys.argv:
        cfg=json.loads(sys.argv[sys.argv.index("--mcp-config")+1])["mcpServers"]["session_relay"]
        plan=json.loads(text.split("<relay-decision>")[1].split("</relay-decision>")[0])
        name, args=("send_to_codex", {"prompt":plan["prompt"]}) if plan["action"]=="continue" else ("finish_review", {"status":"done", "reason":"done"})
        call={"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":name,"arguments":args}}
        ack=subprocess.run([cfg["command"],*cfg["args"]],env=dict(os.environ,**cfg["env"]),input=json.dumps(call),text=True,capture_output=True,check=True,encoding="utf-8")
        out({"type":"assistant","session_id":sid,"message":{"content":[{"type":"tool_use","id":"call1","name":"mcp__session_relay__"+name,"input":args}]}})
        out({"type":"user","session_id":sid,"message":{"content":[{"type":"tool_result","tool_use_id":"call1","content":json.loads(ack.stdout)["result"]["content"]}]}})
        text="仅给用户的审阅意见"
    out({"type":"user","message":{"content":[{"type":"tool_result","content":"TOOL-OUTPUT"}]}})
    out({"type":"assistant","message":{"content":[{"type":"text","text":text}]}})
    out({"type":"result","session_id":sid,"subtype":"success","result":text})
'''


def fake_cli(root):
    cli = root / ("fake-cli.py" if os.name == "nt" else "fake-cli")
    cli.write_text(DRIVER, encoding="utf-8")
    if os.name != "nt":
        cli.chmod(0o700)
    return cli


class RelayTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name).resolve()
        self.doc = self.root / DOC
        self.doc.write_text("# task", encoding="utf-8")
        cli = fake_cli(self.root)
        self.patch = patch("agents.executable", return_value=str(cli))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        a,b = str(uuid.uuid4()), str(uuid.uuid4())
        self.desktop = self.root / "desktop-meta"
        self.agents = {"claude":Claude(b,self.root,self.doc,self.desktop),"codex":Codex(a,self.root)}
        self.addCleanup(self.agents["codex"].close)
        self.events = []
        self.fields = []

    def run_case(self, manager):
        pair = workspace(self.root, "a", "b", manager)
        config = dict(manager=manager, mode="latest", limit=1)
        def record(kind, message, **fields):
            self.events.append(kind)
            self.fields.append(dict(fields, kind=kind))
        def run():
            run_loop(config,pair,self.doc,self.agents,self.agents["codex"].latest,lambda:False,record)
        run()
        self.assertEqual(self.events[-1], "paused")
        self.assertEqual((self.root/"executions").read_text(encoding="utf-8"),"1")
        config["mode"] = "resume"
        run()
        self.assertEqual(self.events[-1], "done")
        self.assertEqual((self.root/"executions").read_text(encoding="utf-8"),"2")
        folder = pair / (pair/"current").read_text(encoding="utf-8")
        self.assertIn("TOOL-OUTPUT",(folder/"001-receipt.txt").read_text(encoding="utf-8"))
        self.assertNotIn("WRONG",(folder/"001-receipt.txt").read_text(encoding="utf-8"))
        self.assertEqual(self.doc.read_text(encoding="utf-8").count("review"),3)
        return pair, folder

    def test_claude_manager(self): self.run_case("claude")
    def test_codex_manager(self): self.run_case("codex")

    def test_conversation_view_streams_review_and_writes_digest(self):
        pair, folder = self.run_case("claude")
        chat = conversation(folder)
        self.assertEqual([(m["round"], m["role"]) for m in chat],
                         [(0,"receipt"),(0,"review"),(0,"prompt"),(1,"receipt"),(1,"review"),(1,"prompt"),
                          (2,"receipt"),(2,"review"),(2,"decision")])
        self.assertEqual(chat[2]["text"], "exact\n任务  $HOME")
        self.assertIn("仅给用户的审阅意见", chat[1]["text"])
        self.assertIn("▸ 提交给 Codex 的指令", chat[1]["text"])
        self.assertNotIn("TOOL-OUTPUT", chat[1]["text"])
        self.assertEqual(chat[-1]["title"], "接力完成，等待你确认")
        streamed = [f for f in self.fields if f["kind"] == "stream"]
        self.assertTrue(any(f["role"] == "claude" and "审阅意见" in f["text"] for f in streamed))
        self.assertTrue(any(f["role"] == "codex" and "RECEIPT-OK" in f["text"] for f in streamed))
        turns = {f["id"] for f in self.fields if f["kind"] == "turn"}
        self.assertEqual(turns, {m["id"] for m in chat})
        latest = (pair.parent / DIGEST).read_text(encoding="utf-8")
        self.assertIn(str(folder), latest)
        self.assertIn("接力完成，等待你确认", latest)

    def desktop_meta(self, seconds_ago):
        meta = self.desktop / "org" / "account"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "local_x.json").write_text(json.dumps(dict(
            cliSessionId=self.agents["claude"].sid, title="桌面审查", sessionId="local_x",
            lastActivityAt=int((time.time() - seconds_ago) * 1000))), encoding="utf-8")

    def test_recent_desktop_use_pauses_before_resuming_claude(self):
        pair = workspace(self.root, "a", "b", "claude")
        cfg = dict(manager="claude", mode="goal", goal="g", limit=1)
        events = []
        def run():
            run_loop(cfg, pair, self.doc, self.agents, lambda:None, lambda:False,
                     lambda kind, message="", **k: events.append((kind, message)))
        self.desktop_meta(60)
        with patch.object(self.agents["claude"], "run") as review:
            run()
            review.assert_not_called()
        self.assertEqual(events[-1][0], "desktop")
        self.assertIn("桌面审查", events[-1][1])
        state = json.loads((pair/(pair/"current").read_text(encoding="utf-8")/"state.json").read_text(encoding="utf-8"))
        self.assertEqual((state["phase"], state["inflight"]), ("review", False))
        def finish(prompt, manager, handoff):
            self.doc.write_text("reviewed", encoding="utf-8")
            self.submit(handoff, FINISH, dict(status="done", reason="ok"))
            return "ok", "ok"
        cfg.update(mode="resume")
        with patch.object(self.agents["claude"], "run") as review:
            run()  # Still recent: an ordinary resume keeps waiting for the desktop window.
            review.assert_not_called()
        cfg.update(force=True)
        with patch.object(self.agents["claude"], "run", side_effect=finish) as review:
            run()
            self.assertEqual(review.call_count, 1)
        self.assertEqual(events[-1][0], "done")

    def test_old_desktop_activity_does_not_block(self):
        self.desktop_meta(3600)
        pair = workspace(self.root, "a", "b", "claude")
        def finish(prompt, manager, handoff):
            self.doc.write_text("reviewed", encoding="utf-8")
            self.submit(handoff, FINISH, dict(status="done", reason="ok"))
            return "ok", "ok"
        with patch.object(self.agents["claude"], "run", side_effect=finish) as review:
            run_loop(dict(manager="claude", mode="goal", goal="g", limit=1), pair, self.doc, self.agents,
                     lambda:None, lambda:False, lambda *a, **k: None)
            self.assertEqual(review.call_count, 1)

    def test_desktop_branch_messages_reach_the_next_review(self):
        sid = self.agents["claude"].sid
        cfg_dir = self.root / "claude-config"
        bucket = cfg_dir / "projects" / "p"
        bucket.mkdir(parents=True)
        def row(kind, entry, content, **extra):
            return json.dumps(dict(type=kind, entrypoint=entry, message=dict(content=content), **extra))
        rows = [row("user", "claude-desktop", "早先的桌面消息"),
                row("user", "sdk-cli", "你是本项目的指挥者。旧审查"),
                row("assistant", "sdk-cli", [dict(type="text", text="relay 的审查")]),
                row("user", "claude-desktop", "措辞用第二种"),
                row("assistant", "claude-desktop", [dict(type="tool_use", id="t", name="Read", input={})]),
                row("user", "claude-desktop", [dict(type="tool_result", tool_use_id="t", content="x")]),
                row("assistant", "claude-desktop", [dict(type="text", text="好的，按第二种写。")]),
                row("user", "claude-desktop", "提醒", isMeta=True)]
        (bucket / f"{sid}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(cfg_dir)}):
            self.assertEqual(desktop_notes(sid), [("措辞用第二种", "好的，按第二种写。")])
            pair = workspace(self.root, "a", "b", "claude")
            prompts = []
            def finish(prompt, manager, handoff):
                prompts.append(prompt)
                self.doc.write_text("reviewed", encoding="utf-8")
                self.submit(handoff, FINISH, dict(status="done", reason="ok"))
                return "ok", "ok"
            with patch.object(self.agents["claude"], "run", side_effect=finish):
                run_loop(dict(manager="claude", mode="goal", goal="g", limit=1), pair, self.doc, self.agents,
                         lambda:None, lambda:False, lambda *a, **k: None)
        self.assertIn("[用户] 措辞用第二种\n[你的答复] 好的，按第二种写。", prompts[0])
        self.assertNotIn("早先的桌面消息", prompts[0])

    def test_doc_not_written_does_not_dispatch(self):
        pair=workspace(self.root,"a","b","claude")
        run_loop(dict(manager="claude",mode="goal",goal="NO_WRITE",limit=1),
                 pair,self.doc,self.agents,lambda:"",lambda:False,lambda *a,**k:None)
        folder = pair/(pair/"current").read_text(encoding="utf-8")
        self.assertEqual(json.loads((folder/"state.json").read_text(encoding="utf-8"))["phase"], "blocked")
        self.assertFalse((self.root/"executions").exists())

    def test_unmarked_prose_is_reformatted_before_dispatch(self):
        pair = workspace(self.root, "a", "b", "codex")
        cfg = dict(manager="codex", mode="goal", goal="legacy format", limit=1)
        prompt = "核对 A24 的结果。\n\n```python\nprint(24)\n```"
        calls = []

        def review(request, manager):
            calls.append(request)
            if len(calls) == 1:
                self.doc.write_text("updated", encoding="utf-8")
                answer = "结果通过。接下来把核对工作交给执行者。附注仅供审查。"
            elif len(calls) == 2:
                decision = json.dumps(dict(action="continue", reason="已核对", prompt=prompt))
                answer = "我的审查意见\n<relay-decision>" + decision + "</relay-decision>\n附注"
            else:
                self.doc.write_text("finished", encoding="utf-8")
                answer = '<relay-decision>{"action":"done","reason":"完成","prompt":""}</relay-decision>'
            return answer, answer

        with patch.object(self.agents["codex"], "run", side_effect=review), \
             patch.object(self.agents["claude"], "run", return_value=("ok","ok")) as execute:
            run_loop(cfg,pair,self.doc,self.agents,lambda:"seed",lambda:False,lambda *a,**k:None)
        execute.assert_called_once_with(prompt, False)
        self.assertEqual(len(calls), 3)

    def test_discover_local_session_and_resolve_desktop_alias(self):
        cli_id, alias = str(uuid.uuid4()), "local_" + str(uuid.uuid4())
        cfg = self.root / "claude-config"
        bucket = cfg / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(self.root))
        bucket.mkdir(parents=True)
        (bucket/(cli_id + ".jsonl")).write_text(json.dumps({"cwd":str(self.root)})+"\n", encoding="utf-8")
        other = str(uuid.uuid4())
        (bucket/(other + ".jsonl")).write_text(json.dumps({"cwd":"/another/project"})+"\n", encoding="utf-8")
        meta = self.root/"desktop"/"org"/"account"
        meta.mkdir(parents=True)
        (meta/(alias+".json")).write_text(json.dumps(dict(cwd=str(self.root), cliSessionId=cli_id,
                                                         sessionId=alias, title="项目审查")), encoding="utf-8")
        with patch.dict("os.environ", {"CLAUDE_CONFIG_DIR":str(cfg)}):
            sessions = project_sessions(self.root, self.root/"desktop")
            self.assertEqual([(s["id"],s["title"]) for s in sessions], [(cli_id,"项目审查")])
            with patch("agents.project_sessions",return_value=sessions):
                self.assertEqual(resolve_claude_id(alias,self.root),cli_id)

    def test_pause_and_resume_same_external_turn(self):
        pair = workspace(self.root, "a", "b", "claude")
        cfg = dict(manager="claude", mode="latest", limit=1)
        codex = self.agents["codex"]
        waiting = {"id":"external", "status":"interrupted", "completedAt":None}
        completed = {"id":"external", "status":"completed", "completedAt":123}
        paused = []

        def run():
            run_loop(cfg,pair,self.doc,self.agents,lambda:self.fail("Used unpinned receipt"),
                     lambda:bool(paused),lambda *a,**k:None)

        with patch.object(codex,"get_turn",side_effect=[waiting,waiting]), \
             patch("agents.time.sleep",side_effect=lambda _:paused.append(True)), \
             patch.object(self.agents["claude"],"run") as review:
            run()
            review.assert_not_called()
        folder = pair / (pair/"current").read_text(encoding="utf-8")
        state = json.loads((folder/"state.json").read_text(encoding="utf-8"))
        self.assertEqual((state["phase"],state["sourceTurn"]),("await_codex","external"))
        paused.clear()
        cfg["mode"] = "resume"

        def finish(prompt, manager, handoff):
            self.assertIn("bound receipt",prompt)
            self.doc.write_text("review complete", encoding="utf-8")
            self.submit(handoff, FINISH, dict(status="done", reason="ok"))
            return "完成", "完成"

        with patch.object(codex,"get_turn",return_value=completed) as read, \
             patch.object(codex,"turn_output",return_value=("final","bound receipt")) as output, \
             patch.object(self.agents["claude"],"run",side_effect=finish) as review:
            run()
            read.assert_called_once_with("external")
            output.assert_called_once_with("external")
            self.assertEqual(review.call_count,1)

    def test_failed_and_explicitly_aborted_turns_never_return_a_receipt(self):
        codex = self.agents["codex"]
        codex.rollout = self.root / "events.jsonl"
        abort = json.dumps({"type":"event_msg","payload":{"type":"turn_aborted","turn_id":"target"}})
        codex.rollout.write_text(abort[:-1], encoding="utf-8")
        ambiguous = {"id":"target","status":"interrupted","completedAt":None}
        self.assertEqual(codex.turn_state(ambiguous),"pending")
        with codex.rollout.open("a") as f:
            f.write("}\n")
        for turn in (ambiguous, {"id":"target","status":"failed"}):
            with patch.object(codex,"get_turn",return_value=turn), patch.object(codex,"turn_output") as output:
                with self.assertRaisesRegex(RuntimeError,"失败或中断"):
                    codex.wait_for_receipt("target",lambda:False)
                output.assert_not_called()

    def test_ambiguous_plan(self):
        with self.assertRaises(ValueError):
            parse_decision('<relay-decision>{}</relay-decision> <relay-decision>{}</relay-decision>')

    def test_resume_blocked_review_reuses_receipt_without_reexecuting(self):
        cfg = dict(manager="claude", mode="latest", limit=1)
        pair = workspace(self.root, "a", "b", "claude")
        outcomes = iter(["blocked", "done"])
        def review(prompt, manager, handoff):
            action = next(outcomes)
            if action == "done":
                self.assertIn("正在恢复同一回合的审查", prompt)
                self.doc.write_text("review saved", encoding="utf-8")
            self.submit(handoff, FINISH, dict(status=action, reason="test"))
            return action, action
        with patch.object(self.agents["claude"], "run", side_effect=review), patch.object(self.agents["codex"], "run") as execute:
            for mode in ("latest", "resume"):
                cfg["mode"] = mode
                run_loop(cfg,pair,self.doc,self.agents,lambda:self.fail("unexpected replay"),
                         lambda:False,lambda *a,**k:None)
            execute.assert_not_called()
        folder = pair / (pair/"current").read_text(encoding="utf-8")
        self.assertEqual(json.loads((folder/"state.json").read_text(encoding="utf-8"))["phase"], "done")
        self.assertIn("blocked", (folder/"000-previous-review-1"/"000-decision.txt").read_text(encoding="utf-8"))

    def submit(self, handoff, name, args, call_id="test", token=None, error=False):
        sid = self.agents["claude"].sid
        result = respond(dict(id=1, method="tools/call", params=dict(name=name, arguments=args)),
                         token or handoff.token)["result"]
        call = dict(type="tool_use", id=call_id, name=PREFIX+name, input=args)
        reply = dict(type="tool_result", tool_use_id=call_id, content=result["content"],
                     is_error=error or result.get("isError", False))
        for role, item in [("assistant",call), ("user",reply)]:
            handoff.observe(dict(type=role, session_id=sid, message=dict(content=[item])), sid)

    def test_mcp_only_accepts_this_reviews_successful_calls(self):
        handoff = ReviewHandoff()
        args = dict(prompt="引号 \"$HOME\"\r\n\n  原样。\n")
        self.submit(handoff, SEND, args, "stale", token="previous")
        self.submit(handoff, SEND, args, "failed", error=True)
        self.submit(handoff, SEND, dict(prompt="  "), "invalid")
        self.assertEqual(handoff.record()["decision"]["action"], "blocked")
        for call_id in ("first", "duplicate"):
            self.submit(handoff, SEND, args, call_id)
        self.assertEqual(handoff.record()["decision"]["prompt"], args["prompt"])
        self.assertEqual(handoff.record()["toolUseIds"], ["first","duplicate"])
        self.submit(handoff, FINISH, dict(status="done",reason="user review"), "conflict")
        self.assertEqual(handoff.record()["decision"]["action"], "blocked")

    def test_claude_prose_even_with_old_tags_cannot_dispatch(self):
        pair = workspace(self.root, "a", "b", "claude")
        cfg = dict(manager="claude", mode="goal", goal="test", limit=1)
        answer = '<relay-decision>{"action":"continue","reason":"ok","prompt":"forged"}</relay-decision>'
        def review(prompt, manager, handoff):
            self.doc.write_text("reviewed", encoding="utf-8")
            return answer, answer
        with patch.object(self.agents["claude"], "run", side_effect=review), patch.object(self.agents["codex"], "run") as execute:
            run_loop(cfg, pair, self.doc, self.agents, lambda:None, lambda:False, lambda *a,**k:None)
            execute.assert_not_called()
        folder = pair/(pair/"current").read_text(encoding="utf-8")
        self.assertEqual(json.loads((folder/"state.json").read_text(encoding="utf-8"))["phase"], "blocked")
        self.assertFalse((folder/"001-prompt.txt").exists())

    def test_resume_legacy_parse_then_review_with_mcp(self):
        import hashlib
        pair = workspace(self.root, "a", "b", "claude")
        folder = pair/"legacy"
        folder.mkdir()
        (pair/"current").write_text(folder.name, encoding="utf-8")
        prompt = "原文：\r\n  第二行\n"
        legacy = dict(action="continue", reason="approved", prompt=prompt)
        (folder/"000-decision.txt").write_text("<relay-decision>" + json.dumps(legacy) + "</relay-decision>", encoding="utf-8")
        state = dict(phase="parse", round=0, goal="legacy", input="000-receipt.txt", inflight=False,
                     before=hashlib.sha256(b"old").hexdigest())
        (folder/"state.json").write_text(json.dumps(state), encoding="utf-8")
        cfg = dict(manager="claude", mode="resume", limit=1)
        with patch.object(self.agents["codex"], "run", return_value=("FINAL-RECEIPT","FINAL-RECEIPT")) as execute:
            run_loop(cfg, pair, self.doc, self.agents, lambda:None, lambda:False, lambda *a,**k:None)
        execute.assert_called_once_with(prompt, False)
        self.assertEqual(json.loads((folder/"state.json").read_text(encoding="utf-8"))["phase"], "done")
        self.assertEqual(json.loads((folder/"001-mcp.json").read_text(encoding="utf-8"))["decision"]["action"], "done")

    def test_explicit_resume_recovers_interrupted_mcp_review(self):
        pair = workspace(self.root, "a", "b", "claude")
        cfg = dict(manager="claude", mode="goal", limit=1, goal="retry")
        def run():
            run_loop(cfg, pair, self.doc, self.agents, lambda:None, lambda:False, lambda *a,**k:None)
        with patch.object(self.agents["claude"], "run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                run()
        cfg["mode"] = "resume"
        def finish(prompt, manager, handoff):
            self.doc.write_text("retry completed", encoding="utf-8")
            self.submit(handoff, FINISH, dict(status="done", reason="user review"))
            return "请审阅", "请审阅"
        with patch.object(self.agents["claude"], "run", side_effect=finish), patch.object(self.agents["codex"], "run") as execute:
            run()
            execute.assert_not_called()
        state = json.loads((pair/(pair/"current").read_text(encoding="utf-8")/"state.json").read_text(encoding="utf-8"))
        self.assertEqual((state["phase"], state["retry"]), ("done", 1))

    def test_large_receipt_pages_fit_tool_limits_and_keep_long_lines(self):
        path = self.root / "000-receipt.txt"
        content = ("数值" * 40000 + "\n") * 2 + "FINAL RESULT"
        path.write_text(content, encoding="utf-8")
        message = review_evidence(path)
        pages = sorted(path.with_suffix(".pages").glob("*.txt"))
        self.assertGreater(len(pages), 1)
        self.assertIn(str(pages[0]), message)
        self.assertIn(str(pages[-1]), message)
        self.assertIn("FINAL RESULT", message)
        self.assertTrue(all(p.stat().st_size <= 16384 for p in pages))
        self.assertEqual(path.read_text(encoding="utf-8"), content)
        view = "".join(p.read_text(encoding="utf-8") for p in pages)
        self.assertLessEqual(max(map(len, view.splitlines())), 800)
        self.assertEqual(view.replace("\n",""),content.replace("\n",""))

    def test_interrupted_delivery_is_not_replayed(self):
        pair=workspace(self.root,"a","b","claude")
        cfg=dict(manager="claude",mode="latest",limit=2)
        with patch.object(self.agents["codex"],"run",side_effect=RuntimeError("connection lost")):
            with self.assertRaisesRegex(RuntimeError,"connection lost"):
                run_loop(cfg,pair,self.doc,self.agents,lambda:"seed",lambda:False,lambda *a,**k:None)
        cfg["mode"]="resume"
        with self.assertRaisesRegex(RuntimeError,"核对两端"):
            run_loop(cfg,pair,self.doc,self.agents,lambda:"seed",lambda:False,lambda *a,**k:None)
        self.assertFalse((self.root/"executions").exists())


class LiveRelayTest(unittest.TestCase):
    """The reviewer's own session dispatches through codex_relay and collects receipts."""

    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix="Session Relay O'Brien & 测试 ")
        self.addCleanup(t.cleanup)
        self.root = Path(t.name).resolve()
        (self.root / DOC).write_text("# task", encoding="utf-8")
        cli = fake_cli(self.root)
        env = patch.dict(os.environ, {"SESSION_RELAY_CODEX_BIN": str(cli),
                                      "SESSION_RELAY_SUPPORT": str(self.root / "support"),
                                      "CLAUDE_CONFIG_DIR": str(self.root / "claude-config")})
        env.start()
        self.addCleanup(env.stop)
        support = patch("relay.SUPPORT", self.root / "support")
        support.start()
        self.addCleanup(support.stop)
        self.codex = str(uuid.uuid4())

    def server(self, **env):
        proc = subprocess.Popen([sys.executable, "-B", str(HERE / "relay_mcp.py"), "--live", "--project", str(self.root)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=dict(os.environ, **env))
        self.addCleanup(lambda: (proc.stdin.close(), proc.stdout.close(), proc.wait()))
        counter = iter(range(1, 1000))
        def call(method, **params):
            proc.stdin.write(json.dumps(dict(jsonrpc="2.0", id=next(counter), method=method, params=params)) + "\n")
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())["result"]
        return call

    def tool(self, call, name, **args):
        result = call("tools/call", name=name, arguments=args)
        return result.get("isError", False), result["content"][0]["text"]

    def wait(self, text):
        command = text.strip().splitlines()[-2]
        if os.name == "nt":
            self.assertTrue(command.startswith("MSYS2_ARG_CONV_EXCL="))
            args = [str(relay_platform.windows_git_bash()), "-c", command]
        else:
            args = shlex.split(command)
            self.assertEqual(args[0], sys.executable)
        return subprocess.run(args, capture_output=True, encoding="utf-8", timeout=60)

    def test_dispatch_wait_and_receipt_round_trip(self):
        folder = live.bind(self.root, self.codex, limit=2, document=DOC)
        call = self.server()
        init = call("initialize", protocolVersion="2025-06-18")
        self.assertIn("run_in_background", init["instructions"])
        self.assertEqual({t["name"] for t in call("tools/list")["tools"]}, {SEND, "relay_status", "start_new_run"})
        prompt = "exact\n任务  $HOME"

        error, text = self.tool(call, SEND, prompt=prompt)
        self.assertFalse(error, text)
        self.assertIn("第 1 轮指令", text)
        error, refused = self.tool(call, SEND, prompt=prompt)
        self.assertTrue(error)  # Still running, or finished but not yet collected.
        done = self.wait(text)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Codex 第 1 轮已完成", done.stdout)
        self.assertIn("RECEIPT-OK", done.stdout)
        self.assertIn(str(folder / "001-receipt.txt"), done.stdout)

        error, text = self.tool(call, SEND, prompt=prompt)
        self.assertFalse(error, text)
        done = self.wait(text)
        self.assertIn("FINAL-RECEIPT", done.stdout)
        self.assertIn("还可派出 0 轮", done.stdout)
        self.assertEqual((self.root / "executions").read_text(encoding="utf-8"), "2")

        error, text = self.tool(call, SEND, prompt=prompt)
        self.assertTrue(error)
        self.assertIn("达到上限", text)
        error, text = self.tool(call, "relay_status")
        self.assertIn("已派出 2 / 2 轮", text)
        chat = conversation(folder)
        self.assertEqual([(m["round"], m["role"]) for m in chat],
                         [(0, "prompt"), (1, "receipt"), (1, "prompt"), (2, "receipt")])
        self.assertIn("RECEIPT-OK", chat[1]["text"])

        error, text = self.tool(call, "start_new_run")
        self.assertFalse(error, text)
        (live.base(self.root) / "pause").write_text("", encoding="utf-8")
        error, text = self.tool(call, SEND, prompt=prompt)
        self.assertTrue(error)
        self.assertIn("暂停", text)

    def test_pairs_in_one_project_route_by_the_calling_session(self):
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        live.bind(self.root, self.codex, check=False, document=DOC, claude=first)
        folder = live.bind(self.root, str(uuid.uuid4()), check=False, document=DOC, pair="p-two", claude=second)
        self.assertEqual(folder.parent, live.base(self.root) / "p-two")
        with self.assertRaisesRegex(ValueError, "选定 Claude Code 会话"):
            live.bind(self.root, self.codex, check=False, document=DOC, pair="p-3")
        with self.assertRaisesRegex(ValueError, "另一个配对"):
            live.bind(self.root, self.codex, check=False, document=DOC, pair="p-3", claude=first)
        with self.assertRaises(ValueError):
            live.base(self.root, "../escape")
        self.assertEqual(live.route(self.root, {"CLAUDE_CODE_SESSION_ID": first}), "")
        self.assertEqual(live.route(self.root, {"CLAUDE_CODE_SESSION_ID": second}), "p-two")
        with self.assertRaisesRegex(ValueError, "没有绑定"):
            live.route(self.root, {"CLAUDE_CODE_SESSION_ID": str(uuid.uuid4())})

        (live.base(self.root) / "pause").write_text("", encoding="utf-8")  # Pausing the first pair leaves the second running.
        call = self.server(CLAUDE_CODE_SESSION_ID=second)
        error, text = self.tool(call, SEND, prompt="exact\n任务  $HOME")
        self.assertFalse(error, text)
        self.assertIn("--pair p-two", text)
        done = self.wait(text)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(str(folder / "001-receipt.txt"), done.stdout)
        self.assertIn("已派出 1 / 3 轮", self.tool(call, "relay_status")[1])
        error, text = self.tool(self.server(CLAUDE_CODE_SESSION_ID=first), SEND, prompt="x")
        self.assertTrue(error)
        self.assertIn("暂停", text)

    def test_codex_chats_are_listed_for_the_picker(self):
        chats = codex_threads(self.root)
        self.assertEqual([(c["id"], c["title"]) for c in chats], [("a", "Main"), ("b", "hello world")])

    @unittest.skipUnless(relay_platform.WINDOWS, "Windows discovery")
    def test_discovery_keeps_codex_chats_when_claude_is_missing(self):
        result = subprocess.run([sys.executable, str(HERE / "relay.py")],
                                input=json.dumps(dict(command="discover", project=str(self.root))),
                                env=dict(os.environ, SESSION_RELAY_CLAUDE_BIN=str(self.root / "missing.exe")),
                                capture_output=True, encoding="utf-8", check=True)
        event = json.loads(result.stdout)
        self.assertEqual(event["kind"], "discovery")
        self.assertIsNone(event["loggedIn"])
        self.assertTrue(event["claudeError"])
        self.assertEqual([chat["id"] for chat in event["codex"]], ["a", "b"])

    def test_no_round_limit(self):
        folder = live.bind(self.root, self.codex, limit=0, check=False, document=DOC)
        state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["limit"], 0)
        state["round"] = 150
        (folder / "state.json").write_text(json.dumps(state), encoding="utf-8")
        text = live.send(self.root, "go", spawn=lambda root, folder, k: 0, settle=0)
        self.assertIn("第 151 轮指令", text)
        self.assertIn("已派出 151 轮（不设上限）", live.status(self.root))
        with self.assertRaises(ValueError):
            live.bind(self.root, self.codex, limit=-1, check=False, document=DOC)

    def test_rebinding_reuses_an_unused_run(self):
        first = live.bind(self.root, self.codex, limit=3, check=False, document=DOC)
        again = live.bind(self.root, self.codex, limit=10, check=False, document=DOC)
        self.assertEqual(first, again)
        self.assertEqual(json.loads((again / "state.json").read_text(encoding="utf-8"))["limit"], 10)
        live.send(self.root, "x", spawn=lambda *a: None, settle=0)
        live.update_pending(again, status="completed", collected=True)
        third = live.bind(self.root, self.codex, limit=10, check=False, document=DOC)
        self.assertNotEqual(third, again)
        self.assertEqual(len([d for d in live.base(self.root).iterdir() if d.is_dir()]), 2)

    def test_mcp_is_registered_locally_from_this_copy(self):
        calls = []
        def run(cmd, returncode=0, **kw):
            calls.append((cmd, kw))
            return subprocess.CompletedProcess(cmd, 1 if fail and cmd[2] == "add" else 0, "", "boom")
        fail = False
        with patch("relay.executable", return_value="claude"):
            register_mcp(self.root, run=run)
            (remove, _), (add, kw) = calls
            self.assertEqual(remove, ["claude", "mcp", "remove", "-s", "local", "codex_relay"])
            self.assertEqual(add, ["claude", "mcp", "add", "-s", "local", "codex_relay", "--", sys.executable, "-B",
                                   str(HERE / "relay_mcp.py"), "--live", "--project", str(self.root)])
            self.assertEqual(kw["cwd"], self.root)  # Local scope is keyed by the project folder.
            fail = True
            with self.assertRaisesRegex(RuntimeError, "boom"):
                register_mcp(self.root, run=run)

    def test_session_lock_contends_across_processes_and_releases(self):
        command = [sys.executable, "-c",
                   "from relay import session_locks; from contextlib import ExitStack; "
                   "stack = ExitStack(); stack.enter_context(session_locks(['shared'])); stack.close()"]
        env = dict(os.environ, PYTHONIOENCODING="utf-8") if relay_platform.WINDOWS else None
        with session_locks(["shared", "shared"]):
            conflict = subprocess.run(command, cwd=HERE, env=env, capture_output=True, encoding="utf-8")
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn("Session Relay", conflict.stderr)
        released = subprocess.run(command, cwd=HERE, env=env, capture_output=True, encoding="utf-8")
        self.assertEqual(released.returncode, 0, released.stderr)

    def test_git_bash_preserves_windows_paths_with_spaces_and_apostrophes(self):
        python = r"C:\Program Files\Python\python.exe"
        root = r"D:\Projects\O'Brien & Co"
        script = r"C:\Relay UI\relay.py"
        command = relay_platform.git_bash_command(
            [python, "-B", script, "wait", "--project", root, "--pair", "p-fixture"], (0, 2, 5))
        self.assertEqual(shlex.split(command),
                         ["MSYS2_ARG_CONV_EXCL=*", "C:/Program Files/Python/python.exe", "-B",
                          "C:/Relay UI/relay.py", "wait", "--project", "D:/Projects/O'Brien & Co",
                          "--pair", "p-fixture"])

    def test_windows_permission_path_uses_claude_posix_drive_syntax(self):
        with patch("relay_platform.WINDOWS", True):
            self.assertEqual(relay_platform.claude_rule_path(r"D:\Projects\任务 文档.md"),
                             "//d/Projects/任务 文档.md")

    def test_windows_bootstrap_opens_new_powershell_console(self):
        doc = self.root / "O'Brien 任务.md"
        doc.write_text("# task", encoding="utf-8")
        with patch("relay.WINDOWS", True), patch("relay.executable", return_value=r"C:\Program Files\claude.exe"), \
             patch("relay.subprocess.CREATE_NEW_CONSOLE", 16, create=True), \
             patch("relay.subprocess.Popen") as launch, patch("relay.emit") as emit:
            bootstrap(self.root, document=str(doc))
        (command,), options = launch.call_args
        self.assertEqual(command[:3], ["powershell.exe", "-NoProfile", "-EncodedCommand"])
        script = base64.b64decode(command[3]).decode("utf-16-le")
        self.assertIn(r"& 'C:\Program Files\claude.exe' auth status", script)
        self.assertIn("--session-id", script)
        self.assertIn("O''Brien 任务.md", script)
        self.assertEqual(options["creationflags"], 16)
        self.assertEqual(options["cwd"], self.root)
        self.assertEqual(emit.call_args.args[0], "created")

    def test_windows_cmd_npm_launchers_resolve_the_published_entry(self):
        for agent, package, entry in (("claude", "@anthropic-ai/claude-code", "bin/claude.exe"),
                                      ("codex", "@openai/codex", "bin/codex.js")):
            shim = self.root / f"{agent}.cmd"
            folder = self.root / "node_modules" / package
            folder.mkdir(parents=True)
            (folder / "package.json").write_text(json.dumps({"bin": {agent: entry}}), encoding="utf-8")
            with patch("agents.WINDOWS", True), patch("agents.shutil.which", return_value="node.exe"):
                result = cli_command(agent, str(shim))
            expected = [str(folder / entry)]
            if agent == "codex":
                expected.insert(0, "node.exe")
            self.assertEqual(result, expected)

    def test_frozen_script_command_targets_worker(self):
        with patch.object(sys, "frozen", True, create=True):
            self.assertEqual(relay_platform.script_command(HERE / "relay_mcp.py", "--live"),
                             [sys.executable, "relay_mcp.py", "--live"])

    def test_task_document_can_live_anywhere(self):
        notes = self.root / "notes"
        notes.mkdir()
        (notes / "plan.md").write_text("# plan", encoding="utf-8")
        self.assertEqual(task_document(self.root, "notes/plan.md"), notes / "plan.md")
        self.assertEqual(task_document(self.root, str(notes / "plan.md")), notes / "plan.md")
        for value in ("", "missing.md"):
            with self.assertRaises(ValueError):
                task_document(self.root, value)
        live.bind(self.root, self.codex, check=False, document="notes/plan.md")
        self.assertIn(str(notes / "plan.md"), live.status(self.root))

    def test_english_binding_speaks_english(self):
        self.addCleanup(i18n.set_lang, i18n.LANG)
        i18n.set_lang("en")
        live.bind(self.root, self.codex, check=False, document=DOC)
        i18n.set_lang("zh")
        text = live.status(self.root)  # Loading the binding restores its language.
        self.assertIn("Dispatched 0 / 3 rounds", text)
        self.assertIn("Task document:", text)
        self.assertIn("relay_status shows its path", live.instructions(self.root, "zh", "relay_status shows its path"))

    def test_rejected_dispatch_reports_codex_error(self):
        live.bind(self.root, self.codex, check=False, document=DOC)
        def reject(root, folder, k):
            live.update_pending(folder, status="failed", error="Codex 正在运行另一项任务。")
        with self.assertRaisesRegex(RuntimeError, "正在运行另一项任务"):
            live.send(self.root, "x", spawn=reject, settle=1)
        with self.assertRaisesRegex(RuntimeError, "没有完成"):
            live.wait(self.root)
        chat = conversation(live.load(self.root)[1])
        self.assertEqual(chat[-1]["title"], "Codex 执行失败")

    def test_wait_notices_a_worker_that_died(self):
        live.bind(self.root, self.codex, check=False, document=DOC)
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        live.send(self.root, "x", spawn=lambda *a: dead.pid, settle=0)
        with self.assertRaisesRegex(RuntimeError, "意外退出"):
            live.wait(self.root, poll=0.1)


if __name__=="__main__":
    unittest.main()
