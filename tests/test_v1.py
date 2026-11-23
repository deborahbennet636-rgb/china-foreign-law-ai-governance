"""Tests for the v1 layers: obligations, countermeasures, foreign tagging.

The rule these tests defend is the one that makes the obligation layer worth
having at all: a quote must come from the provision it names, so that
``quote`` ⊆ ``provision.text`` ⊆ snapshot holds for every record. An
obligation that cannot show that chain does not build.
"""
import copy
import datetime
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aigov.build import build_dataset  # noqa: E402
from aigov.checks_obligation import effective_duty, quote_inside_provision  # noqa: E402
from aigov.evidence import SnapshotIndex  # noqa: E402
from aigov.store import Database, load_database  # noqa: E402
from aigov.validate import validate  # noqa: E402

TODAY = datetime.date(2026, 1, 1)

LAW_TEXT = """某某人工智能服务管理办法
某某管理部令第1号
某某管理部制定了本办法，2025年3月7日公布。
第一条 提供者应当对生成内容进行标识，不得删除、篡改标识。
第二条 提供者使用具有合法来源的数据和基础模型。
第三条 本办法自2025年9月1日起施行。"""

PROVISION_ONE = "提供者应当对生成内容进行标识，不得删除、篡改标识。"
PROVISION_TWO = "提供者使用具有合法来源的数据和基础模型。"


def make_index(manifest: Dict[str, Dict[str, Any]]) -> SnapshotIndex:
    return SnapshotIndex(manifest, loader=lambda entry: entry["text"])


def make_database() -> Database:
    """A minimal v1 database that passes every check."""
    manifest = {
        "SRC-LAW": {"id": "SRC-LAW", "official": True, "kind": "OFFICIAL_TEXT", "text": LAW_TEXT},
    }
    instrument = {
        "id": "X-LAW", "jurisdiction": "CN", "title": "某某人工智能服务管理办法", "short_title": "某某办法",
        "issuer": "某某管理部", "doc_number": "某某管理部令第1号",
        "instrument_type": "AI_SPECIFIC", "status": "IN_FORCE",
        "foreign_related": "DOMESTIC",
        "source_id": "SRC-LAW", "source_ids": ["SRC-LAW"], "complete": True, "expected_provisions": 3,
        "published_at": "2025-03-07", "effective_at": "2025-09-01", "derived_dates": {},
        "meta_evidence": {
            "issuer": "某某管理部制定了本办法",
            "published_at": "某某管理部制定了本办法，2025年3月7日公布。",
            "effective_at": "本办法自2025年9月1日起施行",
        },
        "provisions": [
            {"no": "第一条", "ordinal": 1, "division": "", "source_id": "SRC-LAW", "text": PROVISION_ONE},
            {"no": "第二条", "ordinal": 2, "division": "", "source_id": "SRC-LAW", "text": PROVISION_TWO},
            {"no": "第三条", "ordinal": 3, "division": "", "source_id": "SRC-LAW", "text": "本办法自2025年9月1日起施行。"},
        ],
    }
    obligation = {
        "id": "OBL-X-1", "instrument_id": "X-LAW", "provision": "第一条",
        "kind": "LABELING", "modality": "MUST", "subject": ["PROVIDER"],
        "quote": "提供者应当对生成内容进行标识",
        "extraterritorial": False,
    }
    return Database(manifest=manifest, instruments=[instrument], cases=[], issues=[], leads=[],
                    obligations=[obligation], countermeasures=[])


def problems(database: Database) -> List[str]:
    return validate(database, index=make_index(database.manifest), check_files=False, today=TODAY)


def rejected(database: Database, fragment: str) -> bool:
    return any(fragment in message for message in problems(database))


def with_obligation(**changes: Any) -> Database:
    """The minimal database with one field of its obligation changed."""
    database = make_database()
    database.obligations[0].update(changes)
    return database


# ---- the core invariant: quote ⊆ provision ----

def test_minimal_v1_database_is_valid() -> None:
    assert problems(make_database()) == []


def test_a_quote_cut_from_the_wrong_provision_is_rejected() -> None:
    """The obligation names 第一条 but quotes 第二条's words."""
    assert rejected(with_obligation(quote=PROVISION_TWO), "quote does not occur verbatim in X-LAW#第一条")


