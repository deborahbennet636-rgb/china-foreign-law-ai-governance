"""Tests for validation and build: a fact without evidence must not build.

Most tests here are regressions for defects found in two rounds of code
review, where a record passed validation although its snapshot did not
support it.
"""
import copy
import datetime
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aigov.build import build_dataset, embed_json, render_page  # noqa: E402
from aigov.checks_case import sources_of_case  # noqa: E402
from aigov.evidence import SnapshotIndex, assess  # noqa: E402
from aigov.store import Database, load_database  # noqa: E402
from aigov.validate import validate  # noqa: E402

TODAY = datetime.date(2026, 1, 1)
RULE = "This Measure shall enter into force on the twentieth day following that of its publication."
LAW_TEXT = f"""某某人工智能服务管理办法
某某管理部令第1号
某某管理部制定了本办法，2025年3月7日公布。
第一条 提供者应当对生成内容进行标识。
第二条 本办法自2025年9月1日起施行。
{RULE}"""
DIGEST_TEXT = """某某互联网法院发布两起涉人工智能典型案例。
案例一
甲诉乙网络侵权责任纠纷案
法院依照某某人工智能服务管理办法第一条，判决乙赔偿甲经济损失一万元。
宣判后，双方均未上诉，判决已生效。
一审：某某区人民法院（2024）某0101民初1号
案例二
丙诉丁著作权侵权纠纷案
2025年5月6日，法院判决驳回丙的全部诉讼请求。
丙不服一审判决，已提起上诉。
一审：某某区人民法院（2024）某0101民初2号
结束"""
APPEAL_TEXT = "某某市中级人民法院民事判决书 2025年8月8日，某某市中级人民法院作出二审判决，驳回上诉，维持原判。"

FINAL_SENTENCE = "宣判后，双方均未上诉，判决已生效。"
AWARD_SENTENCE = "法院依照某某人工智能服务管理办法第一条，判决乙赔偿甲经济损失一万元。"
APPEAL_SENTENCE = "2025年8月8日，某某市中级人民法院作出二审判决，驳回上诉，维持原判。"
BLOCKS = {1: {"block_start": "案例一", "block_end": "案例二"}, 2: {"block_start": "案例二", "block_end": "结束"}}


def make_index(manifest: Dict[str, Dict[str, Any]]) -> SnapshotIndex:
    """Index over in-memory snapshots: each entry carries its own text."""
    return SnapshotIndex(manifest, loader=lambda entry: entry["text"])


def make_case(number: int) -> Dict[str, Any]:
    """Case 1 (final, claimant won) or case 2 (under appeal) of the digest page."""
    first = number == 1
    result = AWARD_SENTENCE if first else "2025年5月6日，法院判决驳回丙的全部诉讼请求。"
    index_line = f"一审：某某区人民法院（2024）某0101民初{number}号"
    return {
        "id": f"X-CASE-{number}", "jurisdiction": "CN", "forum": "某某区人民法院", "forum_type": "COURT",
        "procedural_stage": "FIRST_INSTANCE",
        "outcome": "CLAIMANT_PREVAILED" if first else "RESPONDENT_PREVAILED",
        "is_final": True if first else None, "decided_at": None,
        "caption": "甲诉乙网络侵权责任纠纷案" if first else "丙诉丁著作权侵权纠纷案",
        "case_numbers": [f"（2024）某0101民初{number}号"], "ai_roles": ["OUTPUT"], "issues": ["X-ISSUE"],
        "history": [], "also_reported_in": [], "scopes": {"SRC-DIGEST": dict(BLOCKS[number])}, "scope_links": {},
        "excerpts": [{"kind": "holding", "source_id": "SRC-DIGEST", "text": result}],
        "field_evidence": {
            "forum": [{"source_id": "SRC-DIGEST", "quote": index_line}],
            "procedural_stage": [{"source_id": "SRC-DIGEST", "quote": index_line}],
            "case_numbers": [{"source_id": "SRC-DIGEST", "quote": index_line}],
            "outcome": [{"source_id": "SRC-DIGEST", "quote": result}],
            **({"is_final": [{"source_id": "SRC-DIGEST", "quote": FINAL_SENTENCE}]} if first else {}),
        },
        "legal_anchors": [{"provision": "X-LAW#第一条", "basis": "EDITORIAL", "note": "主题对应。"}],
    }


