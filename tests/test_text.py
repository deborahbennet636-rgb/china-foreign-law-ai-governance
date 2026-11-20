"""Tests for text matching, splitting, digest parsing and snapshot reading."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aigov import sources  # noqa: E402
from aigov.caseparse import clean_lines, extract_block, split_sections  # noqa: E402
from aigov.config import Paths  # noqa: E402
from aigov.evidence import date_renderings, long_enough, quote_states_date, states_token  # noqa: E402
from aigov.splitter import (  # noqa: E402
    check_consecutive,
    check_sequence,
    cn_number,
    get_splitter,
    select_provisions,
    slice_lines,
)
from aigov.textnorm import fold, html_to_text, normalize, occurs  # noqa: E402


def test_matching_ignores_whitespace_and_width_only() -> None:
    assert normalize("第 一 条\n ＡＩ") == "第一条AI"
    page = fold("甲公司赔偿乙公司\n12万元。")
    assert occurs(page, "赔偿乙公司 12万元")
    assert not occurs(page, "赔偿乙公司21万元")
    assert not occurs(page, "   ")


def test_latin_match_must_sit_on_word_boundaries() -> None:
    """Review finding: with spaces removed, 'lawful' was found inside 'unlawful'."""
    page = fold("The conduct was unlawful under Section 107.")
    assert occurs(page, "was unlawful under")
    assert not occurs(page, "lawful under Section 107")
    assert not occurs(page, "The conduct was unlaw")
    assert not occurs(fold("decided in 2025"), "decided in 202")


def test_pdf_style_spacing_inside_words_still_matches() -> None:
    assert occurs(fold("summary judgment for Anthro pic that the training use"), "judgment for Anthropic that")


def test_case_is_folded_only_on_request() -> None:
    text = "REGULATION (EU) 2024/1689 OF THE EUROPEAN PARLIAMENT"
    assert not occurs(fold(text), "Regulation (EU) 2024/1689 of the European Parliament")
    assert occurs(fold(text, ignore_case=True), "Regulation (EU) 2024/1689 of the European Parliament", ignore_case=True)


def test_html_to_text_drops_scripts_and_keeps_paragraphs() -> None:
    text = html_to_text("<p>第一条 甲</p><script>var a = '第九条';</script><p>第二条&nbsp;乙</p>")
    assert text.split("\n") == ["第一条 甲", "第二条 乙"]


@pytest.mark.parametrize(
    ("numeral", "value"),
    [("十二", 12), ("二十四", 24), ("一百零五", 105), ("一千一百九十七", 1197), ("一千零三十二", 1032)],
)
def test_cn_number(numeral: str, value: int) -> None:
    assert cn_number(numeral) == value


@pytest.mark.parametrize("bad", ["第三", ""])
def test_cn_number_rejects_non_numerals(bad: str) -> None:
    with pytest.raises(ValueError):
        cn_number(bad)


def test_cn_article_splitter_tracks_chapters_and_sections() -> None:
    lines = ["标题", "第一章 总则", "第一条 甲。", "续段。", "第二章 规范", "第一节 一般规定", "第二条 乙。"]
    provisions = get_splitter("cn-article")(lines)
    assert [(p["no"], p["ordinal"], p["division"], p["text"]) for p in provisions] == [
        ("第一条", 1, "第一章 总则", "甲。\n续段。"),
        ("第二条", 2, "第二章 规范 / 第一节 一般规定", "乙。"),
    ]
    check_sequence(provisions, 2)


def test_body_lines_that_look_like_headings_stay_in_the_body() -> None:
    """Review finding: such lines closed the article and dropped the rest of it."""
    lines = ["第一条 甲。", "第三章规定的情形除外。", "第三条规定的期限届满后适用。", "末段。", "第二条 乙。"]
    provisions = get_splitter("cn-article")(lines)
    assert [p["no"] for p in provisions] == ["第一条", "第二条"]
    assert provisions[0]["text"] == "甲。\n第三章规定的情形除外。\n第三条规定的期限届满后适用。\n末段。"


def test_check_sequence_detects_a_missing_provision() -> None:
    provisions = get_splitter("cn-article")(["第一条 甲。", "第三条 丙。"])
    with pytest.raises(ValueError):
        check_sequence(provisions, 3)


def test_selection_from_a_long_text_requires_unbroken_numbering() -> None:
    """Review finding: in select mode a false heading cut an article short unnoticed."""
    good = get_splitter("cn-article")(["第七条 甲。", "第八条 乙。", "第九条 丙。"])
    check_consecutive(good)
    broken = get_splitter("cn-article")(["第七条 甲。", "第三条 假标题。", "第八条 乙。"])
    with pytest.raises(ValueError):
        check_consecutive(broken)
    with pytest.raises(ValueError):
        check_consecutive([])


def test_eu_splitter_takes_title_from_next_line_and_stops_at_sections() -> None:
    lines = ["CHAPTER I", "Article 1", "Subject matter", "Body one.", "SECTION 2", "Article 2", "Scope", "Body two."]
    provisions = get_splitter("eu-article")(lines)
    assert provisions[0]["heading"] == "Subject matter"
    assert provisions[0]["text"] == "Body one."
    assert provisions[1]["division"] == "CHAPTER I / SECTION 2"


def test_select_provisions_fails_when_one_is_absent() -> None:
    provisions = get_splitter("cn-article")(["第一条 甲。", "第二条 乙。"])
    assert [p["no"] for p in select_provisions(provisions, ["第二条"])] == ["第二条"]
    with pytest.raises(ValueError):
        select_provisions(provisions, ["第二条", "第九条"])


def test_slice_lines_uses_last_start_marker() -> None:
    text = "办法\n导言\n办法\n第一条 甲。\n关闭\n页脚"
    assert slice_lines(text, "办法", "关闭") == ["办法", "第一条 甲。"]
    with pytest.raises(ValueError):
        slice_lines(text, "不存在", None)


def test_digest_block_and_sections() -> None:
    page = "目录\n案例一 甲案\n案例二 乙案\n案例一 甲案\n【基本案情】\n事实。\n【裁判结果】\n判决。\n【案号】\n(2024)某号\n案例二 乙案\n【基本案情】\n其他。"
    block = extract_block(clean_lines(page), "案例一", "案例二")
    title, sections = split_sections(block, {"facts": "【基本案情】", "holding": "【裁判结果】"}, ["【案号】"])
    assert title == ["案例一 甲案"]
    assert sections == {"facts": ["事实。"], "holding": ["判决。"]}


def test_digest_sections_fail_when_a_heading_is_missing() -> None:
    with pytest.raises(ValueError):
        split_sections(["标题", "【基本案情】", "事实。"], {"facts": "【基本案情】", "holding": "【裁判结果】"})


def test_date_renderings_cover_the_formats_in_use() -> None:
    assert date_renderings("2025-07-18")[0] == "2025年7月18日"
    assert quote_states_date("Decided March 18, 2025", "2025-03-18")
    assert quote_states_date("Done at Strasbourg, 8 July 2026.", "2026-07-08")
    assert quote_states_date("L series 2024/1689 12.7.2024", "2024-07-12")
    assert quote_states_date("本办法自2025年9月1日起施行", "2025-09-01")
    assert not quote_states_date("2025年7月18日", "2025-07-19")


@pytest.mark.parametrize(
    ("quote", "iso_date"),
    [
        ("Done at Strasbourg, 18 July 2026.", "2026-07-08"),
        ("18.7.2026", "2026-07-08"),
        ("21 July 2026", "2026-07-01"),
        ("July 18, 2025", "2025-07-01"),
        ("2025年7月18日", "2025-07-01"),
        ("12025年7月1日", "2025-07-01"),
    ],
)
def test_a_date_is_not_found_inside_a_longer_date(quote: str, iso_date: str) -> None:
    """Review finding: '8 July 2026' was found inside '18 July 2026'."""
    assert not quote_states_date(quote, iso_date)


def test_tokens_must_be_whole() -> None:
    """Review finding: a truncated or empty case number passed."""
    assert states_token("Decided March 18, 2025 No. 23- 5233", "No. 23-5233")
    assert not states_token("No. 23-5233", "23-52")
    assert not states_token("No. 23-5233", "")
    assert states_token("一审：某法院（2024）苏0214民初9489号", "（2024）苏0214民初9489号")
    assert not states_token("一审：某法院（2024）苏0214民初9489号", "（2024）苏0214民初948")
    assert not states_token("某部令第11号", "令第1号")


def test_short_quotes_are_not_evidence() -> None:
    """Review finding: an is_final quote of 'the' passed."""
    assert not long_enough("the")
    assert not long_enough("affirmed.")
    assert not long_enough("判决已生效")
    assert long_enough("该一审判决已生效。")
    assert long_enough("We affirm the denial")


def test_text_is_read_only_from_bytes_that_match_their_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding: hashes were checked separately from the text that was matched."""
    monkeypatch.setattr(sources, "PATHS", Paths(data=tmp_path))
    (tmp_path / "a.txt").write_bytes("第一条 甲。".encode("utf-8"))
    good = {"file": "a.txt", "sha256": sources.sha256_of("第一条 甲。".encode("utf-8"))}
    assert sources.read_text(good) == "第一条 甲。"
    (tmp_path / "a.txt").write_bytes("第一条 乙。".encode("utf-8"))
    changed = {"file": "a.txt", "sha256": sources.sha256_of("第一条 乙。".encode("utf-8"))}
    assert sources.read_text(changed) == "第一条 乙。"
    with pytest.raises(ValueError):
        sources.read_text({"file": "a.txt", "sha256": "0" * 64})