def test_a_paraphrase_in_the_quote_field_is_rejected() -> None:
    """A summary belongs in duty; the quote field is the provision's own words."""
    assert rejected(with_obligation(quote="平台必须给AI生成的内容打标签"), "quote does not occur verbatim")


def test_a_quote_too_short_to_prove_anything_is_rejected() -> None:
    assert rejected(with_obligation(quote="标识"), "quote is too short")


def test_a_quote_may_start_and_end_mid_sentence() -> None:
    """Cutting one clause out of a provision is the whole point of the layer."""
    assert problems(with_obligation(quote="不得删除、篡改标识")) == []


def test_whitespace_and_width_do_not_matter_but_wording_does() -> None:
    assert quote_inside_provision("提供者 应当 对生成内容进行标识", PROVISION_ONE)
    assert not quote_inside_provision("提供者可以对生成内容进行标识", PROVISION_ONE)


def test_an_obligation_cannot_name_a_provision_that_does_not_exist() -> None:
    assert rejected(with_obligation(provision="第九条"), "has no provision '第九条'")


def test_an_obligation_cannot_name_an_instrument_that_does_not_exist() -> None:
    assert rejected(with_obligation(instrument_id="NO-SUCH-LAW"), "unknown instrument")


# ---- vocabularies ----

@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("kind", "SOMETHING", "unknown obligation kind"),
        ("modality", "SHOULD", "unknown modality"),
        ("subject", [], "needs at least one subject"),
        ("subject", ["NOBODY"], "unknown subject"),
        ("extraterritorial", True, "extraterritorial_basis is empty"),
    ],
)
def test_obligation_vocabularies_are_enforced(field: str, value: Any, expected: str) -> None:
    assert rejected(with_obligation(**{field: value}), expected)


def test_a_paraphrase_long_enough_to_be_a_second_provision_is_rejected() -> None:
    assert rejected(with_obligation(duty="长" * 301), "longer than 300 characters")


def test_an_empty_paraphrase_is_rejected_but_an_absent_one_is_fine() -> None:
    assert problems(with_obligation(duty="提供者对生成内容进行标识")) == []
    assert rejected(with_obligation(duty=""), "duty is given but empty")


# ---- what the reader is shown ----

def test_the_quote_stands_as_the_duty_when_no_paraphrase_is_written() -> None:
    record = make_database().obligations[0]
    assert effective_duty(record) == record["quote"]
    assert effective_duty({**record, "duty": "给生成内容打标识"}) == "给生成内容打标识"


def test_an_obligation_inherits_the_level_of_its_instrument() -> None:
    database = make_database()
    dataset = build_dataset(database, index=make_index(database.manifest), built_at="2026-01-01")
    assert dataset["schema"] == "aigov-db/v1"
    assert dataset["obligations"][0]["verification"] == "VERIFIED"
    assert dataset["obligations"][0]["duty_text"] == "提供者应当对生成内容进行标识"
    assert dataset["stats"]["obligations"] == 1
    assert dataset["stats"]["obligations_by_kind"] == {"LABELING": 1}
    assert dataset["stats"]["obligations_by_modality"] == {"MUST": 1}


def test_an_obligation_on_an_unverified_instrument_is_not_shown_as_verified() -> None:
    database = make_database()
    database.manifest["SRC-LAW"]["official"] = False
    dataset = build_dataset(database, index=make_index(database.manifest), built_at="2026-01-01")
    assert dataset["obligations"][0]["verification"] == "PARSED"


# ---- countermeasures ----

MEASURE_TEXT = """Bureau of Industry and Security
Additions to the Entity List
Published March 14, 2026
This rule is effective March 14, 2026.
"""


def make_measure(**changes: Any) -> Database:
    database = make_database()
    database.manifest["SRC-MEASURE"] = {
        "id": "SRC-MEASURE", "official": True, "kind": "OFFICIAL_TEXT", "text": MEASURE_TEXT,
    }
    record = {
        "id": "CM-US-1", "direction": "INBOUND_TO_CN", "jurisdiction": "US",
        "issuer": "Bureau of Industry and Security", "title": "Additions to the Entity List",
        "target": "中国实体", "measure_type": "ENTITY_LIST", "status": "IN_FORCE",
        "effective_at": "2026-03-14",
        "source_id": "SRC-MEASURE", "source_ids": ["SRC-MEASURE"],
        "meta_evidence": {"effective_at": "This rule is effective March 14, 2026."},
    }
    record.update(changes)
    database.countermeasures.append(record)
    return database