def make_database() -> Database:
    """A minimal database that passes every check."""
    manifest = {
        "SRC-LAW": {"id": "SRC-LAW", "official": True, "kind": "OFFICIAL_TEXT", "text": LAW_TEXT},
        "SRC-DIGEST": {"id": "SRC-DIGEST", "official": True, "kind": "OFFICIAL_DIGEST", "text": DIGEST_TEXT},
        "SRC-APPEAL": {"id": "SRC-APPEAL", "official": False, "kind": "JUDGMENT", "text": APPEAL_TEXT},
    }
    instrument = {
        "id": "X-LAW", "jurisdiction": "CN", "title": "某某人工智能服务管理办法", "short_title": "某某办法",
        "issuer": "某某管理部", "doc_number": "某某管理部令第1号",
        "instrument_type": "AI_SPECIFIC", "status": "IN_FORCE",
        "source_id": "SRC-LAW", "source_ids": ["SRC-LAW"], "complete": True, "expected_provisions": 2,
        "published_at": "2025-03-07", "effective_at": "2025-09-01", "derived_dates": {},
        "meta_evidence": {
            "issuer": "某某管理部制定了本办法",
            "published_at": "某某管理部制定了本办法，2025年3月7日公布。",
            "effective_at": "本办法自2025年9月1日起施行",
            "rule": RULE,
        },
        "provisions": [
            {"no": "第一条", "ordinal": 1, "division": "", "source_id": "SRC-LAW", "text": "提供者应当对生成内容进行标识。"},
            {"no": "第二条", "ordinal": 2, "division": "", "source_id": "SRC-LAW", "text": "本办法自2025年9月1日起施行。"},
        ],
    }
    issue = {
        "id": "X-ISSUE", "title": "标识",
        "positions": [{"jurisdiction": "CN", "summary": "有规定。", "provisions": ["X-LAW#第一条"], "cases": ["X-CASE-1", "X-CASE-2"]}],
    }
    lead = {"id": "X-LEAD", "status": "OPEN", "title": "某案", "claim": "据称。", "seen_in": ["某文"], "next_step": "取原文。"}
    return Database(manifest=manifest, instruments=[instrument], cases=[make_case(1), make_case(2)], issues=[issue], leads=[lead])


def problems(database: Database) -> List[str]:
    return validate(database, index=make_index(database.manifest), check_files=False, today=TODAY)


def rejected(database: Database, fragment: str) -> bool:
    return any(fragment in message for message in problems(database))


def test_minimal_database_is_valid() -> None:
    assert problems(make_database()) == []


# ---- cases: evidence must come from the case's own block ----

def test_a_sentence_from_the_neighbouring_case_cannot_vouch_for_this_one() -> None:
    """Round 1, critical: finality of case 2 was 'proved' by case 1's sentence."""
    database = make_database()
    case = database.cases[1]
    case["is_final"] = True
    case["field_evidence"]["is_final"] = [{"source_id": "SRC-DIGEST", "quote": FINAL_SENTENCE}]
    assert rejected(database, "X-CASE-2: evidence for is_final: quote not found in the case's own block")


def test_a_case_cannot_be_pointed_at_its_neighbours_block() -> None:
    """Round 2, critical: the spec could aim a case's scope at another case."""
    database = make_database()
    case = database.cases[1]
    case["scopes"]["SRC-DIGEST"] = dict(BLOCKS[1])
    assert rejected(database, "X-CASE-2: caption does not occur verbatim in any of the case's blocks")
    assert rejected(database, "tied to the case neither by caption")


def test_a_multi_case_page_cannot_be_used_without_a_block() -> None:
    """Round 2, critical: a null scope let any sentence on the page count."""
    database = make_database()
    database.cases[1]["scopes"]["SRC-DIGEST"] = None
    assert rejected(database, "X-CASE-2: SRC-DIGEST holds more than one case and needs a block")


