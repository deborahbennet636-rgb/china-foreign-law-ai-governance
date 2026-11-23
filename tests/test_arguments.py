"""Tests for the LAMUS 6-class FIRAC sentence-level argument mining pilot."""
import copy
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aigov.argument_metrics import (
    classification_metrics,
    cohens_kappa,
    evaluate_aligned_records,
)
from aigov.build import build_dataset
from aigov.checks_argument import check_argument_record
from aigov.query import Index, get_case
from aigov.sentencer import split_sentences
from aigov.store import load_database, provision_refs
from aigov.textnorm import normalize
from aigov.validate import validate


def test_sentencer_handles_zh_en_de_legal_abbreviations_and_ordinals() -> None:
    zh = "法院认为，被告构成侵权。原告称：“已多次制止！”宣判后，双方均未上诉。"
    assert split_sentences(zh) == [
        "法院认为，被告构成侵权。",
        "原告称：“已多次制止！”",
        "宣判后，双方均未上诉。",
    ]

    de = (
        "Der 5. Zivilsenat hat heute entschieden, dass das Landgericht die Klage zu Recht abgewiesen hat. "
        "Zur Begründung führt der Senat aus, dass sich der Beklagte auf das sog. Text und Data Mining "
        "aus § 44b Abs. 3 S. 2 UrhG berufen könne."
    )
    de_sents = split_sentences(de)
    assert len(de_sents) == 2
    assert de_sents[0].startswith("Der 5. Zivilsenat")
    assert "sog. Text" in de_sents[1]
    assert "§ 44b Abs. 3 S. 2 UrhG" in de_sents[1]

    en = (
        "On the application, Dr. Thaler listed Co., Ltd. under 17 U.S.C. § 107. "
        "The Italian SA fined Luka Inc. for Articles 5.1 (a) and 25.1 of the GDPR."
    )
    en_sents = split_sentences(en)
    assert len(en_sents) == 2
    assert "Dr. Thaler" in en_sents[0]
    assert "5.1 (a)" in en_sents[1]


def test_sentencer_is_lossless_across_every_shipped_case_excerpt() -> None:
    db = load_database()
    for case in db.cases:
        for ex_idx, excerpt in enumerate(case["excerpts"]):
            sents = split_sentences(excerpt["text"])
            assert sents, f"{case['id']} excerpt {ex_idx} produced no sentences"
            assert normalize("".join(sents)) == normalize(excerpt["text"]), (case["id"], ex_idx)


def test_shipped_arguments_cover_all_17_cases_and_pass_validation() -> None:
    db = load_database()
    assert len(db.arguments) == len(db.cases) == 17
    assert sum(len(a["sentences"]) for a in db.arguments) == 228
    assert validate(db) == []


def test_argument_validator_catches_tampered_text_dropped_sentence_and_bad_vocab() -> None:
    db = load_database()
    cases_by_id = {c["id"]: c for c in db.cases}
    refs = provision_refs(db.instruments)
    base = copy.deepcopy(db.arguments[0])

    # 1. Tampered character breaks sequential verbatim check
    tampered = copy.deepcopy(base)
    tampered["sentences"][0]["text"] = tampered["sentences"][0]["text"] + "增字"
    errs = check_argument_record(tampered, cases_by_id, refs)
    assert any("does not match excerpt text verbatim in sequence" in e for e in errs)

    # 2. Dropping the trailing sentence breaks full-excerpt reconstruction
    dropped = copy.deepcopy(base)
    ex0_indices = [i for i, s in enumerate(dropped["sentences"]) if s["excerpt_index"] == 0]
    dropped["sentences"].pop(ex0_indices[-1])
    errs = check_argument_record(dropped, cases_by_id, refs)
    assert any("do not reconstruct full excerpt" in e for e in errs)

    # 3. Unknown FIRAC role and unknown annotation_mode are rejected
    bad_vocab = copy.deepcopy(base)
    bad_vocab["annotation_mode"] = "GOLD_MAGIC"
    bad_vocab["sentences"][0]["role"] = "OPINION"
    errs = check_argument_record(bad_vocab, cases_by_id, refs)
    assert any("unknown annotation_mode" in e for e in errs)
    assert any("unknown FIRAC role" in e for e in errs)

    # 4. Unknown provision reference is rejected
    bad_ref = copy.deepcopy(base)
    bad_ref["sentences"][0]["provisions_mentioned"] = ["EU-GDPR-2016#Article 999"]
    errs = check_argument_record(bad_ref, cases_by_id, refs)
    assert any("unknown provision reference" in e for e in errs)