def test_a_countermeasure_needs_its_title_and_date_in_a_snapshot() -> None:
    assert problems(make_measure()) == []
    assert rejected(make_measure(title="A Measure That Was Never Published"), "title does not occur")
    assert rejected(make_measure(effective_at="2026-04-01"), "not stated in meta_evidence")


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("direction", "SIDEWAYS", "unknown direction"),
        ("measure_type", "VIBES", "unknown measure_type"),
        ("status", "MAYBE", "unknown status"),
        ("target", "", "needs a target"),
        ("instrument_id", "NO-SUCH-LAW", "unknown instrument"),
    ],
)
def test_countermeasure_vocabularies_are_enforced(field: str, value: Any, expected: str) -> None:
    assert rejected(make_measure(**{field: value}), expected)


def test_inbound_and_outbound_measures_are_counted_apart() -> None:
    database = make_measure()
    dataset = build_dataset(database, index=make_index(database.manifest), built_at="2026-01-01")
    assert dataset["stats"]["countermeasures"] == 1
    assert dataset["stats"]["countermeasures_by_direction"] == {"INBOUND_TO_CN": 1}


def test_ids_are_unique_across_every_layer() -> None:
    database = make_measure(id="X-LAW")
    assert rejected(database, "id is used more than once")


# ---- measures that take effect the day they are published ----

NOTICE_TEXT = """某某工作机制公告
2025-10-09 16:00
本公告自公布之日起实施
"""


def make_notice(**changes: Any) -> Database:
    """A notice that names no date of its own, only the rule."""
    database = make_database()
    database.manifest["SRC-NOTICE"] = {
        "id": "SRC-NOTICE", "official": True, "kind": "OFFICIAL_TEXT", "text": NOTICE_TEXT,
    }
    record = {
        "id": "CM-CN-1", "direction": "OUTBOUND_FROM_CN", "jurisdiction": "CN",
        "issuer": "某某工作机制", "title": "某某工作机制公告",
        "target": "某某公司", "measure_type": "ENTITY_LIST", "status": "IN_FORCE",
        "announced_at": "2025-10-09", "effective_at": "2025-10-09",
        "effective_on_publication": True,
        "source_id": "SRC-NOTICE", "source_ids": ["SRC-NOTICE"],
        "meta_evidence": {"announced_at": "2025-10-09 16:00", "effective_at": "本公告自公布之日起实施"},
    }
    record.update(changes)
    database.countermeasures.append(record)
    return database


def test_a_notice_that_takes_effect_on_publication_is_valid() -> None:
    assert problems(make_notice()) == []


def test_the_clause_must_actually_say_it_takes_effect_on_publication() -> None:
    """A record cannot claim the rule without quoting a clause that states it."""
    assert rejected(
        make_notice(meta_evidence={"announced_at": "2025-10-09 16:00", "effective_at": "某某工作机制公告"}),
        "does not say so",
    )


def test_effective_on_publication_pins_the_date_to_the_announcement() -> None:
    assert rejected(make_notice(effective_at="2025-10-10"), "must equal announced_at")


def test_an_iso_date_in_the_source_counts_as_stating_the_date() -> None:
    """Publishing systems stamp pages as 2025-10-09 16:00; that is the date."""
    database = make_notice(
        effective_on_publication=False,
        announced_at="2025-10-09",
        effective_at="2025-10-09",
        meta_evidence={"announced_at": "2025-10-09 16:00", "effective_at": "2025-10-09 16:00"},
    )
    assert problems(database) == []


# ---- shipped data ----