def test_a_judgment_saved_from_a_database_page_needs_a_block() -> None:
    """Review finding: the page's case-history panel vouched for another instance's date."""
    database = make_database()
    case = database.cases[0]
    database.manifest["SRC-PAGE"] = {
        "kind": "JUDGMENT", "official": False, "has_page_metadata": True,
        "text": "案件历程\n一审判决 2025.03.04\n二审裁定 2025.09.09\n正文\n某某区人民法院\n（2024）某0101民初1号\n判决如下\n审判人员",
    }
    case["scopes"]["SRC-PAGE"] = None
    assert rejected(database, "X-CASE-1: SRC-PAGE is a database page with panels of its own and needs a block")
    case["scopes"]["SRC-PAGE"] = {"block_start": "正文", "block_end": "审判人员"}
    assert problems(database) == []
    case["excerpts"].append({"kind": "holding", "source_id": "SRC-PAGE", "text": "二审裁定 2025.09.09"})
    assert rejected(database, "X-CASE-1: excerpt: quote not found in the case's own block")


def test_excerpt_from_another_block_is_rejected() -> None:
    database = make_database()
    database.cases[1]["excerpts"][0]["text"] = AWARD_SENTENCE
    assert rejected(database, "X-CASE-2: excerpt: quote not found in the case's own block")


def test_page_level_evidence_is_for_the_court_and_only_on_a_single_court_page() -> None:
    database = make_database()
    case = database.cases[1]
    intro = {"source_id": "SRC-DIGEST", "page_level": True, "quote": "某某互联网法院发布两起涉人工智能典型案例。"}
    case["forum"] = "某某互联网法院"
    case["field_evidence"]["forum"] = [intro]
    assert rejected(database, "needs SRC-DIGEST to be registered as holding only this court's cases")
    database.manifest["SRC-DIGEST"]["all_cases_by"] = "某某互联网法院"
    assert problems(database) == []
    case["field_evidence"]["outcome"] = [dict(intro)]
    assert rejected(database, "page-level evidence is allowed only for the court's name")


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("case_numbers", ["（2024）某0101民初9号"], "is malformed or not stated in its evidence"),
        ("case_numbers", ["（2024）某0101民初"], "is malformed or not stated in its evidence"),
        ("case_numbers", ["某0101民初1号"], "is malformed or not stated in its evidence"),
        ("case_numbers", [""], "is malformed or not stated in its evidence"),
        ("decided_at", "2025-01-01", "decided_at=2025-01-01"),
        ("decided_at", "not-a-date", "decided_at=not-a-date"),
        ("forum", "别的某某人民法院", "is not named in full in its evidence"),
        ("forum", "法院", "is not named in full in its evidence"),
        ("caption", "戊诉己合同纠纷一案的全称", "caption does not occur verbatim"),
        ("procedural_stage", "APPEAL", "procedural_stage APPEAL is not shown by its evidence"),
        ("issues", ["NO-SUCH-ISSUE"], "unknown issue"),
        ("outcome", "WON", "unknown outcome"),
    ],
)
def test_case_fields_need_their_own_evidence(field: str, value: Any, expected: str) -> None:
    database = make_database()
    database.cases[0][field] = value
    assert rejected(database, expected)


def test_too_short_a_quote_is_not_evidence() -> None:
    database = make_database()
    database.cases[0]["field_evidence"]["is_final"] = [{"source_id": "SRC-DIGEST", "quote": "已生效"}]
    assert rejected(database, "quote is too short to prove anything")


def test_finality_cannot_be_asserted_without_a_quote() -> None:
    database = make_database()
    del database.cases[0]["field_evidence"]["is_final"]
    assert rejected(database, "is_final is set")
    database.cases[0]["is_final"] = None
    assert problems(database) == []


def test_fabricated_source_title_is_rejected() -> None:
    database = make_database()
    database.cases[0]["source_title"] = {"source_id": "SRC-DIGEST", "text": "法院认定平台承担全部责任的典型案例"}
    assert rejected(database, "X-CASE-1: source_title")