def test_cohens_kappa_and_classification_metrics_exact_values() -> None:
    # 10 items: 5 FACT, 5 RULE in A; 5 FACT, 5 RULE in B; 8 agree, 2 disagree -> p_o=0.8, p_e=0.5 -> kappa=0.6
    y_a = ["FACT", "FACT", "FACT", "FACT", "FACT", "RULE", "RULE", "RULE", "RULE", "RULE"]
    y_b = ["FACT", "FACT", "FACT", "FACT", "RULE", "FACT", "RULE", "RULE", "RULE", "RULE"]
    assert cohens_kappa(y_a, y_b) == pytest.approx(0.6)

    m = classification_metrics(y_a, y_b)
    assert m["accuracy"] == 0.8
    assert m["disagreement_rate"] == 0.2
    assert m["cohens_kappa"] == 0.6
    assert m["per_class"]["FACT"]["f1"] == 0.8
    assert m["per_class"]["RULE"]["f1"] == 0.8
    assert m["macro_f1_present"] == 0.8

    # Edge case: perfect agreement on a single class
    assert cohens_kappa(["FACT", "FACT"], ["FACT", "FACT"]) == 1.0


def test_evaluate_aligned_records_supports_jurisdiction_breakdown_and_rejects_bad_labels() -> None:
    rows_a = [
        {"case_id": "C1", "sentence_id": "S001", "jurisdiction": "CN", "role": "FACT", "text": "a"},
        {"case_id": "C1", "sentence_id": "S002", "jurisdiction": "CN", "role": "RULE", "text": "b"},
        {"case_id": "C2", "sentence_id": "S001", "jurisdiction": "EU", "role": "ANALYSIS", "text": "c"},
        {"case_id": "C2", "sentence_id": "S002", "jurisdiction": "EU", "role": "", "text": "d"},
    ]
    rows_b = [
        {"case_id": "C1", "sentence_id": "S001", "jurisdiction": "CN", "role": "FACT", "text": "a"},
        {"case_id": "C1", "sentence_id": "S002", "jurisdiction": "CN", "role": "ANALYSIS", "text": "b"},
        {"case_id": "C2", "sentence_id": "S001", "jurisdiction": "EU", "role": "ANALYSIS", "text": "c"},
        {"case_id": "C2", "sentence_id": "S002", "jurisdiction": "EU", "role": "OTHER", "text": "d"},
    ]
    res = evaluate_aligned_records(rows_a, rows_b, "role", "role", by_jurisdiction=True)
    assert res["unlabeled_skipped"] == 1
    assert res["overall"]["n"] == 3
    assert len(res["disagreements"]) == 1
    assert res["disagreements"][0]["case_id"] == "C1"
    assert set(res["by_jurisdiction"]) == {"CN", "EU"}

    bad = copy.deepcopy(rows_b)
    bad[0]["role"] = "NOT_A_ROLE"
    with pytest.raises(ValueError, match="unknown label"):
        evaluate_aligned_records(rows_a, bad, "role", "role")


def test_get_case_exposes_draft_warning_and_blind_export_hides_draft_labels() -> None:
    db = load_database()
    dataset = build_dataset(db)
    idx = Index(dataset)
    view = get_case(idx, "EU-CASE-KNESCHKE-V-LAION")
    arg = view["argument_annotations"]
    assert arg["annotation_mode"] == "LLM_DRAFT"
    assert "尚未经法学双盲人工复核" in arg["warning"]
    assert len(arg["sentences"]) == 8

    blind_csv = Path(__file__).resolve().parent.parent / "research" / "lamus_pilot" / "blind_review_annotator_A.csv"
    with blind_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        assert "draft_role" not in (reader.fieldnames or [])
        rows = list(reader)
    assert len(rows) == 228
    assert all(r["human_role"] == "" for r in rows)