def test_a_pdf_is_never_decoded_as_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources, "PATHS", Paths(data=tmp_path))
    payload = b"%PDF-1.7 binary"
    (tmp_path / "b.html").write_bytes(payload)
    with pytest.raises(ValueError):
        sources.read_text({"file": "b.html", "sha256": sources.sha256_of(payload)})


def test_latin_words_cannot_be_redivided() -> None:
    """Round 2: with spaces removed, 'apart' was found in 'a part'."""
    page = fold("It was a part of the deal with the rapist.", keep_word_spaces=True)
    assert occurs(page, "a  part of the\ndeal", keep_word_spaces=True)
    assert not occurs(page, "apart of the deal", keep_word_spaces=True)
    assert not occurs(page, "with therapist", keep_word_spaces=True)
    chinese = fold("第一条 提供者 应当\n标识 AI 生成内容。", keep_word_spaces=True)
    assert occurs(chinese, "提供者应当标识AI生成内容", keep_word_spaces=True)


def test_a_provision_label_is_not_found_in_its_numbered_sibling() -> None:
    """Round 2: 第二百八十七条 was found inside 第二百八十七条之一, a different article."""
    assert states_token("依照刑法第二百八十七条的规定", "第二百八十七条")
    assert not states_token("依照刑法第二百八十七条之一的规定", "第二百八十七条")


def test_dates_written_in_chinese_numerals_are_recognised() -> None:
    assert quote_states_date("二〇二三年十一月二十七日", "2023-11-27")
    assert quote_states_date("二〇二四年四月二十三日", "2024-04-23")
    assert quote_states_date("二〇二五年十月十日", "2025-10-10")
    assert not quote_states_date("二〇二三年十一月二十七日", "2023-11-17")


def test_a_sentence_is_not_a_chapter_heading() -> None:
    """Round 2: '第三章 规定的情形除外。' closed the article and dropped the rest."""
    lines = ["第一章 总则", "第一条 甲。", "第三章 规定的情形除外。", "末段。", "二、其他", "第二条 乙。"]
    provisions = get_splitter("cn-article")(lines)
    assert [p["division"] for p in provisions] == ["第一章 总则", "第一章 总则"]
    assert provisions[0]["text"] == "甲。\n第三章 规定的情形除外。\n末段。\n二、其他"
    points = get_splitter("cn-point")(["一、总体要求", "（一）甲。", "二、依法办理，不得拖延。", "（二）乙。"])
    assert points[0]["text"] == "甲。\n二、依法办理，不得拖延。"
