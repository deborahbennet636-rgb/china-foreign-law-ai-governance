"""The tools the MCP server offers: names, descriptions, schemas, dispatch.

Every tool is read-only. Enumerations are taken from ``config`` so that the
server, the validator and the viewer share one vocabulary. Arguments are
checked here before any query runs, and a bad argument comes back as a
tool error the model can read and correct, not as a crash.
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from . import query
from .config import FOREIGN_RELATED, MEASURE_DIRECTIONS, MEASURE_TYPES, MODALITIES, OBLIGATION_KINDS, OBLIGATION_SUBJECTS
from .query_search import SEARCH_SCOPES, search

Record = Dict[str, Any]
Handler = Callable[[query.Index, Record], Record]

JURISDICTIONS = ["CN", "EU", "US"]


@dataclass(frozen=True)
class Tool:
    """One tool: what the model sees, and the function that answers it."""

    name: str
    description: str
    properties: Record
    required: Tuple[str, ...]
    handler: Handler

    def schema(self) -> Record:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.required),
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }


def _string(description: str) -> Record:
    return {"type": "string", "description": description}


def _enum(values: Any, description: str) -> Record:
    return {"type": "string", "enum": sorted(values), "description": description}


TOOLS: List[Tool] = [
    Tool("describe_database",
         "Scope, layers, counts, verification levels, what is not covered, and the citation rule of this "
         "database of Chinese foreign-related law and AI governance (China, EU, US). Call this first.",
         {}, (), lambda index, args: query.describe_database(index)),
    Tool("search_law",
         "Full-text search over provisions, obligations, cases, issues and countermeasures. Width and "
         "whitespace are ignored; wording is not. Returns refs and snippets, grouped by kind, unranked. "
         "Use get_provision / get_case / get_issue to read a hit in full. No hit means the database "
         "does not hold it, not that it does not exist.",
         {"query": _string("Words to find, e.g. 数据出境, 反制清单, Entity List. At least 2 characters."),
          "scope": _enum(SEARCH_SCOPES, "Which layer to search. Default all."),
          "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20,
                    "description": "Maximum hits returned. Default 20."}},
         ("query",),
         lambda index, args: search(index.data, args["query"], args.get("scope", "all"), args.get("limit", 20))),
    Tool("list_instruments",
         "List the laws, regulations and rules in the database with status, effective date, article "
         "count and verification level.",
         {"jurisdiction": _enum(JURISDICTIONS, "Only this jurisdiction."),
          "foreign_related": _enum(FOREIGN_RELATED, "Only instruments the editor tagged this way.")},
         (), lambda index, args: query.list_instruments(index, args.get("jurisdiction"), args.get("foreign_related"))),
    Tool("get_instrument",
         "One instrument: title, issuer, document number, dates (derived dates flagged), status, the "
         "labels of every article held, its obligations, and where to cite it.",
         {"instrument_id": _string("Instrument id, e.g. CN-NPC-ANTISANCTION-2021. See list_instruments.")},
         ("instrument_id",), lambda index, args: query.get_instrument(index, args["instrument_id"])),
    Tool("get_provision",
         "The verbatim text of one article, the obligations cut from it, the cases that cite it, and the "
         "publisher's page to cite. Quote the `text` field; it was matched against a snapshot.",
         {"instrument_id": _string("Instrument id, e.g. CN-CAC-CROSSBORDER-2024."),
          "article": _string("Article label as printed (第七条, （十二）, Article 50, Sec. 2.) or just "
                             "the number (7, 第7条).")},
         ("instrument_id", "article"),
         lambda index, args: query.get_provision(index, args["instrument_id"], args["article"])),
    Tool("find_obligations",
         "Obligations cut from provisions: what must, must not or may be done, by whom. `quote` is the "
         "provision's own words and is verified; everything under `editorial` is the editor's reading. "
         "All filters are optional and combine.",
         {"kind": _enum(OBLIGATION_KINDS, "Category, e.g. SECURITY_ASSESSMENT, LICENSE, PROHIBITION."),
          "modality": _enum(MODALITIES, "MUST (应当), MUST_NOT (不得), MAY (可以)…"),
          "subject": _enum(OBLIGATION_SUBJECTS, "Who bears the obligation."),
          "instrument_id": _string("Only obligations from this instrument."),
          "extraterritorial_only": {"type": "boolean", "default": False,
                                    "description": "Only obligations the editor tagged as reaching beyond China."}},
         (), lambda index, args: query.find_obligations(
             index, args.get("kind"), args.get("modality"), args.get("subject"),
             args.get("instrument_id"), args.get("extraterritorial_only", False))),
    Tool("list_issues",
         "The cross-jurisdiction issues, with whether each one's columns are comparable at all.",
         {}, (), lambda index, args: query.list_issues(index)),
    Tool("get_issue",
         "One issue: first whether its jurisdictions may be compared and why not, then each position "
         "with the nature of its material and the provisions, cases and obligations it rests on. Do not "
         "present non-comparable positions as competing answers.",
         {"issue_id": _string("Issue id, e.g. ISSUE-PERSONAL-INFO-EXPORT-PATHS. See list_issues.")},
         ("issue_id",), lambda index, args: query.get_issue(index, args["issue_id"])),
    Tool("list_countermeasures",
         "Foreign measures against Chinese parties and Chinese measures against foreign parties, always "
         "returned as two separate lists, with dates, the law authorising each, and where to cite it.",
         {"direction": _enum(MEASURE_DIRECTIONS, "Only one direction."),
          "measure_type": _enum(MEASURE_TYPES, "Only this kind of measure.")},
         (), lambda index, args: query.list_countermeasures(index, args.get("direction"), args.get("measure_type"))),
    Tool("get_case",
         "One case: court, case number, date, stage, verbatim excerpts, provisions it cites (and whether "
         "the judgment cites them or the editor linked them), and where to cite it.",
         {"case_id": _string("Case id, e.g. CN-CASE-AI-VOICE. Find ids with search_law scope=case.")},
         ("case_id",), lambda index, args: query.get_case(index, args["case_id"])),
]

BY_NAME: Dict[str, Tool] = {tool.name: tool for tool in TOOLS}

_TYPES = {"string": str, "integer": int, "boolean": bool}


def check_arguments(tool: Tool, arguments: Any) -> List[str]:
    """Return one message per problem with the arguments; empty means valid."""
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return ["arguments must be an object"]
    errors = [f"missing required argument {name!r}" for name in tool.required if name not in arguments]
    for name, value in arguments.items():
        spec = tool.properties.get(name)
        if spec is None:
            errors.append(f"unknown argument {name!r}; allowed: {sorted(tool.properties)}")
            continue
        expected = _TYPES[spec["type"]]
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            errors.append(f"{name!r} must be a {spec['type']}")
            continue
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"{name!r} must be one of {spec['enum']}")
        if "minimum" in spec and value < spec["minimum"] or "maximum" in spec and value > spec["maximum"]:
            errors.append(f"{name!r} must be between {spec.get('minimum')} and {spec.get('maximum')}")
        if expected is str and not value.strip():
            errors.append(f"{name!r} must not be empty")
    return errors


def call_tool(index: query.Index, name: str, arguments: Any) -> Tuple[Record, bool]:
    """Run one tool.

    Returns:
        The result (or an error record) and whether it is an error.

    Raises:
        KeyError: When no tool has this name; the server turns that into a
            protocol error.
    """
    tool = BY_NAME[name]
    problems = check_arguments(tool, arguments)
    if problems:
        return {"error": "invalid arguments", "problems": problems}, True
    try:
        return tool.handler(index, arguments or {}), False
    except query.NotFound as error:
        return {"error": "not found", "message": str(error)}, True
    except ValueError as error:
        return {"error": "invalid request", "message": str(error)}, True
