"""MCP server over stdio for the foreign-related law and AI governance database.

Usage:
    python -I tools/mcp_server.py                 # reads dist/aigov-db.json
    python -I tools/mcp_server.py --db other.json

Speaks JSON-RPC 2.0, one message per line, on stdin and stdout, which is the
MCP stdio transport. It needs nothing beyond the Python standard library,
so a clone of the repository can serve its data without installing an SDK.
Opened in Claude Code, the repository's ``.mcp.json`` starts it.

Every tool is read-only. No input may stop the server: malformed bytes,
deep nesting, odd ids and unencodable strings all get an error reply and the
next message is still answered. Only protocol messages reach stdout.
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, BinaryIO, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aigov.config import PATHS  # noqa: E402
from aigov.mcp_tools import BY_NAME, TOOLS, call_tool  # noqa: E402
from aigov.query import Index  # noqa: E402

logger = logging.getLogger("aigov.mcp")

SERVER_INFO = {"name": "aigov-db", "title": "涉外法治与人工智能治理对应库", "version": "1.0.0"}
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
BATCH_VERSION = "2025-03-26"  # the only revision that allows JSON-RPC batches
INSTRUCTIONS = (
    "Read-only database of Chinese foreign-related law (outbound data, anti-sanctions, blocking, "
    "export control) and AI governance, with EU and US material. Rules for using it: "
    "(1) quote only the `text` and `quote` fields, which were matched verbatim against snapshots; "
    "fields under `editorial` are the editor's classification or paraphrase; "
    "(2) cite the publisher's page given as `official_url`, not this database; "
    "(3) when an issue says comparable=false, do not present its jurisdictions as competing answers; "
    "(4) inbound and outbound countermeasures are separate lists, never one; "
    "(5) heed any `warning`: an amended instrument's text may not be the text in force; "
    "(6) a search with no hit means the database does not hold it, not that it does not exist. "
    "Start with describe_database."
)

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND = -32700, -32600, -32601
INVALID_PARAMS, INTERNAL_ERROR = -32602, -32603

Message = Dict[str, Any]


def _error(message_id: Any, code: int, text: str) -> Message:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}


def _result(message_id: Any, result: Any) -> Message:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _valid_id(value: Any) -> bool:
    """MCP request ids are strings or integers, never null, bool or float."""
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


class Server:
    """Answers JSON-RPC messages, remembering the negotiated protocol version."""

    def __init__(self, index: Index) -> None:
        self.index = index
        self.version: Optional[str] = None

    def respond(self, message: Any) -> Any:
        """Return the reply to one line's message: a dict, a list, or None."""
        if isinstance(message, list):
            return self._batch(message)
        return self.handle(message)

    def _batch(self, messages: list) -> Any:
        if not messages:
            return _error(None, INVALID_REQUEST, "empty batch")
        if self.version != BATCH_VERSION:
            return _error(None, INVALID_REQUEST, f"batches are only supported under protocol {BATCH_VERSION}")
        replies = []
        for item in messages:
            if isinstance(item, dict) and item.get("method") == "initialize":
                replies.append(_error(item.get("id") if _valid_id(item.get("id")) else None,
                                      INVALID_REQUEST, "initialize must not be part of a batch"))
                continue
            reply = self.handle(item)
            if reply is not None:
                replies.append(reply)
        return replies or None

    def handle(self, message: Any) -> Optional[Message]:
        """Return the response to ``message``, or None for a notification."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            raw_id = message.get("id") if isinstance(message, dict) else None
            return _error(raw_id if _valid_id(raw_id) else None, INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        if "id" not in message:
            return None  # notifications, including notifications/initialized, need no answer
        message_id = message["id"]
        if not _valid_id(message_id):
            return _error(None, INVALID_REQUEST, "request id must be a string or an integer")
        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error(message_id, INVALID_PARAMS, "params must be an object")
        method = message["method"]
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
            return _error(message_id, INTERNAL_ERROR, f"internal error: {type(error).__name__}")

    def initialize(self, params: Message) -> Message:
        """Agree on a protocol version and describe the server."""
        requested = params.get("protocolVersion")
        self.version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": self.version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }

    def call(self, message_id: Any, params: Message) -> Message:
        """Run one tool and wrap its result as MCP text content."""
        name = params.get("name")
        if not isinstance(name, str) or name not in BY_NAME:
            return _error(message_id, INVALID_PARAMS, f"unknown tool {name!r}; available: {sorted(BY_NAME)}")
        result, is_error = call_tool(self.index, name, params.get("arguments"))
        text = json.dumps(result, ensure_ascii=False, indent=2)
        return _result(message_id, {"content": [{"type": "text", "text": text}], "isError": is_error})


def encode(reply: Any) -> bytes:
    """Serialise a reply as one line, falling back to ASCII escapes when needed.

    A lone surrogate echoed back from a request cannot be written as UTF-8;
    escaped, it is still valid JSON. Anything that cannot be serialised at
    all becomes an internal error, so the line is always a valid message.
    """
    try:
        return json.dumps(reply, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
    except UnicodeEncodeError:
        pass
    except (ValueError, TypeError, RecursionError):
        logger.exception("reply could not be serialised")
        reply = _error(None, INTERNAL_ERROR, "reply could not be serialised")
    try:
        return json.dumps(reply, ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"
    except (ValueError, TypeError, RecursionError):
        logger.exception("reply could not be serialised")
        return json.dumps(_error(None, INTERNAL_ERROR, "reply could not be serialised")).encode("ascii") + b"\n"


def serve(server: Server, source: BinaryIO, sink: BinaryIO) -> None:
    """Read messages from ``source`` until it closes, answering each on ``sink``."""
    for raw in source:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line.decode("utf-8-sig"), parse_constant=_reject_constant)
        except (UnicodeDecodeError, ValueError, RecursionError) as error:
            reply: Any = _error(None, PARSE_ERROR, f"parse error: {type(error).__name__}")
        else:
            reply = server.respond(message)
        if reply is not None:
            sink.write(encode(reply))
            sink.flush()


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


def main() -> int:
    """Parse arguments, load the dataset and serve until stdin closes."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=PATHS.dist / "aigov-db.json", help="built dataset to serve")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sink = sys.stdout.buffer
    sys.stdout = sys.stderr  # a stray print can no longer corrupt the protocol stream
    index = load_index(args.db)
    logger.info("serving %s (%s, built %s)", args.db.name, index.data["schema"], index.data["built_at"])
    serve(Server(index), sys.stdin.buffer, sink)
    return 0


if __name__ == "__main__":
    sys.exit(main())
