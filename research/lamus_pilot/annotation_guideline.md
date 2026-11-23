# LAMUS 6 类 FIRAC 跨法域句级标注规范（试点 v1）

> 适用范围：本库已入库的 17 件中美欧 AI 治理裁判与监管决定（228 句，覆盖中、英、德三语）。
> 方法来源：参照 *LAMUS: A Large-Scale Corpus for Legal Argument Mining from U.S. Caselaw using LLMs*（arXiv:2603.08286v2）的 6 类 FIRAC 句级论证体系，并针对中国典型案例/判决书与欧盟数据保护行政决定作跨法域边界细化。

---

## 一、不变量与状态声明

1. **逐字溯源不变量**：每一句 `text` 均由 `aigov/sentencer.py` 从已通过快照校验的案例摘录中无损切出，校验脚本强制检查 `sentence.text ⊆ case.excerpts[i].text ⊆ snapshot` 且整段拼接零漏字、零改写。
2. **标注状态分层**：
   - `LLM_DRAFT`：模型初标，**不得**直接当作人工黄金标准引用；
   - `HUMAN_REVIEWED`：单人法学复核；
   - `DOUBLE_BLIND_ADJUDICATED`：双人盲标、计算 Cohen's $\kappa$ 并就分歧句仲裁定稿。

---

## 二、6 类 FIRAC 标签定义与硬边界

| 标签 | 英文对应 | 核心定义 | 典型句例 |
|---|---|---|---|
| **`FACT`** | Fact | 案件背景事实、当事人行为、技术/产品机制、双方诉讼主张与抗辩、庭审勘验查明事实，以及立案、上诉、撤诉、决定撤下等**程序经过** | 「原告李某某使用 Stable Diffusion 生成图片……」「宣判后，双方均未提起上诉，该判决已生效。」 |
| **`ISSUE`** | Issue | 法院或监管机构明确归纳的**待决法律问题 / 争议焦点**，或明确声明**不予审理 / 另案保留**的争议事项 | 「本案是一起厘清使用检索增强生成技术的搜索引擎服务提供者侵权责任边界的典型案例。」「Given that holding, we need not address...」 |
| **`RULE`** | Rule / Law / Holding | 脱离本案具体当事人事实的**一般性法律规范**：引述法条原文、裁判依据条文清单、抽象司法检验标准，以及典型案例中提炼的**普遍裁判规则** | 「著作权法规定，作者限于自然人、法人或非法人组织……」「综上，依照《中华人民共和国民法典》第……条……判决如下：」 |
| **`ANALYSIS`** | Analysis | **涵摄与说理**：将法律规则、合同条款或司法标准适用于本案具体事实与证据，论证侵权、合理使用、过错或豁免是否成立的推理句 | 「本案中，被告虽然使用原告的视频制作视频模板，但并未利用原告的肖像……」「FINDING that ... data are stored in the PRC, in violation of Article 32...」 |
| **`CONCLUSION`** | Conclusion | 法院或监管机构对本案具体主体作出的**最终法律认定、判项主文、罚款/禁令命令、简易判决裁定或二审维持/改判结果** | 「因此，被告的行为不构成对原告肖像权的侵害。」「This order grants summary judgment for Anthropic...」「二、被告赔偿原告经济损失 183 000 元；」 |
| **`OTHER`** | Other | 宏观时代背景、政策意义赞语、入选典型案例荣誉记录、文书结构标题（如 `ORDERS`）及法官给读者的适用射程提示 | 「人工智能、大数据等新技术新应用不断涌现……」「本案入选最高人民法院……典型民事案例。」 |

### 高频边界判定规则（双盲标注前必读）

1. **`RULE` vs `ANALYSIS`**：若句子陈述的是**不依赖本案当事人即可独立成立**的抽象标准、法条或普遍裁判规则（主语为「自然人」「网络服务提供者」「AI 合成声音」等一般主体），标 `RULE`；若将规则落到「本案中」「被告某公司」「LAION」「Claude」「DeepSeek」等具体对象上展开推理，标 `ANALYSIS`。
2. **`ANALYSIS` vs `CONCLUSION`**：若句子同时给出理由与结论，以句子的**主要语用功能**为准——重在展开推理链条（「……因为……」「由于……不构成……」「FINDING that ... in violation of ...」）标 `ANALYSIS`；独立承接上文推理作出终局定性（「因此，被告的行为不构成……」）或下达救济/罚款/简易判决主文标 `CONCLUSION`。
3. **`FACT` vs `CONCLUSION`（程序状态句）**：法院或监管机构作出的决定（「判决驳回」「驳回上诉，维持原判」「upheld the appeal」）标 `CONCLUSION`；当事人的程序动作或后续客观状态（「宣判后，双方均未提起上诉」「原告撤回部分诉请」「第 755 号决定已从官网暂时撤下」）标 `FACT`。
4. **`ISSUE` vs `FACT`（当事人主张）**：单方起诉或抗辩陈述（「原告认为被告侵权，故诉至法院」）归 `FACT`；只有当文书明确将某一法律争点提炼为本案裁判焦点，或明确划定不予审理/另案调查的争点范围时，才标 `ISSUE`。

---

## 三、双盲复核与评测流程

### 1. 生成复核表（可重复运行）

```powershell
python -I tools/export_review_sheet.py
```

在 `research/lamus_pilot/` 下产出 4 份文件：
- `blind_review_annotator_A.csv` / `blind_review_annotator_B.csv`：盲标表（隐藏模型初标，两位标注员各自填写 `human_role`）；
- `hybrid_audit_sheet.csv`：人机协同复核表（参照 LAMUS 3.2 节，核对 `draft_role` 并填写 `verified_role`，可直接测算 LLM 初标纠错率）；
- `pilot_corpus.jsonl`：带完整溯源字段的机读语料。

### 2. 计算双盲一致性（Cohen's $\kappa$）与 LLM 初标纠错率

```powershell
python -I tools/eval_arguments.py --a research/lamus_pilot/blind_review_annotator_A.csv --col-a human_role --b research/lamus_pilot/blind_review_annotator_B.csv --col-b human_role --by-jurisdiction
```

```powershell
python -I tools/eval_arguments.py --a research/lamus_pilot/hybrid_audit_sheet.csv --col-a verified_role --b research/lamus_pilot/hybrid_audit_sheet.csv --col-b draft_role --by-jurisdiction
```

仲裁定稿后，将最终标签写回 `data/arguments/ARG-*.json` 并将 `annotation_mode` 升级为 `DOUBLE_BLIND_ADJUDICATED`，重新运行 `python -I tools/build.py`。