def test_review_regressions_word_boundaries_order_bool_index_and_schema() -> None:
    # Regression: corrupted spacing, mid-word split, reversed excerpt order, bool index, string provisions
    cases = {
        "CASE-X": {
            "id": "CASE-X",
            "excerpts": [
                {"source_id": "SRC-1", "kind": "facts", "text": "A part of the claim is invalid."},
                {"source_id": "SRC-1", "kind": "holding", "text": "Second excerpt."},
            ],
        }
    }

    def make_rec(sentences, **extra):
        rec = {
            "id": "ARG-CASE-X",
            "case_id": "CASE-X",
            "annotation_mode": "LLM_DRAFT",
            "annotator": "tester",
            "complete_excerpts": True,
            "sentences": sentences,
        }
        rec.update(extra)
        return rec

    # Corrupted Latin word spacing rejected
    rec_space = make_rec([
        {"id": "S1", "excerpt_index": 0, "source_id": "SRC-1", "text": "Apartoftheclaimisinvalid.", "role": "FACT"},
        {"id": "S2", "excerpt_index": 1, "source_id": "SRC-1", "text": "Second excerpt.", "role": "CONCLUSION"},
    ])
    assert any("spacing or text mismatch" in e for e in check_argument_record(rec_space, cases, set()))

    # Mid-word split ("in" + "valid.") rejected
    rec_split = make_rec([
        {"id": "S1", "excerpt_index": 0, "source_id": "SRC-1", "text": "A part of the claim is in", "role": "FACT"},
        {"id": "S2", "excerpt_index": 0, "source_id": "SRC-1", "text": "valid.", "role": "FACT"},
        {"id": "S3", "excerpt_index": 1, "source_id": "SRC-1", "text": "Second excerpt.", "role": "CONCLUSION"},
    ])
    assert any("splits inside a Latin word" in e for e in check_argument_record(rec_split, cases, set()))

    # Reversed excerpt order rejected
    rec_rev = make_rec([
        {"id": "S1", "excerpt_index": 1, "source_id": "SRC-1", "text": "Second excerpt.", "role": "CONCLUSION"},
        {"id": "S2", "excerpt_index": 0, "source_id": "SRC-1", "text": "A part of the claim is invalid.", "role": "FACT"},
    ])
    assert any("must follow excerpt order" in e for e in check_argument_record(rec_rev, cases, set()))

    # Bool excerpt_index, non-bool complete_excerpts, non-dict item, string provisions_mentioned rejected
    rec_types = make_rec(
        [
            "not-a-dict",
            {"id": "S1", "excerpt_index": False, "source_id": "SRC-1", "text": "A part of the claim is invalid.", "role": "FACT"},
            {
                "id": "S2",
                "excerpt_index": 1,
                "source_id": "SRC-1",
                "text": "Second excerpt.",
                "role": "CONCLUSION",
                "provisions_mentioned": "EU-GDPR-2016#Article 6",
            },
        ],
        complete_excerpts=0,
    )
    errs = check_argument_record(rec_types, cases, {"EU-GDPR-2016#Article 6"})
    assert any("must be a boolean" in e for e in errs)
    assert any("must be an object" in e for e in errs)
    assert any("out of range" in e for e in errs)
    assert any("must be a list of strings" in e for e in errs)


def test_review_regressions_sentencer_and_metrics_strictness() -> None:
    # Sentence-final numbers and non-dotted initialisms still split; ellipses and CJK continuation stay intact
    assert split_sentences("See Article 5. The court agrees.") == ["See Article 5.", "The court agrees."]
    assert split_sentences("Dies folgt aus § 44b UrhG. Die Klage scheitert.") == [
        "Dies folgt aus § 44b UrhG.",
        "Die Klage scheitert.",
    ]
    assert split_sentences("原告称“太离谱！”并请求法院判令赔偿。") == ["原告称“太离谱！”并请求法院判令赔偿。"]
    assert split_sentences("Quoted ... mid sentence continues.") == ["Quoted ... mid sentence continues."]

    # Metrics reject OOV labels, duplicate categories, duplicate keys, and missing label columns
    with pytest.raises(ValueError, match="out-of-vocabulary"):
        cohens_kappa(["FACT", "BOGUS"], ["FACT", "FACT"])
    with pytest.raises(ValueError, match="duplicates"):
        cohens_kappa(["FACT"], ["FACT"], categories=("FACT", "FACT"))

    rows_ok = [{"case_id": "C1", "sentence_id": "S1", "role": "FACT", "text": "x"}]
    rows_dup = rows_ok + [{"case_id": "C1", "sentence_id": "S1", "role": "RULE", "text": "x"}]
    with pytest.raises(ValueError, match="duplicate key"):
        evaluate_aligned_records(rows_dup, rows_ok, "role", "role")
    with pytest.raises(ValueError, match="missing label column"):
        evaluate_aligned_records(rows_ok, rows_ok, "typo_col", "role")

