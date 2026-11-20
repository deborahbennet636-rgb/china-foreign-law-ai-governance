"""One-off: write obligation records cut from Regulation (EU) 2024/1689.

Run from the repository root; refuses to overwrite. Deleted after use.
Article 4 is not cut: Regulation (EU) 2026/1744 replaced it, so the 2024
wording held here no longer states the duty.
"""
import json
import pathlib
import sys

OUT = pathlib.Path("data/obligations")
AI = "EU-AI-ACT-2024"
F35 = "第 99 条第 3 款：最高 3500 万欧元，或企业上一财年全球年营业额的 7%，取高者"
F15 = "第 99 条第 4 款：最高 1500 万欧元，或企业上一财年全球年营业额的 3%，取高者"
F101 = "第 101 条：由欧盟委员会处罚，最高 1500 万欧元或全球年营业额的 3%，取高者"
EXT_PROVIDER = "第 2 条第 1 款第 (a) 项：适用于在欧盟投放市场或投入使用的提供者，不论其设立于欧盟还是第三国；第 (c) 项：第三国的提供者与部署者，其系统输出在欧盟使用的，亦适用"
EXT_GPAI = "第 2 条第 1 款第 (a) 项：在欧盟投放通用目的 AI 模型的提供者，不论其设立于欧盟还是第三国"
HIGH_RISK_DATES = ("高风险义务。2024 年文本第 113 条定 2026-08-02（附件三）与 2027-08-02（第 6 条第 1 款）起适用；"
                   "2026/1744 号条例第 1 条第 (40) 点改为 2027-12-02（附件三）与 2028-08-02（附件一）。")


def ob(oid, prov, kind, modality, subject, quote, duty, trigger, penalty, note, ext=None):
    record = {"id": oid, "instrument_id": AI, "provision": prov, "kind": kind, "modality": modality,
              "subject": subject, "quote": quote, "duty": duty, "trigger": trigger, "penalty": penalty,
              "extraterritorial": ext is not None, "note": note}
    if ext:
        record["extraterritorial_basis"] = ext
    return record