def shipped(kind: str, record_id: str, change: Callable[[Dict[str, Any]], Any]) -> List[str]:
    """Apply one change to a shipped record and validate the result."""
    database = load_database()
    records = copy.deepcopy(getattr(database, kind))
    change(next(item for item in records if item["id"] == record_id))
    changed = Database(
        manifest=database.manifest,
        instruments=records if kind == "instruments" else database.instruments,
        cases=records if kind == "cases" else database.cases,
        issues=records if kind == "issues" else database.issues,
        leads=database.leads,
        obligations=records if kind == "obligations" else database.obligations,
        countermeasures=database.countermeasures,
    )
    return validate(changed, check_files=False)


def test_shipped_obligations_quote_their_own_provision() -> None:
    """Every obligation in the shipped database passes the chain check."""
    database = load_database()
    assert database.obligations, "the v1 layer should not ship empty"
    assert validate(database) == []


def test_a_shipped_obligation_pointed_at_the_wrong_article_is_caught() -> None:
    database = load_database()
    record = database.obligations[0]
    others = [
        provision["no"]
        for instrument in database.instruments
        if instrument["id"] == record["instrument_id"]
        for provision in instrument["provisions"]
        if provision["no"] != record["provision"]
    ]
    if not others:
        pytest.skip("first shipped obligation sits on a single-article instrument")
    assert shipped("obligations", record["id"], lambda r: r.update(provision=others[0]))


def test_us_code_splitter_keeps_the_catchline_apart_and_drops_nothing() -> None:
    from aigov.splitter import get_splitter
    lines = ["§107. Limitations on exclusive rights: Fair use", "Notwithstanding the provisions of sections 106,",
             "(1) the purpose and character of the use;"]
    [section] = get_splitter("us-code")(lines)
    assert section["no"] == "§107." and section["ordinal"] == 107
    assert section["heading"] == "Limitations on exclusive rights: Fair use"
    assert section["text"] == "\n".join(lines[1:])


def test_a_section_label_matches_a_citation_of_its_subsection_but_not_a_longer_number() -> None:
    from aigov.evidence import states_token
    token = "§107.".rstrip(".")
    assert states_token("17 U.S.C. § 107(1).", token)
    assert states_token("17 U.S.C. §§ 107(a); 201(a)", token)
    assert not states_token("17 U.S.C. § 1070", token)


def test_a_label_without_its_full_stop_does_not_match_a_decimal_sub_number() -> None:
    # Review regression: stripping "." from "§201." let "§ 201.4" pass as §201.
    from aigov.evidence import states_token
    assert not states_token("37 C.F.R. § 201.4", "§201")
    assert not states_token("Sec. 4.1 applies", "Sec. 4")
    assert states_token("17 U.S.C. § 201(a).", "§201")
    assert states_token("as Sec. 4. provides", "Sec. 4")


def test_an_issue_position_lists_only_obligations_of_its_own_jurisdiction() -> None:
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parent.parent / "dist" / "aigov-db.json").read_text(encoding="utf-8"))
    jurisdiction = {item["id"]: item["jurisdiction"] for item in data["instruments"]}
    owner = {item["id"]: jurisdiction[item["instrument_id"]] for item in data["obligations"]}
    for issue in data["issues"]:
        for position in issue["positions"]:
            for obligation_id in position.get("obligations", []):
                assert owner[obligation_id] == position["jurisdiction"], (issue["id"], obligation_id)


def test_latin_case_number_pattern_accepts_us_de_it_and_rejects_bare_numbers() -> None:
    from aigov.checks_case import LATIN_CASE_NUMBER
    for good in ("No. 23-5233", "No. C 24-05417 WHA", "No. 310 O 227/23", "Az.: 5 U 104/24", "n. 33 del 30 gennaio 2025"):
        assert LATIN_CASE_NUMBER.fullmatch(good), good
    for bad in ("", "23-52", "No.", "No. abc", "Az. ", "n. without-digits"):
        assert not LATIN_CASE_NUMBER.fullmatch(bad), bad


