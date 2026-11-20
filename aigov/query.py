"""Read-only queries over the built dataset, used by the MCP server.

Every function takes the dataset written by ``tools/build.py`` and returns
plain JSON-serialisable data. Nothing here decides anything about the law.
Two rules shape every answer:

* What a source says and what the editor reads into it come back under
  different keys. ``text`` and ``quote`` are verbatim and were matched
  against a snapshot when the database was built; anything under
  ``editorial`` is a classification or a paraphrase that no script checked.
* Every answer that rests on a source says where to read and cite it: the
  publisher's own page, with the day the snapshot was taken and its
  SHA-256. The copy in this database is for checking, not for citing.
"""
from typing import Any, Dict, List, Optional

from .query_search import resolve_label

Record = Dict[str, Any]

CITE_RULE = "引用请以发布机关页面（official_url）为准；本库副本只用于核对原文，不作引用来源。"
EDITORIAL_RULE = "editorial 下的字段是编者的分类或概括，脚本没有核对，不能当作原文引用。"


class NotFound(LookupError):
    """A requested record does not exist; the message says what does."""


def _drop_empty(record: Record) -> Record:
    """Leave out keys whose value is None, an empty string or an empty list."""
    return {key: value for key, value in record.items() if value not in (None, "", [], {})}


class Index:
    """The dataset, with every record reachable by id."""

    def __init__(self, dataset: Record) -> None:
        self.data = dataset
        self.sources = {item["id"]: item for item in dataset["sources"]}
        self.instruments = {item["id"]: item for item in dataset["instruments"]}
        self.cases = {item["id"]: item for item in dataset["cases"]}
        self.issues = {item["id"]: item for item in dataset["issues"]}
        self.obligations = {item["id"]: item for item in dataset["obligations"]}
        self.countermeasures = {item["id"]: item for item in dataset["countermeasures"]}

    def lookup(self, table: str, record_id: str) -> Record:
        """Return one record, or raise NotFound naming the ids that exist."""
        records = getattr(self, table)
        if record_id in records:
            return records[record_id]
        close = [key for key in records if record_id.upper() in key.upper()][:8]
        hint = f"相近的有：{close}" if close else f"可用的有：{sorted(records)[:12]}"
        raise NotFound(f"没有 id 为 {record_id!r} 的记录。{hint}")

    # ---- shared pieces ----

    def cite(self, source_ids: List[str]) -> Record:
        """Say where each fact can be read and cited."""
        sources = []
        unknown = [source_id for source_id in source_ids if source_id not in self.sources]
        for source_id in dict.fromkeys(source_ids):
            entry = self.sources.get(source_id, {})
            sources.append(_drop_empty({
                "source_id": source_id,
                "official_url": entry.get("url"),
                "publisher": entry.get("publisher"),
                "official": entry.get("official"),
                "kind": entry.get("kind"),
                "snapshot_taken": entry.get("fetched_at"),
                "sha256": entry.get("sha256"),
            }))
        block: Record = {"rule": CITE_RULE, "sources": sources}
        warnings = []
        if any(item.get("official") is False for item in sources):
            warnings.append("其中至少一份是转载页或数据库页，不是发布机关自己的页面。")
        if unknown:
            warnings.append(f"来源 {sorted(set(unknown))} 未登记，没有原址可查。")
        if warnings:
            block["warning"] = " ".join(warnings)
        return block

    def obligation_view(self, item: Record) -> Record:
        """An obligation with its verified quote apart from the editor's reading."""
        instrument = self.instruments.get(item["instrument_id"], {})
        provision = next((p for p in instrument.get("provisions", []) if p["no"] == item["provision"]), {})
        return {
            "id": item["id"],
            "provision_ref": f"{item['instrument_id']}#{item['provision']}",
            "instrument": instrument.get("short_title", item["instrument_id"]),
            "quote": item["quote"],
            "verification": item.get("verification"),
            "editorial": _drop_empty({
                "duty": item.get("duty"),
                "modality": item.get("modality"),
                "kind": item.get("kind"),
                "subject": item.get("subject"),
                "trigger": item.get("trigger"),
                "exception": item.get("exception"),
                "penalty": item.get("penalty"),
                "extraterritorial": item.get("extraterritorial"),
                "extraterritorial_basis": item.get("extraterritorial_basis"),
                "note": item.get("note"),
            }),
            "cite": self.cite([provision["source_id"]] if provision else []),
            **({"warning": warning} if (warning := _currency_warning(instrument)) else {}),
        }

    def instrument_summary(self, item: Record) -> Record:
        """The few fields that identify an instrument in a list."""
        return _drop_empty({
            "id": item["id"],
            "title": item["title"],
            "short_title": item.get("short_title"),
            "jurisdiction": item["jurisdiction"],
            "status": item.get("status"),
            "effective_at": item.get("effective_at"),
            "articles": len(item["provisions"]),
            "complete": item.get("complete"),
            "verification": item.get("verification"),
            "foreign_related": item.get("foreign_related"),
        })


