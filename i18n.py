"""Two-language messages. Chinese is the default; the app sets SESSION_RELAY_LANG=en for English.

The live MCP server and wait command are not started by the app, so they read the language
saved in the live binding instead (see live.load).
"""
import os

LANG = "en" if os.environ.get("SESSION_RELAY_LANG", "").lower().startswith("en") else "zh"


def set_lang(value):
    global LANG
    if value:
        LANG = "en" if str(value).lower().startswith("en") else "zh"


def t(zh, en):
    return en if LANG == "en" else zh