def test_gdpr_and_dsm_full_texts_obligations_and_eu_case_anchors_are_wired() -> None:
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parent.parent / "dist" / "aigov-db.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in data["instruments"]}
    assert len(by_id["EU-GDPR-2016"]["provisions"]) == 99
    assert len(by_id["EU-DSM-2019"]["provisions"]) == 32
    assert by_id["EU-GDPR-2016"]["verification"] == "VERIFIED"
    assert by_id["EU-DSM-2019"]["verification"] == "VERIFIED"

    obl_ids = {o["id"] for o in data["obligations"]}
    for expected in ("OBL-GDPR-06", "OBL-GDPR-27", "OBL-GDPR-44", "OBL-GDPR-46", "OBL-DSM-03", "OBL-DSM-04"):
        assert expected in obl_ids

    cases = {c["id"]: c for c in data["cases"]}
    assert any(a["provision"] == "EU-DSM-2019#Article 3" for a in cases["EU-CASE-KNESCHKE-V-LAION"]["legal_anchors"])
    assert any(a["provision"] == "EU-GDPR-2016#Article 27" for a in cases["EU-CASE-GPDP-DEEPSEEK-2025"]["legal_anchors"])
    assert any(a["provision"] == "EU-GDPR-2016#Article 33" for a in cases["EU-CASE-GPDP-OPENAI-2024"]["legal_anchors"])
    assert any(a["provision"] == "EU-GDPR-2016#Article 25" for a in cases["EU-CASE-GPDP-REPLIKA-2025"]["legal_anchors"])

    issues = {i["id"]: i for i in data["issues"]}
    eu_export = next(p for p in issues["ISSUE-PERSONAL-INFO-EXPORT-PATHS"]["positions"] if p["jurisdiction"] == "EU")
    assert eu_export["nature"] == "NORMATIVE"
    assert "EU-GDPR-2016#Article 46" in eu_export["provisions"]
    assert "OBL-GDPR-46" in eu_export["obligations"]


def test_eu_article_plain_splitter_and_dd_mm_yyyy_date_rendering() -> None:
    from aigov.evidence import quote_states_date
    from aigov.splitter import get_splitter

    lines = [
        "Article 1",
        "First paragraph of article one.",
        "Article 2",
        "Single paragraph of article two.",
    ]
    provs = get_splitter("eu-article-plain")(lines)
    assert len(provs) == 2
    assert provs[0]["no"] == "Article 1" and provs[0]["text"] == "First paragraph of article one."
    assert provs[1]["no"] == "Article 2" and provs[1]["text"] == "Single paragraph of article two."
    assert quote_states_date("Official Journal L 309 , 29/11/1996 P. 0001 - 0006", "1996-11-29")


def test_eu_blocking_and_fdi_screening_2019_and_2026_are_verified_and_wired() -> None:
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parent.parent / "dist" / "aigov-db.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in data["instruments"]}

    for iid, count in (
        ("EU-BLOCKING-1996-2271", 12),
        ("EU-FDI-2019-452", 17),
        ("EU-FDI-2026-1386", 31),
    ):
        assert len(by_id[iid]["provisions"]) == count
        assert by_id[iid]["verification"] == "VERIFIED"
        assert by_id[iid]["foreign_related"] == "FOREIGN_SPECIFIC"

    obl_ids = {o["id"] for o in data["obligations"]}
    for expected in (
        "OBL-EUBL-02", "OBL-EUBL-04", "OBL-EUBL-05", "OBL-EUBL-09",
        "OBL-FDI19-06", "OBL-FDI19-08",
        "OBL-FDI26-03", "OBL-FDI26-04", "OBL-FDI26-05",
    ):
        assert expected in obl_ids

    issues = {i["id"]: i for i in data["issues"]}
    eu_coercion = next(p for p in issues["ISSUE-RESPONSE-TO-FOREIGN-COERCION"]["positions"] if p["jurisdiction"] == "EU")
    assert "EU-BLOCKING-1996-2271#Article 5" in eu_coercion["provisions"]
    assert "OBL-EUBL-05" in eu_coercion["obligations"]


