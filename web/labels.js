/* Display labels for the coded values of the dataset. */
var JUR = { CN: "中国", EU: "欧盟", US: "美国" };
var JUR_ORDER = ["CN", "EU", "US"];
var VERIFICATION = { VERIFIED: "已核验", PARSED: "转载核对", PENDING: "待核" };
var VERIFICATION_HELP = {
  VERIFIED: "全部引文与发布机关自己的页面或文书快照逐字一致",
  PARSED: "全部引文与快照逐字一致，但至少一份快照是转载页，不是发布机关的页面",
  PENDING: "尚无快照"
};
var STATUS = { PROPOSED: "草案", ADOPTED: "已发布（施行情况未核）", IN_FORCE: "现行", AMENDED: "已被修订", REPEALED: "已废止", UNKNOWN: "状态不明" };
var TYPE = { AI_SPECIFIC: "AI 专门规范", GENERAL_LAW_CITED: "一般法（仅收被案例适用的条文）", RELATED_LAW: "涉外 / 相邻领域法" };
var FOREIGN = { FOREIGN_SPECIFIC: "涉外专门法", FOREIGN_CLAUSE: "含涉外或域外条款", DOMESTIC: "无涉外条款", UNKNOWN: "未判定" };
var NATURE = {
  NORMATIVE: "规范性文件", JUDICIAL_INTERPRETATION: "司法解释", CASE: "个案裁判",
  GUIDANCE: "监管指南 / 案例发布", STANDARD: "标准", UNOFFICIAL: "只有二手材料", NONE: "库内无材料"
};
var OBL_KIND = {
  DATA_SOURCE: "数据来源", SECURITY_ASSESSMENT: "安全评估", FILING: "备案登记", LABELING: "标识",
  DISCLOSURE: "公开披露", CONSENT: "告知同意", LOCALIZATION: "本地化", RECORD_KEEPING: "记录留存",
  PROHIBITION: "禁止性义务", REPORTING: "报送报告", LICENSE: "许可准入", CERTIFICATION: "认证",
  CONTRACT: "合同约定", PROTECTION: "保护义务", COOPERATION: "配合监管", OTHER: "其他"
};
var MODALITY = { MUST: "应当", MUST_NOT: "不得", MAY: "可以", MAY_NOT: "可以不", ENCOURAGED: "鼓励" };
var SUBJECT = {
  PROVIDER: "服务提供者", USER: "用户", PLATFORM: "平台经营者", OPERATOR: "运营者",
  DATA_HANDLER: "数据处理者", STATE_AGENCY: "国家机关", IMPORTER: "进口经营者", EXPORTER: "出口经营者",
  ORGANIZATION: "组织 / 企业", CITIZEN: "公民个人", OTHER: "其他"
};
var DIRECTION = { INBOUND_TO_CN: "境外对华措施", OUTBOUND_FROM_CN: "中国对外措施" };
var MEASURE = {
  SANCTION: "制裁", EXPORT_CONTROL: "出口管制", INVESTMENT_SCREENING: "投资审查",
  DATA_RESTRICTION: "数据限制", ENTITY_LIST: "实体清单", BLOCKING: "阻断",
  TARIFF: "关税", IMPORT_BAN: "进口禁令", OTHER: "其他"
};
var STAGE = { FILED: "已立案", FIRST_INSTANCE: "一审", APPEAL: "二审 / 上诉审", RETRIAL: "再审", ENFORCEMENT_DECISION: "执法决定" };
var OUTCOME = {
  CLAIMANT_PREVAILED: "原告胜诉", CLAIMANT_PARTLY_PREVAILED: "原告部分胜诉", RESPONDENT_PREVAILED: "被告胜诉",
  SETTLED: "和解", DISMISSED: "驳回 / 撤诉", PENDING: "未决", UNVERIFIED: "结果未核验"
};
var ROLE = { TRAINING: "模型训练", OUTPUT: "生成内容", DEPLOYMENT: "服务提供", USE_BY_PARTY: "当事人使用 AI", DETECTION: "AI 内容识别" };
var EXCERPT = { facts: "案情", holding: "裁判", significance: "意义" };
var FIELD = { forum: "审理机关", caption: "案名", procedural_stage: "审级", case_numbers: "案号", decided_at: "裁判日期", outcome: "结果", is_final: "是否终局" };
var META = {
  doc_number: "文号", issuer: "发布机关", published_at: "发布 / 签署日期", effective_at: "施行日期", short_title: "简称",
  expected_provisions: "条数", adopted_at: "通过日期", entry_into_force: "生效规则", general_application: "一般适用日期", fr_doc: "公报编号", title: "标题"
};
var BASIS = { CITED_IN_SOURCE: "来源明文援引", EDITORIAL: "编者关联" };
var KIND = { OFFICIAL_TEXT: "规范文本", JUDGMENT: "裁判文书", OFFICIAL_DIGEST: "法院案例稿", SECONDARY: "二手材料" };