# ---- instruments and provisions ----

def list_instruments(index: Index, jurisdiction: Optional[str] = None,
                     foreign_related: Optional[str] = None) -> Record:
    """List instruments, optionally of one jurisdiction or foreign-related tag."""
    items = [
        index.instrument_summary(item) for item in index.data["instruments"]
        if (jurisdiction is None or item["jurisdiction"] == jurisdiction)
        and (foreign_related is None or item.get("foreign_related") == foreign_related)
    ]
    return {"count": len(items), "instruments": items,
            "note": "foreign_related 是编者分类；complete 为 false 表示只收了部分条文或只登记了元数据。"}


def get_instrument(index: Index, instrument_id: str) -> Record:
    """One instrument with its dates, article labels, obligations and citation."""
    item = index.lookup("instruments", instrument_id)
    derived = (item.get("derived_dates") or {}).get("effective_at")
    obligations = [o for o in index.data["obligations"] if o["instrument_id"] == instrument_id]
    return _drop_empty({
        "id": item["id"],
        "title": item["title"],
        "short_title": item.get("short_title"),
        "jurisdiction": item["jurisdiction"],
        "issuer": item.get("issuer"),
        "doc_number": item.get("doc_number"),
        "published_at": item.get("published_at"),
        "effective_at": item.get("effective_at"),
        "effective_at_note": ("原文只写了规则，没有直接写这个日期；按 published_at 后第 "
                              f"{derived.get('plus_days')} 日推算") if derived else None,
        "status": item.get("status"),
        "status_note": item.get("status_note"),
        "complete": item.get("complete"),
        "articles": [provision["no"] for provision in item["provisions"]],
        "amends": item.get("amends"),
        "amended_by": item.get("amended_by"),
        "obligations": [o["id"] for o in obligations],
        "verification": item.get("verification"),
        "evidence_grade": item.get("evidence_grade"),
        "editorial": _drop_empty({
            "level": item.get("level"),
            "instrument_type": item.get("instrument_type"),
            "foreign_related": item.get("foreign_related"),
        }),
        "cite": index.cite(item.get("source_ids", [])),
    })


VERIFIED_TEXT = {
    "VERIFIED": "条号与正文一起与发布机关页面的快照逐字比对过。",
    "PARSED": "条号与正文一起与快照逐字比对过，但快照是转载页，不是发布机关的页面。",
}


def _currency(item: Record) -> Record:
    """How current the instrument's text is, as far as the database knows."""
    return _drop_empty({
        "status": item.get("status"),
        "effective_at": item.get("effective_at"),
        "effective_at_scope": "整部法规的施行日期，不一定是本条的适用日期。",
        "amended_by": item.get("amended_by"),
        "editorial": _drop_empty({"status_note": item.get("status_note")}),
    })


def _currency_warning(item: Record) -> Optional[str]:
    """A warning when the text held may no longer be the text in force."""
    if item.get("status") == "AMENDED" or item.get("amended_by"):
        return "所在法规已被修订；本条是库内收录的文本，可能不是现行文本，引用前须对照修订文件（见 currency）。"
    return None


