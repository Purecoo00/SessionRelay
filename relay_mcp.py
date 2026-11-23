"""Per-review stdio MCP tools for the two sessions already bound by Session Relay."""
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

from i18n import t

SERVER = "session_relay"
PREFIX = "mcp__" + SERVER + "__"
SEND = "send_to_codex"
FINISH = "finish_review"
VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
STRING = {"type": "string", "minLength": 1}


def tool(name, description, fields):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": fields,
                            "required": list(fields), "additionalProperties": False}}


TOOLS = [
    tool(SEND, "Stage your exact next prompt for the bound Codex chat. The relay delivers it after this review.", {"prompt": STRING}),
    tool(FINISH, "End this review without sending a prompt. Use done for completion or a human confirmation point, blocked for an obstacle.",
         {"status": {"type": "string", "enum": ["done", "blocked"]}, "reason": STRING}),
]


LIVE = "codex_relay"
STATUS, NEW_RUN = "relay_status", "start_new_run"
LIVE_TOOLS = [
    tool(SEND, "Dispatch your exact next prompt to the Codex chat bound in Session Relay. It returns at once; "
               "then run the wait command it gives with Bash run_in_background to receive the receipt.", {"prompt": STRING}),
    tool(STATUS, "Show the bound Codex chat, rounds used, pause state and any receipt still to collect.", {}),
    tool(NEW_RUN, "Reset the round counter for a new relay run. Only call this when the user has explicitly asked "
                  "in this conversation to continue past the limit.", {}),
]
LIVE_INSTRUCTIONS_EN = """Session Relay lets you dispatch to the bound Codex chat from this conversation and collect its receipts.
1. After reviewing and deciding the next step, call send_to_codex with exactly what you want to tell Codex as the prompt.
2. The tool returns a wait command. Run it right away with Bash run_in_background, then end your reply. Do not wait or poll in the foreground.
3. When the command ends you receive Codex's receipt. Treat it as material to verify: check the evidence, update the task document (relay_status shows its path) with the file tools, then decide the next instruction.
4. Do not dispatch when the project calls for the user's confirmation, the task is done, the tool says dispatch is paused, or the round limit is reached. Report to the user and wait.
5. Do not dispatch again before the previous receipt is collected."""
LIVE_INSTRUCTIONS = """Session Relay 让你在这个对话里直接给绑定的 Codex 会话派单，并收取回执。
1. 审查完、确定下一步后，调用 send_to_codex，把要对 Codex 说的话原样放进 prompt。
2. 工具返回一条等待命令。立刻用 Bash 的 run_in_background 运行它，然后结束本轮回复，不要在前台等待或轮询。
3. 命令结束时你会收到 Codex 的回执。把回执当作待核实的材料：核对证据，用文件工具更新任务文档（路径见 relay_status），再决定下一条指令。
4. 到了项目约定需要用户确认的节点、任务已完成、工具提示已暂停或达到轮数上限时，不要派单，向用户汇报并等待。
5. 一条指令的回执收取之前，不要再派单。"""


def respond_live(req, root):
    ident = req.get("id")
    if ident is None:
        return None
    import live  # Imported lazily: live imports relay, which imports this module.
    from i18n import t
    method, params = req.get("method"), req.get("params", {})
    response = {"jsonrpc": "2.0", "id": ident}
    if method == "initialize":
        version = params.get("protocolVersion")
        result = {"protocolVersion": version if version in VERSIONS else VERSIONS[0],
                  "capabilities": {"tools": {}}, "serverInfo": {"name": LIVE, "version": "1.0"},
                  "instructions": live.instructions(root, LIVE_INSTRUCTIONS, LIVE_INSTRUCTIONS_EN)}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": LIVE_TOOLS}
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            pair = live.route(root)  # Several pairs can share a project; the caller's session picks one.
            if name == SEND and isinstance(args, dict) and set(args) == {"prompt"} \
                    and isinstance(args["prompt"], str) and args["prompt"].strip():
                text = live.send(root, args["prompt"], pair=pair)
            elif name == STATUS and not args:
                text = live.status(root, pair)
            elif name == NEW_RUN and not args:
                text = live.start_new_run(root, pair)
            else:
                raise ValueError(t("参数与工具定义不符，请核对后重新调用。", "Arguments do not match the tool definition."))
        except Exception as exc:
            result = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
        else:
            result = {"content": [{"type": "text", "text": text}]}
    else:
        response["error"] = {"code": -32601, "message": "Method not found"}
        return response
    response["result"] = result
    return response