def with_appeal(database: Database) -> Dict[str, Any]:
    """Turn case 1 into an appeal case that rests on a reposted judgment."""
    case = database.cases[0]
    quote = {"source_id": "SRC-APPEAL", "quote": APPEAL_SENTENCE}
    case["history"] = [{"stage": "APPEAL", "forum": "某某市中级人民法院", "decided_at": "2025-08-08", "result": dict(quote)}]
    case.update(forum="某某市中级人民法院", decided_at="2025-08-08", procedural_stage="APPEAL")
    for field in ("forum", "decided_at", "procedural_stage"):
        case["field_evidence"][field] = [dict(quote)]
    case["scopes"]["SRC-APPEAL"] = None
    case["scope_links"] = {"SRC-APPEAL": "编者按当事人和裁判要点认定为本案二审。"}
    return case


def test_a_second_source_must_be_listed_and_tied_to_the_case() -> None:
    """Round 1, critical: a history step quoting a repost left the case VERIFIED."""
    database = make_database()
    case = with_appeal(database)
    assert problems(database) == []
    assert assess(sources_of_case(case), make_index(database.manifest)) == {"verification": "PARSED", "evidence_grade": "B"}

    case["scope_links"] = {}
    assert rejected(database, "the block of SRC-APPEAL is tied to the case neither by caption")
    del case["scopes"]["SRC-APPEAL"]
    assert rejected(database, "source 'SRC-APPEAL' is not listed in the case's scopes")


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda case: case["history"][0].update(decided_at="2025-08-09"), "history date 2025-08-09"),
        (lambda case: case["history"][0].update(forum="别的某某人民法院"), "history court"),
        (lambda case: case["history"][0].update(stage="FIRST_INSTANCE"), "history stage 'FIRST_INSTANCE' is not shown"),
        (lambda case: case.update(decided_at=None), "decided_at must equal that of the last history step"),
        (lambda case: case.update(procedural_stage="FIRST_INSTANCE"), "procedural_stage must equal that of the last history step"),
    ],
)
def test_history_steps_are_checked_and_govern_the_record(change: Callable[[Dict[str, Any]], None], expected: str) -> None:
    """Round 2: the first-instance date could stand in for the appeal's; the stage was unchecked."""
    database = make_database()
    change(with_appeal(database))
    assert rejected(database, expected)


def test_cited_anchor_must_name_the_provision_inside_the_case_block() -> None:
    """Round 1, critical: any quote from any snapshot made an anchor 'cited in source'."""
    database = make_database()
    anchor = database.cases[0]["legal_anchors"][0]
    anchor.update({"basis": "CITED_IN_SOURCE", "source_id": "SRC-DIGEST", "quote": AWARD_SENTENCE})
    assert problems(database) == []

    anchor["provision"] = "X-LAW#第二条"
    assert rejected(database, "cited anchor quote does not name 某某办法 第二条")
    anchor["provision"] = "X-LAW#第一条"
    anchor["quote"] = FINAL_SENTENCE
    assert rejected(database, "cited anchor quote does not name")
    anchor["quote"] = AWARD_SENTENCE
    database.cases[1]["legal_anchors"] = [dict(anchor)]
    assert rejected(database, "X-CASE-2: anchor citation: quote not found in the case's own block")


def test_editorial_anchor_needs_a_note_and_a_real_provision() -> None:
    database = make_database()
    anchor = database.cases[0]["legal_anchors"][0]
    anchor["note"] = ""
    assert rejected(database, "must explain itself")
    anchor["provision"] = "X-LAW#第九条"
    assert rejected(database, "unknown provision")


def test_case_must_appear_under_the_issue_it_is_tagged_with() -> None:
    database = make_database()
    database.issues[0]["positions"][0]["cases"] = ["X-CASE-2"]
    assert rejected(database, "X-CASE-1: tagged X-ISSUE but not listed")


# ---- instruments ----

def test_swapped_provision_texts_are_rejected() -> None:
    """Round 1: label and text were never checked together."""
    database = make_database()
    first, second = database.instruments[0]["provisions"]
    first["text"], second["text"] = second["text"], first["text"]
    assert rejected(database, "X-LAW 第一条: label and text do not occur together")


