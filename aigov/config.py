"""Project paths and controlled vocabularies.

Everything that other modules treat as a constant lives here, so that the
validator, the builder and the tests agree on one definition.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Paths:
    """Filesystem layout of the database."""

    root: Path = ROOT
    data: Path = ROOT / "data"
    raw: Path = ROOT / "data" / "raw"
    sources: Path = ROOT / "data" / "sources.json"
    instruments: Path = ROOT / "data" / "instruments"
    cases: Path = ROOT / "data" / "cases"
    issues: Path = ROOT / "data" / "issues"
    leads: Path = ROOT / "data" / "leads"
    obligations: Path = ROOT / "data" / "obligations"
    countermeasures: Path = ROOT / "data" / "countermeasures"
    specs: Path = ROOT / "ingest"
    web: Path = ROOT / "web"
    dist: Path = ROOT / "dist"


PATHS = Paths()

SCHEMA_VERSION = "aigov-db/v1"

# Verification levels are computed by the build, never typed in by hand.
VERIFIED = "VERIFIED"  # every quote matches a snapshot of an official source
PARSED = "PARSED"  # every quote matches a snapshot of a non-official source
PENDING = "PENDING"  # no snapshot yet; only identifiers and links

SOURCE_KINDS: FrozenSet[str] = frozenset(
    {
        "OFFICIAL_TEXT",  # the instrument as published by its issuer
        "JUDGMENT",  # the judgment or order itself
        "OFFICIAL_DIGEST",  # a court's or regulator's own case summary
        "SECONDARY",  # law-firm notes, press, third-party trackers
    }
)

# Evidence grade follows the kind of source a record rests on.
GRADE_BY_KIND = {
    "OFFICIAL_TEXT": "A",
    "JUDGMENT": "A",
    "OFFICIAL_DIGEST": "B",
    "SECONDARY": "C",
}

JURISDICTIONS: FrozenSet[str] = frozenset({"CN", "EU", "US"})

INSTRUMENT_TYPES: FrozenSet[str] = frozenset(
    {
        "AI_SPECIFIC",  # 专门规范人工智能的立法或规章
        "GENERAL_LAW_CITED",  # 一般法，只为被援引的条文入库
        "RELATED_LAW",  # 涉外、数据、出口管制等相邻领域，全文入库
    }
)
INSTRUMENT_STATUS: FrozenSet[str] = frozenset(
    {"PROPOSED", "ADOPTED", "IN_FORCE", "AMENDED", "REPEALED", "UNKNOWN"}
)

FORUM_TYPES: FrozenSet[str] = frozenset({"COURT", "REGULATOR"})
STAGES: FrozenSet[str] = frozenset(
    {"FILED", "FIRST_INSTANCE", "APPEAL", "RETRIAL", "ENFORCEMENT_DECISION"}
)
# A case outcome is never just win or lose: pending, settled and unverified
# are states of their own.
OUTCOMES: FrozenSet[str] = frozenset(
    {
        "CLAIMANT_PREVAILED",
        "CLAIMANT_PARTLY_PREVAILED",
        "RESPONDENT_PREVAILED",
        "SETTLED",
        "DISMISSED",
        "PENDING",
        "UNVERIFIED",
    }
)
AI_ROLES: FrozenSet[str] = frozenset(
    {"TRAINING", "OUTPUT", "DEPLOYMENT", "USE_BY_PARTY", "DETECTION"}
)
EXCERPT_KINDS: FrozenSet[str] = frozenset({"facts", "holding", "significance"})
ANCHOR_BASIS: FrozenSet[str] = frozenset({"CITED_IN_SOURCE", "EDITORIAL"})
LEAD_STATUS: FrozenSet[str] = frozenset({"OPEN", "INGESTED", "REJECTED"})

# ---------------------------------------------------------------------------
# v1 · 义务层
#
# A provision says what it says. An obligation is the same words cut down to
# one operative sentence, so that "what does this instrument require of whom"
# can be answered without reading every article. The quote is the provision's
# own text and is checked against it; the category is the editor's reading.
# ---------------------------------------------------------------------------

MODALITIES: FrozenSet[str] = frozenset(
    {
        "MUST",  # 应当
        "MUST_NOT",  # 不得、禁止
        "MAY",  # 可以
        "MAY_NOT",  # 可以不
        "ENCOURAGED",  # 鼓励、支持
    }
)

OBLIGATION_KINDS: FrozenSet[str] = frozenset(
    {
        "DATA_SOURCE",  # 数据与模型来源合法
        "SECURITY_ASSESSMENT",  # 安全评估、风险评估
        "FILING",  # 备案、登记
        "LABELING",  # 标识、标注
        "DISCLOSURE",  # 公开、公示、披露
        "CONSENT",  # 告知、同意
        "LOCALIZATION",  # 境内存储、本地化
        "RECORD_KEEPING",  # 日志、记录留存
        "PROHIBITION",  # 单纯禁止某类行为
        "REPORTING",  # 报送、报告
        "LICENSE",  # 许可、准入
        "CERTIFICATION",  # 认证
        "CONTRACT",  # 与境外接收方订立合同或法律文件
        "PROTECTION",  # 保护义务（权益、秘密、未成年）
        "COOPERATION",  # 配合监督检查
        "OTHER",
    }
)

OBLIGATION_SUBJECTS: FrozenSet[str] = frozenset(
    {
        "PROVIDER",  # 服务提供者、生产者
        "USER",  # 用户、个人
        "PLATFORM",  # 平台经营者
        "OPERATOR",  # 运营者、处理者
        "DATA_HANDLER",  # 数据处理者
        "STATE_AGENCY",  # 国家机关、监管部门
        "IMPORTER",  # 进口经营者
        "EXPORTER",  # 出口经营者
        "ORGANIZATION",  # 组织、企业
        "CITIZEN",  # 公民、个人
        "OTHER",
    }
)

# ---------------------------------------------------------------------------
# v1 · 涉外维度
#
# ``level`` and ``instrument_type`` are classed by the editor and the viewer
# says so. These two are the same kind of judgement, kept apart because they
# answer the question a reader of a 涉外 database actually asks.
# ---------------------------------------------------------------------------

FOREIGN_RELATED: FrozenSet[str] = frozenset(
    {
        "FOREIGN_SPECIFIC",  # 涉外专门立法
        "FOREIGN_CLAUSE",  # 通用立法中的涉外条款
        "DOMESTIC",  # 无涉外条款
        "UNKNOWN",
    }
)

# ---------------------------------------------------------------------------
# v1 · 对外措施层
#
# Reading inbound and outbound measures as one list is how a comparison turns
# into a claim. They are kept apart by construction.
# ---------------------------------------------------------------------------

MEASURE_DIRECTIONS: FrozenSet[str] = frozenset(
    {
        "INBOUND_TO_CN",  # 外国或国际组织针对中国主体的措施
        "OUTBOUND_FROM_CN",  # 中国针对境外主体的措施
    }
)

MEASURE_TYPES: FrozenSet[str] = frozenset(
    {
        "SANCTION",
        "EXPORT_CONTROL",
        "INVESTMENT_SCREENING",
        "DATA_RESTRICTION",
        "ENTITY_LIST",
        "BLOCKING",
        "TARIFF",
        "IMPORT_BAN",
        "OTHER",
    }
)

MEASURE_STATUS: FrozenSet[str] = frozenset({"ANNOUNCED", "IN_FORCE", "LIFTED", "UNKNOWN"})

# ---------------------------------------------------------------------------
# v1 · 议题可比性
#
# The one thing a cross-jurisdiction table must not do is put a statute and a
# first-instance judgment side by side and call it a comparison. Each position
# therefore declares what kind of material it rests on, and an issue declares
# whether its positions can be compared at all.
# ---------------------------------------------------------------------------

MATERIAL_NATURES: FrozenSet[str] = frozenset(
    {
        "NORMATIVE",  # 法律、法规、规章
        "JUDICIAL_INTERPRETATION",  # 司法解释、指导意见
        "CASE",  # 个案裁判
        "GUIDANCE",  # 监管指南、典型案例发布
        "STANDARD",  # 国家标准、行业标准
        "UNOFFICIAL",  # 只有二手材料
        "NONE",  # 库内没有这一法域的材料，留白
    }
)