def get_provision(index: Index, instrument_id: str, article: Any) -> Record:
    """One article, verbatim, with its obligations, citing cases and currency.

    ``article`` may be a label as printed or the article number as an integer.
    """
    item = index.lookup("instruments", instrument_id)
    labels = [provision["no"] for provision in item["provisions"]]
    if not labels:
        raise NotFound(f"{instrument_id} 只登记了元数据，没有收条文。")
    label, near = resolve_label(labels, article)
    if label is None:
        partial = "" if item.get("complete") else (
            f"本库只收了该法规的部分条文（{len(labels)} 条），找不到不说明原文没有这一条。")
        raise NotFound(f"{instrument_id} 中找不到 {article!r}（只接受 第七条、（七）、Article 7、Sec. 7、§ 7 "
                       f"或纯数字 7 这几种写法）。可选：{near}。{partial}")
    provision = next(p for p in item["provisions"] if p["no"] == label)
    ref = f"{instrument_id}#{label}"
    cited_by = [
        _drop_empty({"case_id": case["id"], "short_name": case["short_name"], "basis": anchor["basis"],
                     "quote": anchor.get("quote"), "editorial_note": anchor.get("note")})
        for case in index.data["cases"] for anchor in case.get("legal_anchors", [])
        if anchor.get("provision") == ref
    ]
    return _drop_empty({
        "ref": ref,
        "instrument": index.instrument_summary(item),
        "article": label,
        "resolved_from": article if article != label else None,
        "division": provision.get("division"),
        "heading": provision.get("heading"),
        "text": provision["text"],
        "text_verified": VERIFIED_TEXT.get(item.get("verification"), "尚无快照，未核对。"),
        "currency": _currency(item),
        "warning": _currency_warning(item),
        "obligations": [index.obligation_view(o) for o in index.data["obligations"]
                        if o["instrument_id"] == instrument_id and o["provision"] == label],
        "cited_by_cases": cited_by,
        "cited_by_note": ("basis 为 CITED_IN_SOURCE 表示裁判文书明文援引；EDITORIAL 是编者按主题对应，"
                          "不能当作裁判依据。") if cited_by else None,
        "cite": index.cite([provision["source_id"]]),
    })


# ---- obligations ----

def find_obligations(index: Index, kind: Optional[str] = None, modality: Optional[str] = None,
                     subject: Optional[str] = None, instrument_id: Optional[str] = None,
                     extraterritorial_only: bool = False) -> Record:
    """Obligations matching every filter given."""
    if instrument_id is not None:
        index.lookup("instruments", instrument_id)
    items = [
        index.obligation_view(o) for o in index.data["obligations"]
        if (kind is None or o.get("kind") == kind)
        and (modality is None or o.get("modality") == modality)
        and (subject is None or subject in o.get("subject", []))
        and (instrument_id is None or o["instrument_id"] == instrument_id)
        and (not extraterritorial_only or o.get("extraterritorial"))
    ]
    return {
        "count": len(items),
        "obligations": items,
        "note": "quote 是条文原句，已核对它逐字出现在 provision_ref 所指条文中。" + EDITORIAL_RULE,
    }


# ---- issues ----

def list_issues(index: Index) -> Record:
    """Every issue, comparability first."""
    items = []
    for issue in index.data["issues"]:
        comparison = issue.get("comparison") or {}
        items.append({
            "comparable": comparison.get("comparable"),
            "id": issue["id"],
            "title": issue["title"],
            "question": issue.get("question"),
            "jurisdictions_with_material": [
                p["jurisdiction"] for p in issue.get("positions", []) if p.get("nature") not in (None, "NONE")
            ],
        })
    return {"count": len(items), "issues": items,
            "note": "comparable 为 false 的争点，各法域不能当作同一问题的几种答案并列。"}


def get_issue(index: Index, issue_id: str) -> Record:
    """One issue, leading with whether its jurisdictions may be compared."""
    issue = index.lookup("issues", issue_id)
    comparison = issue.get("comparison") or {"comparable": None, "reason": "本争点未声明是否可比。"}
    positions = []
    for position in issue.get("positions", []):
        positions.append(_drop_empty({
            "jurisdiction": position["jurisdiction"],
            "nature": position.get("nature"),
            "summary_editorial": position.get("summary"),
            "provisions": position.get("provisions"),
            "cases": position.get("cases"),
            "obligations": position.get("obligations"),
        }))
    reading = ("各栏不能当作同一问题的几种答案并列或排高低；原因见 comparison.reason。"
               if comparison.get("comparable") is not True else "各栏材料性质相称，可以并排读。")
    return _drop_empty({
        "comparison": comparison,
        "reading_rule": reading,
        "id": issue["id"],
        "title": issue["title"],
        "question": issue.get("question"),
        "positions": positions,
        "editorial": _drop_empty({"editor_note": issue.get("editor_note")}),
        "note": ("争点的题目、问题、各栏概述和编者注都是编者撰写的；所依据的条文、案例、义务用 "
                 "get_provision / get_case / find_obligations 取原文。"),
    })


# ---- countermeasures and cases ----

def _effective_rule(item: Record) -> Optional[str]:
    """Quote the clause that was checked, never a stock phrase."""
    if not item.get("effective_on_publication"):
        return None
    clause = (item.get("meta_evidence") or {}).get("effective_at", "")
    return f"原文：「{clause}」；原文未写具体日期，生效日取公布日。"