def test_altered_provision_text_is_rejected() -> None:
    database = make_database()
    database.instruments[0]["provisions"][0]["text"] = "提供者可以对生成内容进行标识。"
    assert rejected(database, "label and text do not occur together")


def test_a_provision_must_come_from_one_of_the_records_sources() -> None:
    database = make_database()
    database.instruments[0]["provisions"][0]["source_id"] = "SRC-DIGEST"
    assert rejected(database, "is not one of the record's sources")


def test_a_date_needs_its_own_quote() -> None:
    """Round 1, critical: the effective-date quote vouched for the publication date."""
    database = make_database()
    database.instruments[0]["published_at"] = "2025-09-01"
    assert rejected(database, "published_at=2025-09-01 is not stated in meta_evidence['published_at']")


def derived(database: Database, **rule: Any) -> Dict[str, Any]:
    """Make the effective date of the instrument a derived one."""
    instrument = database.instruments[0]
    instrument["derived_dates"] = {"effective_at": {"from": "published_at", "plus_days": 20, "basis": "rule", **rule}}
    instrument["effective_at"] = "2025-03-27"
    return instrument


def test_derived_date_is_recomputed() -> None:
    """Round 1, critical: listing a field as derived switched its check off."""
    database = make_database()
    instrument = derived(database)
    assert problems(database) == []
    instrument["effective_at"] = "1999-01-01"
    assert rejected(database, "effective_at=1999-01-01 is not published_at plus 20 days")


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ({"basis": "issuer"}, "does not say 'twentieth day'"),
        ({"basis": "no-such-evidence"}, "does not say 'twentieth day'"),
        ({"plus_days": 3}, "does not say 'third day'"),
        ({"plus_days": 5}, "needs a day count"),
        ({"plus_days": -20}, "needs a day count"),
        ({"from": "effective_at"}, "only effective_at may be derived"),
    ],
)
def test_derivation_rule_must_be_stated_by_the_source(rule: Dict[str, Any], expected: str) -> None:
    """Round 2, critical: any quote, any day count and any direction were accepted."""
    database = make_database()
    derived(database, **rule)
    assert rejected(database, expected)


def test_publication_date_cannot_be_derived() -> None:
    database = make_database()
    instrument = database.instruments[0]
    instrument["derived_dates"] = {"published_at": {"from": "effective_at", "plus_days": 20, "basis": "rule"}}
    assert rejected(database, "only effective_at may be derived")


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("doc_number", "某某管理部令第9号", "must occur verbatim, in full"),
        ("doc_number", "令第1号", "must occur verbatim, in full"),
        ("doc_number", "第1号", "must occur verbatim, in full"),
        ("issuer", "某某管理部、另一个部门", "issuer names not found"),
        ("issuer", "某某管理部、管理", "issuer names not found"),
        ("title", "另一部并不存在的管理办法", "title does not occur"),
        ("status", "VALID", "unknown status"),
        ("status", "AMENDED", "AMENDED, but no instrument in the database amends it"),
        ("status", "REPEALED", "status REPEALED needs meta_evidence['status']"),
        ("amended_by", ["X-LAW"], "amended_by is computed"),
        ("amends", ["X-LAW"], "does not name the document number of 'X-LAW'"),
    ],
)
def test_instrument_fields_are_checked(field: str, value: Any, expected: str) -> None:
    """Rounds 1 and 2: number, issuer, title, status and amendment links were unchecked."""
    database = make_database()
    database.instruments[0][field] = value
    assert rejected(database, expected)


def test_in_force_needs_an_effective_date_that_has_passed() -> None:
    database = make_database()
    assert validate(database, index=make_index(database.manifest), check_files=False, today=datetime.date(2025, 6, 1)) != []
    database.instruments[0]["effective_at"] = None
    assert rejected(database, "IN_FORCE needs an effective date")


def test_complete_flag_requires_unbroken_numbering() -> None:
    database = make_database()
    database.instruments[0]["provisions"].pop()
    assert rejected(database, "marked complete")