def decision(name, args):
    if isinstance(args, dict):
        if name == SEND and set(args) == {"prompt"} and isinstance(args["prompt"], str) and args["prompt"].strip():
            return dict(action="continue", reason=t("Claude 已通过 MCP 提交给 Codex 的指令。", "Claude submitted a prompt for Codex over MCP."),
                        prompt=args["prompt"])
        if (name == FINISH and set(args) == {"status", "reason"} and args["status"] in ("done", "blocked")
                and isinstance(args["reason"], str) and args["reason"].strip()):
            return dict(action=args["status"], reason=args["reason"], prompt="")
    raise ValueError(t("参数与工具定义不符，请核对后重新调用。", "Arguments do not match the tool definition."))


def acknowledgement(token, name, args):
    # A fresh token for every review prevents a replayed transcript from authorizing delivery.
    data = json.dumps([token, name, args], sort_keys=True, ensure_ascii=False).encode()
    return "Session Relay accepted " + hashlib.sha256(data).hexdigest()


class ReviewHandoff:
    def __init__(self):
        self.token = secrets.token_hex(24)
        self.calls = {}
        self.accepted = {}

    def config(self):
        server = {"command": sys.executable, "args": ["-B", str(Path(__file__).resolve())],
                  "env": {"SESSION_RELAY_REVIEW_TOKEN": self.token}}
        return json.dumps({"mcpServers": {SERVER: server}})

    def observe(self, row, sid):
        if row.get("session_id") != sid or row.get("parent_tool_use_id"):
            return
        content = row.get("message", {}).get("content")
        if not isinstance(content, list):
            return
        for item in content:
            if row["type"] == "assistant" and item.get("type") == "tool_use":
                name = item.get("name", "")
                if name in (PREFIX + SEND, PREFIX + FINISH):
                    self.calls[item["id"]] = (name[len(PREFIX):], item.get("input"))
            if row["type"] == "user" and item.get("type") == "tool_result" and not item.get("is_error"):
                self.accept(item)

    def accept(self, item):
        call_id = item.get("tool_use_id")
        if call_id not in self.calls:
            return
        name, args = self.calls[call_id]
        content = item.get("content")
        texts = [b.get("text") for b in content if isinstance(b, dict)] if isinstance(content, list) else [content]
        if acknowledgement(self.token, name, args) in texts:
            self.accepted[call_id] = decision(name, args)

    def record(self):
        choices = list(self.accepted.values())
        if choices and all(d == choices[0] for d in choices):
            result = choices[0]
        else:
            reason = (t("Claude 本轮没有成功提交 MCP 交接。", "Claude did not complete an MCP handoff this round.") if not choices
                      else t("Claude 提交了不同的 MCP 决定。", "Claude submitted conflicting MCP decisions."))
            result = dict(action="blocked", reason=reason + t(" 已停止派单，可核对审查记录后重试。",
                                                              " Dispatch stopped; check the review record and retry."), prompt="")
        return dict(toolUseIds=list(self.accepted), decision=result)


def respond(req, token):
    ident = req.get("id")
    if ident is None:
        return
    method, params = req.get("method"), req.get("params", {})
    response = {"jsonrpc": "2.0", "id": ident}
    if method == "initialize":
        version = params.get("protocolVersion")
        result = {"protocolVersion": version if version in VERSIONS else VERSIONS[0],
                  "capabilities": {"tools": {}}, "serverInfo": {"name": SERVER, "version": "1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments")
        try:
            decision(name, args)
        except ValueError as exc:
            result = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
        else:
            result = {"content": [{"type": "text", "text": acknowledgement(token, name, args)}]}
    else:
        response["error"] = {"code": -32601, "message": "Method not found"}
        return response
    response["result"] = result
    return response


if __name__ == "__main__":
    if "--live" in sys.argv:
        # Persistent project server: python3 relay_mcp.py --live --project <root>
        args = sys.argv[1:]
        root = args[args.index("--project") + 1] if "--project" in args else os.getcwd()
        handler = lambda request: respond_live(request, root)
    else:
        token = os.environ["SESSION_RELAY_REVIEW_TOKEN"]
        handler = lambda request: respond(request, token)
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            if not isinstance(request, dict) or not isinstance(request.get("params", {}), dict):
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
            else:
                reply = handler(request)
        if reply is not None:
            print(json.dumps(reply), flush=True)