RECORDS = [
    ob("OBL-AI-05", "Article 5", "PROHIBITION", "MUST_NOT", ["PROVIDER", "OPERATOR"],
       "The following AI practices shall be prohibited",
       "不得投放、投入使用或使用第 5 条第 1 款所列的 AI 实践（潜意识操纵、社会评分、无差别抓取人脸图像等）",
       "投放市场、投入使用或使用相关 AI 系统", F35,
       "2025-02-02 起适用。2026/1744 号条例在第 1 款新增第 (ba)(bb) 项（未经同意生成可识别自然人私密影像的系统、儿童性虐待材料），2026-12-02 起适用；本库所存是 2024 年文本，不含这两项。",
       EXT_PROVIDER),
    ob("OBL-AI-09", "Article 9", "SECURITY_ASSESSMENT", "MUST", ["PROVIDER"],
       "A risk management system shall be established, implemented, documented and maintained in relation to high-risk AI systems",
       "为高风险 AI 系统建立、实施、记录并维护覆盖全生命周期的风险管理体系", "提供高风险 AI 系统",
       F15 + "（经第 16 条，第 (a) 项）", HIGH_RISK_DATES),
    ob("OBL-AI-10", "Article 10", "DATA_SOURCE", "MUST", ["PROVIDER"],
       "Training, validation and testing data sets shall be relevant, sufficiently representative",
       "训练、验证与测试数据集须相关、有充分代表性，并尽可能无错误且完整", "以数据训练模型的高风险 AI 系统",
       F15 + "（经第 16 条，第 (a) 项）",
       HIGH_RISK_DATES + "同一条例替换了第 10 条第 1、6 款并删去第 5 款；本条所引第 3 款未改。"),
    ob("OBL-AI-12", "Article 12", "RECORD_KEEPING", "MUST", ["PROVIDER"],
       "High-risk AI systems shall technically allow for the automatic recording of events (logs) over the lifetime of the system",
       "高风险 AI 系统须在技术上支持全生命周期自动记录日志", "提供高风险 AI 系统",
       F15 + "（经第 16 条，第 (a) 项）", HIGH_RISK_DATES),
    ob("OBL-AI-14", "Article 14", "OTHER", "MUST", ["PROVIDER"],
       "can be effectively overseen by natural persons during the period in which they are in use",
       "高风险 AI 系统须设计为在使用期间能由自然人有效监督", "提供高风险 AI 系统",
       F15 + "（经第 16 条，第 (a) 项）", HIGH_RISK_DATES),
    ob("OBL-AI-22", "Article 22", "OTHER", "MUST", ["PROVIDER"],
       "providers established in third countries shall, by written mandate, appoint an authorised representative which is established in the Union",
       "第三国提供者在欧盟市场提供高风险系统前，须书面委任设立于欧盟的授权代表", "设立于第三国的提供者向欧盟市场提供高风险 AI 系统",
       F15 + "（第 (a)(b) 项）", HIGH_RISK_DATES + "本条只约束设立于欧盟境外的提供者，是 AI Act 对中国企业最直接的一条程序性义务。",
       "条文本身只适用于设立于第三国的提供者；适用范围另见第 2 条第 1 款第 (a) 项"),
    ob("OBL-AI-26", "Article 26", "OTHER", "MUST", ["OPERATOR"],
       "take appropriate technical and organisational measures to ensure they use such systems in accordance with the instructions for use",
       "部署者须按使用说明使用高风险系统，并指派具备能力的自然人监督", "部署高风险 AI 系统",
       F15 + "（第 (e) 项）", HIGH_RISK_DATES + "主体是部署者（deployer），本库归入「运营者」。"),
    ob("OBL-AI-49", "Article 49", "FILING", "MUST", ["PROVIDER"],
       "shall register themselves and their system in the EU database referred to in Article 71",
       "投放附件三所列高风险系统前，在欧盟数据库登记本人及系统", "投放附件三所列高风险 AI 系统（附件三第 2 点除外）",
       F15 + "（经第 16 条，第 (a) 项）", HIGH_RISK_DATES + "可由授权代表办理。"),
    ob("OBL-AI-50a", "Article 50", "DISCLOSURE", "MUST", ["PROVIDER"],
       "the natural persons concerned are informed that they are interacting with an AI system",
       "与自然人直接交互的 AI 系统须让对方知道在与 AI 交互（显而易见的除外）", "提供与自然人直接交互的 AI 系统",
       F15 + "（第 (g) 项）",
       "第 50 条属第四章，按第 113 条的一般适用日 2026-08-02 起适用。2026/1744 号条例只替换了第 50 条第 7 款（行为守则与实施法案），本条所引第 1、2、4 款未改。",
       EXT_PROVIDER),
    ob("OBL-AI-50b", "Article 50", "LABELING", "MUST", ["PROVIDER"],
       "shall ensure that the outputs of the AI system are marked in a machine-readable format and detectable as artificially generated or manipulated",
       "生成合成音频、图像、视频或文本的系统，输出须以机器可读方式标记并可被检测为人工生成", "提供生成合成内容的 AI 系统（含通用目的 AI 系统）",
       F15 + "（第 (g) 项）",
       "2026-08-02 起适用；2026/1744 号条例未改本款。与中国标识办法第五条的隐式标识功能相近，但义务主体、技术要求与例外不同，不宜直接对译。",
       EXT_PROVIDER),
    ob("OBL-AI-50c", "Article 50", "LABELING", "MUST", ["OPERATOR"],
       "shall disclose that the content has been artificially generated or manipulated",
       "部署者须披露深度伪造的图像、音频或视频内容系人工生成或操纵", "部署生成或操纵构成深度伪造内容的 AI 系统",
       F15 + "（第 (g) 项）",
       "2026-08-02 起适用；2026/1744 号条例未改本款。执法用途除外；明显属艺术、讽刺、虚构作品的，只须以不妨碍欣赏的方式披露。",
       EXT_PROVIDER),
    ob("OBL-AI-53c", "Article 53", "DATA_SOURCE", "MUST", ["PROVIDER"],
       "put in place a policy to comply with Union law on copyright and related rights",
       "通用目的 AI 模型提供者须制定遵守欧盟版权法的政策，并识别和遵守依 DSM 指令第 4 条第 3 款作出的权利保留", "提供通用目的 AI 模型",
       F101,
       "第五章自 2025-08-02 起适用，第 101 条罚款自 2026-08-02 起适用（第 113 条第 (b) 项）。2026/1744 号条例未改第 53 条。开源模型的豁免（第 2 款）不及于本项。",
       EXT_GPAI),
    ob("OBL-AI-53d", "Article 53", "DISCLOSURE", "MUST", ["PROVIDER"],
       "draw up and make publicly available a sufficiently detailed summary about the content used for training",
       "按 AI 办公室模板公开训练内容的足够详细的摘要", "提供通用目的 AI 模型",
       F101, "适用日期同第 53 条第 1 款第 (c) 项。开源模型的豁免（第 2 款）不及于本项。", EXT_GPAI),
    ob("OBL-AI-54", "Article 54", "OTHER", "MUST", ["PROVIDER"],
       "Prior to placing a general-purpose AI model on the Union market, providers established in third countries shall",
       "第三国的通用目的 AI 模型提供者在欧盟投放模型前，须书面委任设立于欧盟的授权代表", "设立于第三国的提供者在欧盟投放通用目的 AI 模型",
       F101, "2025-08-02 起适用。2026/1744 号条例未改本条。",
       "条文本身只适用于设立于第三国的提供者；适用范围另见第 2 条第 1 款第 (a) 项"),
    ob("OBL-AI-55", "Article 55", "SECURITY_ASSESSMENT", "MUST", ["PROVIDER"],
       "perform model evaluation in accordance with standardised protocols and tools reflecting the state of the art",
       "具有系统性风险的通用目的 AI 模型须按标准化协议开展模型评估，包括对抗测试", "提供具有系统性风险的通用目的 AI 模型",
       F101, "2025-08-02 起适用。同条另有评估缓解系统性风险、报告严重事件、保障网络安全等义务，本条只记第 (a) 项。", EXT_GPAI),
    ob("OBL-AI-73", "Article 73", "REPORTING", "MUST", ["PROVIDER"],
       "shall report any serious incident to the market surveillance authorities of the Member States where that incident occurred",
       "高风险系统发生严重事件的，向事发成员国市场监管机构报告", "欧盟市场上的高风险 AI 系统发生严重事件",
       F15 + "（经第 16 条，第 (a) 项）", HIGH_RISK_DATES),
]


def main() -> int:
    clash = [r["id"] for r in RECORDS if (OUT / f"{r['id']}.json").exists()]
    if clash:
        print("refusing to overwrite:", clash)
        return 1
    for record in RECORDS:
        (OUT / f"{record['id']}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(RECORDS)} obligations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