# ---- levels, build, shipped data ----

def test_verification_level_follows_the_weakest_source() -> None:
    index = make_index(make_database().manifest)
    assert assess(["SRC-LAW"], index) == {"verification": "VERIFIED", "evidence_grade": "A"}
    assert assess(["SRC-LAW", "SRC-DIGEST"], index) == {"verification": "VERIFIED", "evidence_grade": "B"}
    assert assess(["SRC-LAW", "SRC-APPEAL"], index)["verification"] == "PARSED"
    assert assess([], index)["verification"] == "PENDING"


def test_build_counts_levels_and_amendment_links() -> None:
    database = make_database()
    amending = copy.deepcopy(database.instruments[0])
    amending.update(id="X-AMENDING", amends=["X-LAW"], complete=False, provisions=[])
    database.instruments.append(amending)
    dataset = build_dataset(database, index=make_index(database.manifest), built_at="2026-01-01")
    assert dataset["stats"]["provisions"] == 2
    assert dataset["stats"]["cases_final"] == 1
    assert dataset["stats"]["cases_with_judgment"] == 0
    assert dataset["stats"]["anchors_by_basis"] == {"EDITORIAL": 2}
    assert dataset["instruments"][0]["verification"] == "VERIFIED"
    assert dataset["instruments"][0]["amended_by"] == ["X-AMENDING"]
    assert all("text" not in source for source in dataset["sources"])


def test_embedded_json_cannot_close_the_script_element() -> None:
    payload = {"quote": "</script><script>alert(1)</script>"}
    embedded = embed_json(payload)
    assert "<" not in embedded
    assert json.loads(embedded) == payload


def test_page_allows_only_its_own_inline_blocks() -> None:
    page = render_page({"schema": "t"})
    assert "unsafe-inline" not in page
    assert page.count("'sha256-") == 2
    assert "__" + "DATA__" not in page and "_HASH__" not in page


def test_shipped_database_is_valid() -> None:
    assert validate(load_database()) == []


def shipped_problems(kind: str, record_id: str, change: Callable[[Dict[str, Any]], Any]) -> List[str]:
    """Apply one change to a shipped record and validate the result."""
    database = load_database()
    records = copy.deepcopy(getattr(database, kind))
    change(next(item for item in records if item["id"] == record_id))
    changed = Database(
        manifest=database.manifest,
        instruments=records if kind == "instruments" else database.instruments,
        cases=records if kind == "cases" else database.cases,
        issues=database.issues, leads=database.leads,
    )
    return validate(changed, check_files=False)


def _swap_articles(record: Dict[str, Any]) -> None:
    one, two = record["provisions"][0], record["provisions"][1]
    one["text"], two["text"] = two["text"], one["text"]


def _borrow_finality(record: Dict[str, Any]) -> None:
    record["field_evidence"]["is_final"] = [
        {"source_id": "SRC-CN-BJD-BIC-AI-2025", "quote": "被告不服一审判决提起上诉，后撤回上诉，一审判决生效。"}
    ]


def _anchor_to_unrelated_article(record: Dict[str, Any]) -> None:
    record["legal_anchors"] = [{
        "provision": "CN-CIVIL-CODE#第一千一百九十七条", "basis": "CITED_IN_SOURCE",
        "source_id": "SRC-US-CADC-THALER-2025", "quote": "the Copyright Act of 1976 requires",
    }]


def _aim_at_the_voice_case(record: Dict[str, Any]) -> None:
    record["scopes"]["SRC-CN-BJD-BIC-TOP10-2025"] = {"block_start": "自然人声音权益可及于AI生成声音", "block_end": "主办法官"}


def _derive_backwards(record: Dict[str, Any]) -> None:
    record.update(effective_at="2024-07-15")
    record["derived_dates"] = {"effective_at": {"from": "published_at", "plus_days": 3, "basis": "issuer"}}