def _measure_view(index: Index, item: Record) -> Record:
    """A countermeasure: checked title and dates apart from the editor's reading."""
    instrument = index.instruments.get(item.get("instrument_id") or "", {})
    return _drop_empty({
        "id": item["id"],
        "direction": item.get("direction"),
        "title": item["title"],
        "jurisdiction": item.get("jurisdiction"),
        "announced_at": item.get("announced_at"),
        "effective_at": item.get("effective_at"),
        "effective_rule": _effective_rule(item),
        "authorised_by": _drop_empty({"instrument_id": item.get("instrument_id"),
                                      "short_title": instrument.get("short_title")}),
        "verification": item.get("verification"),
        "editorial": _drop_empty({"measure_type": item.get("measure_type"), "target": item.get("target"),
                                  "issuer": item.get("issuer"), "status": item.get("status"),
                                  "note": item.get("note")}),
        "cite": index.cite(item.get("source_ids", [])),
    })


def list_countermeasures(index: Index, direction: Optional[str] = None,
                         measure_type: Optional[str] = None) -> Record:
    """Return measures in two lists that are never merged.

    ``measure_type`` filters on the editor's classification.
    """
    result: Record = {
        "note": "境外对华与中国对外措施分开列出：两者依据的法律、程序和对象不同，合成一张表会被读成对等。",
    }
    for key in ("INBOUND_TO_CN", "OUTBOUND_FROM_CN"):
        if direction not in (None, key):
            continue
        result[key] = [
            _measure_view(index, item) for item in index.data["countermeasures"]
            if item.get("direction") == key and (measure_type is None or item.get("measure_type") == measure_type)
        ]
    return result


def get_case(index: Index, case_id: str) -> Record:
    """One case with verbatim excerpts, cited provisions and citation."""
    case = index.lookup("cases", case_id)
    sources = list((case.get("scopes") or {}).keys()) + [e["source_id"] for e in case.get("excerpts", [])]
    return _drop_empty({
        "id": case["id"],
        "short_name": case.get("short_name"),
        "caption": case.get("caption"),
        "jurisdiction": case.get("jurisdiction"),
        "forum": case.get("forum"),
        "case_numbers": case.get("case_numbers"),
        "decided_at": case.get("decided_at"),
        "procedural_stage": case.get("procedural_stage"),
        "excerpts": [{"kind": e["kind"], "text": e["text"], "source_id": e["source_id"]} for e in case.get("excerpts", [])],
        "legal_anchors": [_drop_empty({"provision": a["provision"], "basis": a["basis"], "quote": a.get("quote"),
                                       "editorial_note": a.get("note")}) for a in case.get("legal_anchors", [])],
        "issues": case.get("issues"),
        "verification": case.get("verification"),
        "editorial": _drop_empty({"outcome": case.get("outcome"), "is_final": case.get("is_final"),
                                  "outcome_note": case.get("outcome_note")}),
        "cite": index.cite(sources),
    })


# ---- the database itself ----

def describe_database(index: Index) -> Record:
    """Scope, layers, counts, verification levels, gaps and rules."""
    stats = index.data["stats"]
    return {
        "name": "涉外法治与人工智能治理对应库",
        "schema": index.data["schema"],
        "built_at": index.data["built_at"],
        "scope": "中国涉外法治（数据出境、反制裁、阻断、出口管制）与人工智能治理；中国、欧盟、美国。不是全球库，也不是任何一地的全量库。",
        "layers": {
            "instruments": f"{stats['instruments']} 部法规，{stats['provisions']} 条条文，条号与正文逐字核对",
            "obligations": f"{stats['obligations']} 条义务，原句逐字落在所指条文中",
            "issues": f"{stats['issues']} 个争点，每栏声明材料性质，整体声明是否可比",
            "countermeasures": f"{stats['countermeasures']} 条对外措施，境外对华与中国对外分开记",
            "cases": f"{stats['cases']} 件案例",
        },
        "verification_levels": {
            "VERIFIED": "全部引文与发布机关自己的页面或文书快照逐字一致",
            "PARSED": "引文与快照一致，但至少一份快照是转载页",
            "PENDING": "尚无快照",
        },
        "not_covered": [
            "条文的逐条版本史：只记施行日期与修订关系，不能回答某条在某日的旧写法",
            "欧盟《人工智能法》2026/1744 号修订的逐条变动",
            "两用物项出口管制清单本身",
            "SDN、UFLPA 实体清单等名单的全量导出：只收了少数个案，不是名单本身",
        ],
        "rules": [CITE_RULE, EDITORIAL_RULE, "没有命中只说明本库没有收，不说明不存在。"],
        "stats": stats,
    }
