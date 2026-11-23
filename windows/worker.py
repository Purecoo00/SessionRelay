"""Console executable for the bundled relay and MCP entry points."""
import sys

import relay
import relay_mcp
from relay_platform import WINDOWS


def main():
    if WINDOWS and getattr(sys, "frozen", False):
        import ctypes

        # Keep Qt/Python DLLs out of the search path of external Claude and Codex executables.
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    script = sys.argv.pop(1) if len(sys.argv) > 1 else ""
    if script == "relay.py":
        relay.entrypoint()
    elif script == "relay_mcp.py":
        relay_mcp.entrypoint()
    else:
        sys.exit("Expected relay.py or relay_mcp.py.")


if __name__ == "__main__":
    main()
