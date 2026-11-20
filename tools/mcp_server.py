"""MCP server over stdio for the foreign-related law and AI governance database.

Usage:
    python -I tools/mcp_server.py                 # reads dist/aigov-db.json
    python -I tools/mcp_server.py --db other.json

Speaks JSON-RPC 2.0, one message per line, on stdin and stdout, which is the
MCP stdio transport. It needs nothing beyond the Python standard library,
so a clone of the repository can serve its data without installing an SDK.
Opened in Claude Code, the repository's ``.mcp.json`` starts it.

Every tool is read-only. Logs go to stderr, never stdout: a stray line on
stdout would corrupt the protocol stream.
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aigov.config import PATHS  # noqa: E402
from aigov.mcp_tools import BY_NAME, TOOLS, call_tool  # noqa: E402
from aigov.query import Index  # noqa: E402

logger = logging.getLogger("aigov.mcp")

SERVER_INFO = {"name": "aigov-db", "title": "涉外法治与人工智能治理对应库", "version": "1.0.0"}
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Read-only database of Chinese foreign-related law (outbound data, anti-sanctions, blocking, export "
    "control) and AI governance, with EU and US material. Rules for using it: "
    "(1) quote only the `text` and `quote` fields, which were matched verbatim against official snapshots; "
    "fields under `editorial` are the editor's classification or paraphrase; "
    "(2) cite the publisher's page given as `official_url`, not this database; "
    "(3) when an issue says comparable=false, do not present its jurisdictions as competing answers; "
    "(4) inbound and outbound countermeasures are separate lists, never one; "
    "(5) a search with no hit means the database does not hold it, not that it does not exist. "
    "Start with describe_database."
)

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603

Message = Dict[str, Any]


def _error(message_id: Any, code: int, text: str) -> Message:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}


def _result(message_id: Any, result: Any) -> Message:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


class Server:
    """Answers one JSON-RPC message at a time."""

    def __init__(self, index: Index) -> None:
        self.index = index

    def handle(self, message: Any) -> Optional[Message]:
        """Return the response to ``message``, or None for a notification."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        method = message["method"]
        if "id" not in message:
            return None  # notifications, including notifications/initialized, need no answer
        message_id = message["id"]
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(message_id, INVALID_PARAMS, "params must be an object")
        try:
            if method == "initialize":
                return _result(message_id, self.initialize(params))
            if method == "ping":
                return _result(message_id, {})
            if method == "tools/list":
                return _result(message_id, {"tools": [tool.schema() for tool in TOOLS]})
            if method == "tools/call":
                return self.call(message_id, params)
            return _error(message_id, METHOD_NOT_FOUND, f"method not supported: {method}")
        except Exception as error:  # noqa: BLE001 - a bad request must never stop the server
            logger.exception("internal error while handling %s", method)
            return _error(message_id, INTERNAL_ERROR, f"internal error: {error}")

    def initialize(self, params: Message) -> Message:
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }

    def call(self, message_id: Any, params: Message) -> Message:
        name = params.get("name")
        if name not in BY_NAME:
            return _error(message_id, INVALID_PARAMS, f"unknown tool {name!r}; available: {sorted(BY_NAME)}")
        result, is_error = call_tool(self.index, name, params.get("arguments"))
        text = json.dumps(result, ensure_ascii=False, indent=2)
        return _result(message_id, {"content": [{"type": "text", "text": text}], "isError": is_error})


def load_index(path: Path) -> Index:
    """Read the built dataset.

    Raises:
        SystemExit: When the file is missing or is not a v1 dataset.
    """
    if not path.exists():
        raise SystemExit(f"dataset not found: {path}; run `python tools/build.py` first")
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if not str(dataset.get("schema", "")).startswith("aigov-db/v1"):
        raise SystemExit(f"{path} is schema {dataset.get('schema')!r}; this server reads aigov-db/v1")
    return Index(dataset)


def serve(server: Server) -> None:
    """Read messages from stdin until it closes, answering each on stdout."""
    out = sys.stdout.buffer
    for raw in sys.stdin.buffer:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            response: Any = _error(None, PARSE_ERROR, f"parse error: {error}")
        else:
            if isinstance(message, list):  # batches, allowed by the 2025-03-26 revision
                answers = [answer for answer in (server.handle(item) for item in message) if answer is not None]
                response = answers or None
            else:
                response = server.handle(message)
        if response is not None:
            out.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
            out.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=PATHS.dist / "aigov-db.json", help="built dataset to serve")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    index = load_index(args.db)
    logger.info("serving %s (%s, built %s)", args.db.name, index.data["schema"], index.data["built_at"])
    serve(Server(index))
    return 0


if __name__ == "__main__":
    sys.exit(main())
