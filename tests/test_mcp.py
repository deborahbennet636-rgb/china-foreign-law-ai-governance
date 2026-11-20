"""Tests for the query layer and the MCP server.

Two kinds of test. Unit tests run the queries on the shipped dataset and
check the rules every answer must keep: verbatim text apart from the
editor's reading, a citation to the publisher's page, non-comparable issues
flagged first, inbound and outbound measures never merged. Protocol tests
start the real server as a subprocess and talk JSON-RPC to it.
"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aigov import query  # noqa: E402
from aigov.mcp_tools import BY_NAME, TOOLS, call_tool, check_arguments  # noqa: E402
from aigov.query_search import label_number, resolve_label, search, to_cn_numeral  # noqa: E402
from aigov.splitter import cn_number  # noqa: E402

DATASET = ROOT / "dist" / "aigov-db.json"


@pytest.fixture(scope="module")
def index() -> query.Index:
    return query.Index(json.loads(DATASET.read_text(encoding="utf-8")))


# ---- article labels ----

def test_chinese_numerals_round_trip_over_every_article_number_in_use() -> None:
    for number in range(1, 1300):
        assert cn_number(to_cn_numeral(number)) == number
    assert [to_cn_numeral(n) for n in (10, 12, 20, 105, 110, 1010, 1260)] == [
        "十", "十二", "二十", "一百零五", "一百一十", "一千零一十", "一千二百六十"]


@pytest.mark.parametrize(("label", "number"), [
    ("第十二条", 12), ("（十二）", 12), ("Article 50", 50), ("Sec. 2.", 2), ("SECTION 1.", 1),
    ("12", 12), ("第12条", 12), ("第七条之一", None), ("附则", None),
])
def test_label_numbers(label: str, number: Any) -> None:
    assert label_number(label) == number


def test_a_label_is_resolved_only_when_exactly_one_article_matches() -> None:
    labels = ["第一条", "第二条", "第十二条"]
    assert resolve_label(labels, "第十二条") == ("第十二条", [])
    assert resolve_label(labels, "12") == ("第十二条", [])
    assert resolve_label(labels, " 第 十二 条 ")[0] == "第十二条"
    found, near = resolve_label(labels, "99")
    assert found is None and near


# ---- what every answer must keep ----

def test_a_provision_comes_back_verbatim_with_the_publishers_page(index: query.Index) -> None:
    result = query.get_provision(index, "CN-NPC-ANTISANCTION-2021", "12")
    assert result["article"] == "第十二条" and result["resolved_from"] == "12"
    stored = next(p for p in index.instruments["CN-NPC-ANTISANCTION-2021"]["provisions"] if p["no"] == "第十二条")
    assert result["text"] == stored["text"]
    source = result["cite"]["sources"][0]
    assert source["official_url"].startswith("http") and source["sha256"] and source["snapshot_taken"]
    assert "official_url" in result["cite"]["rule"]


def test_a_reposted_source_is_flagged_in_the_citation(index: query.Index) -> None:
    reposted = next(i for i in index.data["instruments"] if i["verification"] == "PARSED" and i["provisions"])
    result = query.get_provision(index, reposted["id"], reposted["provisions"][0]["no"])
    assert "warning" in result["cite"]


def test_an_obligation_keeps_its_quote_apart_from_the_editors_reading(index: query.Index) -> None:
    result = query.find_obligations(index, extraterritorial_only=True)
    assert result["count"] == sum(1 for o in index.data["obligations"] if o.get("extraterritorial"))
    for item in result["obligations"]:
        instrument_id, label = item["provision_ref"].split("#")
        text = next(p["text"] for p in index.instruments[instrument_id]["provisions"] if p["no"] == label)
        assert "".join(item["quote"].split()) in "".join(text.split())
        assert "duty" not in item and "duty" in item["editorial"]
        assert item["editorial"]["extraterritorial"] is True


def test_a_non_comparable_issue_says_so_before_anything_else(index: query.Index) -> None:
    result = query.get_issue(index, "ISSUE-PERSONALITY-DEEPFAKE")
    assert list(result)[:2] == ["comparison", "reading_rule"]
    assert result["comparison"]["comparable"] is False and result["comparison"]["reason"]
    assert all("summary_editorial" in p and "summary" not in p for p in result["positions"])


def test_countermeasures_are_never_returned_as_one_list(index: query.Index) -> None:
    both = query.list_countermeasures(index)
    assert set(both) == {"note", "INBOUND_TO_CN", "OUTBOUND_FROM_CN"}
    assert len(both["INBOUND_TO_CN"]) + len(both["OUTBOUND_FROM_CN"]) == len(index.data["countermeasures"])
    only = query.list_countermeasures(index, direction="OUTBOUND_FROM_CN")
    assert "INBOUND_TO_CN" not in only


def test_a_measure_names_the_law_that_authorises_it(index: query.Index) -> None:
    outbound = query.list_countermeasures(index, direction="OUTBOUND_FROM_CN")["OUTBOUND_FROM_CN"]
    linked = [m for m in outbound if m.get("authorised_by")]
    assert linked and all(m["authorised_by"]["short_title"] for m in linked)


def test_search_ignores_spacing_and_reports_an_empty_result_honestly(index: query.Index) -> None:
    spaced = search(index.data, "数据 出境 安全评估", scope="provision")
    assert spaced["total"] > 0 and all(hit["kind"] == "provision" for hit in spaced["hits"])
    empty = search(index.data, "量子纠缠专利池", scope="all")
    assert empty["total"] == 0 and "不说明不存在" in empty["note"]
    with pytest.raises(ValueError):
        search(index.data, " 数 ")


def test_unknown_ids_name_what_does_exist(index: query.Index) -> None:
    with pytest.raises(query.NotFound, match="CN-NPC"):
        query.get_instrument(index, "CN-NPC-NOPE")


# ---- tool registry and argument checks ----

def test_every_tool_is_read_only_and_fully_described() -> None:
    assert len(BY_NAME) == len(TOOLS) == 10
    for tool in TOOLS:
        schema = tool.schema()
        assert schema["annotations"]["readOnlyHint"] is True
        assert schema["inputSchema"]["additionalProperties"] is False
        assert len(tool.description) > 40
        assert all(spec.get("description") for spec in tool.properties.values())
        assert set(tool.required) <= set(tool.properties)


@pytest.mark.parametrize(("name", "arguments", "fragment"), [
    ("get_provision", {"instrument_id": "CN-NPC-ANTISANCTION-2021"}, "missing required argument 'article'"),
    ("search_law", {"query": "数据", "limit": 0}, "between 1 and 100"),
    ("search_law", {"query": "数据", "limit": True}, "must be a integer"),
    ("find_obligations", {"modality": "SHOULD"}, "must be one of"),
    ("list_instruments", {"country": "CN"}, "unknown argument 'country'"),
    ("get_issue", {"issue_id": "  "}, "must not be empty"),
])
def test_bad_arguments_are_refused_with_a_reason(name: str, arguments: Dict[str, Any], fragment: str) -> None:
    assert any(fragment in problem for problem in check_arguments(BY_NAME[name], arguments))


def test_a_failed_lookup_is_a_tool_error_not_a_crash(index: query.Index) -> None:
    result, is_error = call_tool(index, "get_case", {"case_id": "NO-SUCH-CASE"})
    assert is_error and result["error"] == "not found"


def test_every_tool_answers_its_simplest_call(index: query.Index) -> None:
    simplest = {
        "describe_database": {}, "search_law": {"query": "反制"}, "list_instruments": {},
        "get_instrument": {"instrument_id": "CN-GOV-DUALUSE-2024"},
        "get_provision": {"instrument_id": "EU-AI-ACT-2024", "article": "50"},
        "find_obligations": {}, "list_issues": {}, "get_issue": {"issue_id": "ISSUE-TRAINING-COPYRIGHT"},
        "list_countermeasures": {}, "get_case": {"case_id": "CN-CASE-AI-VOICE"},
    }
    assert set(simplest) == set(BY_NAME)
    for name, arguments in simplest.items():
        result, is_error = call_tool(index, name, arguments)
        assert not is_error, (name, result)
        json.dumps(result, ensure_ascii=False)


# ---- the real server over stdio ----

def talk(lines: List[str]) -> List[Dict[str, Any]]:
    """Send raw lines to a fresh server process and parse what it answers."""
    process = subprocess.run(
        [sys.executable, "-I", str(ROOT / "tools" / "mcp_server.py")],
        input=("\n".join(lines) + "\n").encode("utf-8"), capture_output=True, timeout=60,
    )
    assert process.returncode == 0, process.stderr.decode("utf-8", "replace")
    return [json.loads(line) for line in process.stdout.decode("utf-8").splitlines()]


def rpc(message_id: Any, method: str, params: Any = None) -> str:
    message: Dict[str, Any] = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        message["params"] = params
    return json.dumps(message, ensure_ascii=False)


def test_handshake_listing_and_a_call_over_stdio() -> None:
    answers = talk([
        rpc(1, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        rpc(2, "tools/list"),
        rpc(3, "tools/call", {"name": "get_provision", "arguments": {"instrument_id": "CN-CAC-CROSSBORDER-2024", "article": "第七条"}}),
        rpc(4, "ping"),
    ])
    assert [answer["id"] for answer in answers] == [1, 2, 3, 4]
    init, listing, call, ping = (answer["result"] for answer in answers)
    assert init["protocolVersion"] == "2025-03-26" and init["capabilities"]["tools"] == {"listChanged": False}
    assert "official_url" in init["instructions"]
    assert {tool["name"] for tool in listing["tools"]} == set(BY_NAME)
    body = json.loads(call["content"][0]["text"])
    assert call["isError"] is False and body["article"] == "第七条" and "申报数据出境安全评估" in body["text"]
    assert ping == {}


def test_an_unknown_protocol_version_gets_the_latest_supported_one() -> None:
    answer = talk([rpc(1, "initialize", {"protocolVersion": "1999-01-01"})])[0]
    assert answer["result"]["protocolVersion"] == "2025-06-18"


def test_errors_keep_the_server_alive() -> None:
    answers = talk([
        "this is not json",
        rpc(1, "resources/list"),
        rpc(2, "tools/call", {"name": "delete_everything", "arguments": {}}),
        rpc(3, "tools/call", {"name": "get_issue", "arguments": {"issue_id": "NOPE"}}),
        json.dumps([json.loads(rpc(4, "ping")), {"jsonrpc": "2.0", "method": "notifications/cancelled"}]),
        rpc(5, "ping"),
    ])
    assert answers[0]["error"]["code"] == -32700
    assert answers[1]["error"]["code"] == -32601
    assert answers[2]["error"]["code"] == -32602
    assert answers[3]["result"]["isError"] is True
    assert answers[4] == [{"jsonrpc": "2.0", "id": 4, "result": {}}]
    assert answers[5]["result"] == {}