def test_cn_fdi_security_review_manus_and_issue_are_verified() -> None:
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parent.parent / "dist" / "aigov-db.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in data["instruments"]}

    cn_fdi = by_id["CN-NDRC-FDI-REVIEW-2020"]
    assert len(cn_fdi["provisions"]) == 23
    assert cn_fdi["verification"] == "VERIFIED"
    assert cn_fdi["foreign_related"] == "FOREIGN_SPECIFIC"
    assert cn_fdi["effective_at"] == "2021-01-18"

    obl_ids = {o["id"] for o in data["obligations"]}
    for expected in (
        "OBL-CN-FDI-04",
        "OBL-CN-FDI-07",
        "OBL-CN-FDI-10",
        "OBL-CN-FDI-12",
        "OBL-CN-FDI-14",
    ):
        assert expected in obl_ids

    cms = {c["id"]: c for c in data["countermeasures"]}
    manus = cms["CM-CN-NDRC-MANUS-2026-04"]
    assert manus["direction"] == "OUTBOUND_FROM_CN"
    assert manus["measure_type"] == "INVESTMENT_SCREENING"
    assert manus["instrument_id"] == "CN-NDRC-FDI-REVIEW-2020"
    assert manus["announced_at"] == "2026-04-27"

    issues = {i["id"]: i for i in data["issues"]}
    fdi_issue = issues["ISSUE-FDI-SECURITY-SCREENING"]
    assert fdi_issue["comparison"]["comparable"] is True
    pos_by_j = {p["jurisdiction"]: p for p in fdi_issue["positions"]}
    assert pos_by_j["CN"]["nature"] == "NORMATIVE"
    assert "CN-NDRC-FDI-REVIEW-2020#第四条" in pos_by_j["CN"]["provisions"]
    assert "OBL-CN-FDI-04" in pos_by_j["CN"]["obligations"]
    assert pos_by_j["EU"]["nature"] == "NORMATIVE"
    assert "EU-FDI-2026-1386#Article 4" in pos_by_j["EU"]["provisions"]
    assert "OBL-FDI26-04" in pos_by_j["EU"]["obligations"]
    assert pos_by_j["US"]["nature"] == "NORMATIVE"
    assert "US-USC-50-4565#§4565." in pos_by_j["US"]["provisions"]
    assert "US-CFR-31-800#§ 800.401" in pos_by_j["US"]["provisions"]
    assert "OBL-US-CFIUS-401A" in pos_by_j["US"]["obligations"]


def test_us_cfr_splitter_and_gpo_month_abbreviations() -> None:
    import pytest
    from aigov.evidence import quote_states_date
    from aigov.splitter import get_splitter

    lines = [
        "Subpart A—General",
        "§ 800.101 Scope.",
        "First section body.",
        "§ 800.102 Risk-based analysis.",
        "Second section body.",
        "Subpart B—Definitions",
        "Source:",
        "85 FR 3124, Jan. 17, 2020.",
        "§ 800.201 General.",
        "Third section body.",
    ]
    provs = get_splitter("us-cfr")(lines)
    assert [p["no"] for p in provs] == ["§ 800.101", "§ 800.102", "§ 800.201"]
    assert [p["ordinal"] for p in provs] == [1, 2, 3]
    assert provs[2]["division"] == "Subpart B—Definitions"
    assert provs[2]["heading"] == "General."
    assert provs[2]["text"] == "Third section body."
    assert quote_states_date("85 FR 3124, Jan. 17, 2020, unless otherwise noted.", "2020-01-17")

    with pytest.raises(ValueError, match="non-consecutive CFR section"):
        get_splitter("us-cfr")(["Subpart A—General", "§ 800.101 Scope.", "a", "§ 800.103 Gap.", "b"])


def test_us_cfius_statute_cfr_and_obligations_are_verified() -> None:
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parent.parent / "dist" / "aigov-db.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in data["instruments"]}

    usc = by_id["US-USC-50-4565"]
    assert len(usc["provisions"]) == 1
    assert usc["verification"] == "VERIFIED"
    assert usc["foreign_related"] == "FOREIGN_SPECIFIC"

    cfr = by_id["US-CFR-31-800"]
    assert len(cfr["provisions"]) == 104
    assert cfr["complete"] is True
    assert cfr["status"] == "IN_FORCE"
    assert cfr["effective_at"] == "2020-02-13"
    assert cfr["verification"] == "VERIFIED"
    assert cfr["foreign_related"] == "FOREIGN_SPECIFIC"

    obl_ids = {o["id"] for o in data["obligations"]}
    for expected in (
        "OBL-US-CFIUS-401A",
        "OBL-US-CFIUS-401G",
        "OBL-US-CFIUS-801A",
        "OBL-US-CFIUS-801B",
        "OBL-US-CFIUS-4565D",
    ):
        assert expected in obl_ids