@pytest.mark.parametrize(
    ("kind", "record_id", "change", "expected"),
    [
        ("instruments", "CN-CAC-GENAI-2023", _swap_articles, "label and text"),
        ("instruments", "CN-CAC-ALGO-2022", lambda r: r.update(published_at="2022-03-01"), "published_at=2022-03-01"),
        ("instruments", "CN-CAC-GENAI-2023", lambda r: r.update(doc_number="令第99号"), "doc_number"),
        ("instruments", "CN-CAC-GENAI-2023", lambda r: r.update(doc_number="第15号"), "doc_number"),
        ("instruments", "CN-CAC-GENAI-2023", lambda r: r.update(amended_by=["CN-CAC-LABEL-2025"]), "amended_by is computed"),
        ("instruments", "CN-CAC-GENAI-2023", lambda r: r.update(amends=["CN-CAC-LABEL-2025"]), "does not name the document number"),
        ("instruments", "CN-SPC-AI-OPINION-2026", lambda r: r.update(issuer="最高人民法院、人民"), "issuer names not found"),
        ("instruments", "EU-AI-ACT-2024", _derive_backwards, "does not say 'third day'"),
        ("cases", "CN-CASE-FACE-SWAP-PERSONAL-INFO", _borrow_finality, "own block"),
        ("cases", "US-CASE-THALER-V-PERLMUTTER", _anchor_to_unrelated_article, "does not name"),
        ("cases", "US-CASE-THALER-V-PERLMUTTER", lambda r: r.update(case_numbers=["23-52"]), "malformed or not stated"),
        ("cases", "US-CASE-THALER-V-PERLMUTTER", lambda r: r.update(caption="Thaler v. United States Patent Office"), "caption does not occur"),
        ("cases", "US-CASE-THALER-V-PERLMUTTER", lambda r: r.update(procedural_stage="FIRST_INSTANCE"), "procedural_stage FIRST_INSTANCE is not shown"),
        ("cases", "CN-CASE-AI-IMAGE-AUTHORSHIP", _aim_at_the_voice_case, "tied to the case neither"),
        ("cases", "CN-CASE-AI-IMAGE-AUTHORSHIP", lambda r: r["scopes"].update({"SRC-CN-BJD-BIC-AI-2025": None}), "needs a block"),
        ("cases", "CN-CASE-RAG-SEARCH", lambda r: r.update(decided_at="2025-07-01"), "must equal that of the last history step"),
        ("cases", "CN-CASE-RAG-SEARCH", lambda r: r.update(forum="法院"), "is not named in full"),
    ],
)
def test_shipped_data_rejects_the_reviewers_reproductions(kind: str, record_id: str, change: Callable[[Dict[str, Any]], Any],
                                                          expected: str) -> None:
    """Replays, against the real records, what two review rounds got past validation."""
    assert any(expected in message for message in shipped_problems(kind, record_id, change))


def test_a_hand_edited_record_is_caught_by_regeneration() -> None:
    """Stored records must equal what their spec and snapshot produce."""
    database = load_database()
    cases = copy.deepcopy(database.cases)
    next(item for item in cases if item["id"] == "CN-CASE-RAG-SEARCH")["outcome"] = "CLAIMANT_PREVAILED"
    edited = Database(manifest=database.manifest, instruments=database.instruments, cases=cases,
                      issues=database.issues, leads=database.leads)
    assert any("CN-CASE-RAG-SEARCH: stored record differs" in message for message in validate(edited))


def test_judgment_cases_cite_the_provisions_the_judgment_names() -> None:
    """The two cases with a judgment carry the legal basis stated before the ruling."""
    cases = {item["id"]: item for item in load_database().cases}

    def cited(case_id: str) -> List[str]:
        return sorted(a["provision"] for a in cases[case_id]["legal_anchors"] if a["basis"] == "CITED_IN_SOURCE")

    assert cited("CN-CASE-AI-IMAGE-AUTHORSHIP") == sorted(
        f"CN-COPYRIGHT-LAW#{label}" for label in ("第三条", "第十条", "第十一条", "第五十三条", "第五十四条"))
    assert len(cited("CN-CASE-AI-VOICE")) == 9
    assert all(ref.startswith("CN-CIVIL-CODE#") for ref in cited("CN-CASE-AI-VOICE"))
