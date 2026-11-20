/* Viewer for the AI governance database. No dependencies, no network.
   Every string from the dataset reaches the page through text nodes only,
   because excerpts are third-party text and must never be parsed as HTML. */
(function () {
  "use strict";

  var DB = JSON.parse(document.getElementById("data").textContent);
  var view = document.getElementById("view");

  var NAV = [
    ["issues", "争点", function () { return DB.issues.length; }],
    ["obligations", "义务", function () { return DB.obligations.length; }],
    ["instruments", "法规", function () { return DB.instruments.length; }],
    ["cases", "案例", function () { return DB.cases.length; }],
    ["leads", "线索", function () { return DB.leads.length; }],
    ["sources", "来源", function () { return DB.sources.length; }],
    ["about", "口径", function () { return ""; }]
  ];

  function byId(list) {
    var map = {};
    list.forEach(function (item) { map[item.id] = item; });
    return map;
  }
  var INSTRUMENT = byId(DB.instruments);
  var CASE = byId(DB.cases);
  var ISSUE = byId(DB.issues);
  var SOURCE = byId(DB.sources);
  var OBLIGATION = byId(DB.obligations);

  function seal(level) { return h("span", { class: "seal " + level, title: VERIFICATION_HELP[level] || "" }, VERIFICATION[level] || level); }
  function tag(text, cls) { return h("span", { class: "tag" + (cls ? " " + cls : "") }, text); }
  function jur(code) { return tag(code, "jur"); }
  function facts(rows) {
    var dl = h("dl", { class: "facts" });
    rows.forEach(function (row) {
      if (row[1] === null || row[1] === undefined || row[1] === "") { return; }
      append(dl, [h("dt", null, row[0]), h("dd", null, row[1])]);
    });
    return dl;
  }
  function sourceLine(sourceId) {
    var source = SOURCE[sourceId];
    if (!source) { return sourceId; }
    return [source.publisher, source.official ? "" : "（转载）", "，取于 " + source.fetched_at + " · ", link("sources", sourceId)];
  }
  function splitRef(ref) {
    var cut = ref.indexOf("#");
    return { instrument: ref.slice(0, cut), label: ref.slice(cut + 1) };
  }
  function refRoute(ref) {
    var parts = splitRef(ref);
    return "instrument/" + parts.instrument + "/" + encodeURIComponent(parts.label);
  }
  function refLabel(ref) {
    var parts = splitRef(ref);
    var instrument = INSTRUMENT[parts.instrument];
    return (instrument ? instrument.short_title : parts.instrument) + " " + parts.label;
  }
  function finality(value) { return value === true ? "已生效 / 终局" : value === false ? "未终局" : "未核实"; }
  /* True when a source was matched to the case by the editor, not by caption or number. */
  function linked(item) { return Object.keys(item.scope_links || {}).length > 0; }
  function caseTags(item) {
    return h("div", { class: "tags" }, jur(item.jurisdiction), seal(item.verification),
      tag(STAGE[item.procedural_stage] || item.procedural_stage),
      h("span", { class: "reading", title: "脚本只核对原句出自本案；这两项是编者对原句的解读" }, "编者解读",
        tag(OUTCOME[item.outcome] || item.outcome, item.outcome === "PENDING" || item.outcome === "UNVERIFIED" ? "warn" : ""),
        tag(finality(item.is_final), item.is_final === true ? "" : "warn")));
  }
  function caseCard(item) {
    return link("case/" + item.id, [
      h("h3", null, item.short_name), caseTags(item),
      h("p", { class: "meta" }, [item.forum, item.case_numbers.length ? " · " + item.case_numbers.join("、") + (linked(item) ? "（编者对应）" : "") : " · 案号未载", item.decided_at ? " · " + item.decided_at : ""])
    ], "card");
  }
  function instrumentCard(item) {
    return link("instrument/" + item.id, [
      h("h3", null, item.short_title),
      h("div", { class: "tags" }, jur(item.jurisdiction), seal(item.verification), tag(STATUS[item.status] || item.status, item.status === "IN_FORCE" ? "ok" : "warn"),
        tag(item.complete ? "全文 " + item.provisions.length + " 条" : item.provisions.length ? "节选 " + item.provisions.length + " 条" : "仅元数据", item.complete ? "" : "warn")),
      h("p", { class: "meta" }, [item.level, " · ", item.doc_number || "文号未载", item.published_at ? " · " + item.published_at : ""])
    ], "card");
  }
  function page(kicker, title, lede) {
    return [h("p", { class: "kicker" }, kicker), h("h1", null, title), lede ? h("p", { class: "lede" }, lede) : null];
  }
  function inOrder(list) {
    return list.slice().sort(function (a, b) {
      var ia = JUR_ORDER.indexOf(a.jurisdiction), ib = JUR_ORDER.indexOf(b.jurisdiction);
      return (ia < 0 ? 9 : ia) - (ib < 0 ? 9 : ib);
    });
  }

  /* ---- views ---- */

  function viewIssues() {
    var out = page("ISSUES", "争点", "每个争点下并排列出中国、欧盟、美国各自的条文和案例。库内没有材料的法域照实留白。");
    DB.issues.forEach(function (issue) {
      var counts = issue.positions.map(function (position) {
        return tag(position.jurisdiction + " 条文 " + position.provisions.length + " · 案例 " + position.cases.length,
          position.provisions.length + position.cases.length ? "" : "warn");
      });
      out.push(link("issue/" + issue.id, [h("h3", null, issue.title), h("p", null, issue.question), h("div", { class: "tags" }, counts)], "card"));
    });
    return out;
  }

  function viewIssue(id) {
    var issue = ISSUE[id];
    if (!issue) { return notFound(); }
    var out = page("ISSUE", issue.title, issue.question);
    if (issue.editor_note) { out.push(h("p", { class: "note" }, "编者注：" + issue.editor_note)); }
    var matrix = h("div", { class: "matrix" });
    issue.positions.forEach(function (position) {
      var blank = !position.provisions.length && !position.cases.length;
      var provisions = h("ul", { class: "reflist" }, position.provisions.map(function (ref) {
        return h("li", null, h("b", null, "条文"), link(refRoute(ref), refLabel(ref)));
      }));
      var cases = h("ul", { class: "reflist" }, position.cases.map(function (caseId) {
        var item = CASE[caseId];
        return h("li", null, h("b", null, "案例"), link("case/" + caseId, item.short_name), " ", seal(item.verification));
      }));
      append(matrix, h("section", { class: blank ? "blank" : "" },
        h("h3", null, position.jurisdiction + " · " + (JUR[position.jurisdiction] || "")),
        h("p", null, position.summary), provisions, cases));
    });
    out.push(matrix);
    out.push(h("p", { class: "meta" }, "各栏的概述是编者撰写的，不是引文；所依据的条文和案例见各栏下方链接。"));
    return out;
  }

  /* One obligation, as a table row. The paraphrase and the verified quote are
     always printed together, so a reader can check the one against the other. */
  function obligationCells(item, withInstrument) {
    var inst = INSTRUMENT[item.instrument_id] || {};
    var target = refRoute(item.instrument_id + "#" + item.provision);
    return [
      h("td", null, withInstrument
        ? link(target, (inst.short_title || item.instrument_id) + " " + item.provision)
        : link(target, item.provision)),
      h("td", null, tag(MODALITY[item.modality] || item.modality, item.modality === "MUST_NOT" ? "warn" : "ok"),
        " ", tag(OBL_KIND[item.kind] || item.kind)),
      h("td", null, h("div", null, item.duty_text), h("div", { class: "mono" }, "“" + item.quote + "”")),
      h("td", null, item.subject.map(function (s) { return SUBJECT[s] || s; }).join("、")),
      h("td", null, item.extraterritorial ? tag("域外效力", "warn") : "—")
    ];
  }

  function obligationTable(items, withInstrument) {
    if (!items.length) { return h("p", { class: "empty" }, "库内尚无这一层的记录。"); }
    var body = h("tbody");
    items.forEach(function (item) { append(body, h("tr", null, obligationCells(item, withInstrument))); });
    return h("table", null, h("thead", null, h("tr", null,
      h("th", null, withInstrument ? "法规与条文" : "条文"),
      h("th", null, "型态与类别"), h("th", null, "义务"), h("th", null, "主体"), h("th", null, "域外"))), body);
  }

  function viewObligations() {
    var out = page("OBLIGATIONS", "义务",
      "每条义务是从一条条文里切出的原句，逐字核对过；概括是编者写的，原句永远印在旁边。");
    out.push(h("p", { class: "note" },
      "义务不会比它所在的条文更可靠：条文的条号与正文已与快照逐字比对，义务是从那条条文里再切一刀。概括与原句并排，读者一眼就能看出概括有没有走样。"));
    out.push(obligationTable(DB.obligations, true));
    return out;
  }

  function viewObligation(id) {
    var item = OBLIGATION[id];
    if (!item) { return notFound(); }
    var inst = INSTRUMENT[item.instrument_id] || {};
    var provision = (inst.provisions || []).filter(function (p) { return p.no === item.provision; })[0];
    var out = page("OBLIGATION · " + item.instrument_id, item.duty_text);
    out.push(h("div", { class: "tags" },
      tag(MODALITY[item.modality] || item.modality, item.modality === "MUST_NOT" ? "warn" : "ok"),
      tag(OBL_KIND[item.kind] || item.kind),
      seal(item.verification),
      item.extraterritorial ? tag("域外效力", "warn") : null));
    out.push(facts([
      ["所在条文", link(refRoute(item.instrument_id + "#" + item.provision), (inst.short_title || item.instrument_id) + " " + item.provision)],
      ["义务主体", item.subject.map(function (s) { return SUBJECT[s] || s; }).join("、")],
      ["触发情形", item.trigger || null],
      ["例外", item.exception || null],
      ["罚则", item.penalty || null],
      ["域外依据", item.extraterritorial_basis || null]
    ]));
    out.push(h("h2", null, "所引原句"));
    out.push(h("blockquote", { lang: inst.language || null }, item.quote));
    out.push(h("p", { class: "meta" }, "这句原句必须逐字出现在下列条文中，构建时由脚本核对；对不上，构建即失败。"));
    if (provision) {
      out.push(h("h2", null, "所在条文全文"));
      out.push(h("article", { class: "prov", lang: inst.language || null },
        h("h3", null, provision.no, provision.heading ? h("small", null, provision.heading) : null),
        h("p", null, provision.text)));
    }
    out.push(h("p", { class: "meta" }, "义务的“概括”是编者撰写的，不是原文；“原句”和条文才是。"));
    return out;
  }

  function viewInstruments() {
    var out = page("INSTRUMENTS", "法规", "条文一律取自快照，逐字比对后入库。“全文”指条号连续无缺；“节选”和“仅元数据”都不是全文。");
    out.push(h("div", { class: "grid" }, inOrder(DB.instruments).map(instrumentCard)));
    return out;
  }

  /* A derived date is never shown as if the source stated it. */
  function dateCell(item, field, empty) {
    var rule = (item.derived_dates || {})[field];
    if (!item[field]) { return empty; }
    if (!rule) { return item[field]; }
    return item[field] + "（推算：" + (META[rule.from] || rule.from) + "后第 " + rule.plus_days + " 日；原文只写了规则，没有直接写这个日期）";
  }

  function usesOf(ref) {
    var cases = DB.cases.filter(function (item) {
      return item.legal_anchors.some(function (anchor) { return anchor.provision === ref; });
    });
    return cases.map(function (item) { return link("case/" + item.id, item.short_name, "tag"); });
  }

  function viewInstrument(id, label) {
    var item = INSTRUMENT[id];
    if (!item) { return notFound(); }
    var related = (item.amends || []).map(function (other) { return ["修订了 ", link("instrument/" + other, INSTRUMENT[other].short_title)]; })
      .concat((item.amended_by || []).map(function (other) { return ["已被修订：", link("instrument/" + other, INSTRUMENT[other].short_title)]; }));
    var out = page("INSTRUMENT · " + item.jurisdiction, item.title);
    out.push(h("div", { class: "tags" }, seal(item.verification), tag(STATUS[item.status] || item.status, item.status === "IN_FORCE" ? "ok" : "warn"), tag(TYPE[item.instrument_type] || item.instrument_type)));
    if (item.status_note) { out.push(h("p", { class: "note" }, item.status_note)); }
    out.push(facts([
      ["发布机关", item.issuer ? item.issuer.split("、").join(item.language === "en" ? "; " : "、") : "快照未载"],
      ["文号", item.doc_number || "快照未载"], ["效力层级", item.level],
      ["发布 / 签署", dateCell(item, "published_at", "快照未载")],
      ["施行", dateCell(item, "effective_at", "原文未载或未核")],
      ["关联", related.length ? related : null],
      ["收录范围", item.complete ? "全文，共 " + item.provisions.length + " 条" : item.provisions.length ? "节选 " + item.provisions.length + " 条" : "仅登记元数据，未拆条"],
      ["来源", item.source_ids.map(function (sourceId) { return h("div", null, sourceLine(sourceId)); })],
      ["原文地址", item.source_ids.map(function (sourceId) { return SOURCE[sourceId] ? h("div", null, external(SOURCE[sourceId].url)) : null; })],
      ["核验", VERIFICATION_HELP[item.verification]]
    ]));
    var metaFields = Object.keys(item.meta_evidence || {});
    if (metaFields.length) { out.push(h("h2", null, "字段出处")); }
    metaFields.forEach(function (field) {
      out.push(h("div", { class: "ev" }, h("b", null, META[field] || field), "“" + item.meta_evidence[field] + "”"));
    });
    out.push(h("p", { class: "meta" }, "标题、文号、发布机关、日期和条文由脚本对照快照核对；效力层级、类型和状态是编者的分类。"));
    var mine = DB.obligations.filter(function (item2) { return item2.instrument_id === id; });
    if (mine.length) {
      out.push(h("h2", null, "本法规的义务（" + mine.length + "）"));
      out.push(h("p", { class: "meta" }, "从下列条文中切出的原句，逐字核对过；“义务”一栏是编者概括。"));
      out.push(obligationTable(mine, false));
    }
    if (item.provisions.length) { out.push(h("h2", null, "条文")); }
    var division = null;
    var target = null;
    item.provisions.forEach(function (provision) {
      if (provision.division && provision.division !== division) {
        division = provision.division;
        out.push(h("p", { class: "division" }, division));
      }
      var uses = usesOf(id + "#" + provision.no);
      var node = h("article", { class: "prov" + (provision.no === label ? " hit" : ""), lang: item.language },
        h("h3", null, provision.no, provision.heading ? h("small", null, provision.heading) : null),
        h("p", null, provision.text),
        uses.length ? h("div", { class: "tags" }, h("span", { class: "meta" }, "关联案例"), uses) : null);
      if (provision.no === label) { target = node; }
      out.push(node);
    });
    if (target) { setTimeout(function () { target.scrollIntoView({ block: "start" }); }, 0); }
    return out;
  }

  function viewCases() {
    var out = page("CASES", "案例", "案名、审理机关、审级、案号、裁判日期由脚本对照本案原文核对。“结果”和“是否终局”是编者对原句的解读，卡片上圈在“编者解读”里。来源没有写的，一律标“未载”或“未核实”。");
    out.push(h("div", { class: "grid" }, inOrder(DB.cases).map(caseCard)));
    return out;
  }

  function viewCase(id) {
    var item = CASE[id];
    if (!item) { return notFound(); }
    var out = page("CASE · " + item.jurisdiction, item.short_name, item.caption);
    out.push(caseTags(item));
    out.push(h("p", { class: "meta" }, VERIFICATION_HELP[item.verification] + "。"));
    if (item.outcome_note) { out.push(h("p", { class: "note" }, item.outcome_note)); }
    out.push(facts([
      ["审理机关", item.forum],
      ["案号", item.case_numbers.length ? item.case_numbers.join("、") + (linked(item) ? "（与本案的对应系编者比对，见“字段出处”）" : "") : "来源未载"],
      ["裁判日期", item.decided_at || "来源未载"], ["AI 的角色", item.ai_roles.map(function (role) { return ROLE[role] || role; }).join("、")],
      ["争点", item.issues.map(function (issue, i) { return [i ? "、" : "", link("issue/" + issue, ISSUE[issue].title)]; })],
      ["来源标题", item.source_title ? item.source_title.text : null]
    ]));

    if (item.history.length) {
      out.push(h("h2", null, "审级"));
      item.history.forEach(function (step) {
        out.push(h("div", { class: "ev" }, h("b", null, (STAGE[step.stage] || step.stage) + " · " + step.forum + " · " + (step.decided_at || "")), "“" + step.result.quote + "”"));
      });
    }

    out.push(h("h2", null, "原文摘录"));
    item.excerpts.forEach(function (excerpt) {
      out.push(h("blockquote", { lang: item.jurisdiction === "US" ? "en" : null }, excerpt.text,
        h("footer", null, (EXCERPT[excerpt.kind] || excerpt.kind) + " · ", sourceLine(excerpt.source_id))));
    });

    out.push(h("h2", null, "关联条文"));
    if (!item.legal_anchors.length) { out.push(h("p", { class: "empty" }, "暂无。原因见下方备注。")); }
    item.legal_anchors.forEach(function (anchor) {
      out.push(h("div", { class: "card" },
        h("h3", null, link(refRoute(anchor.provision), refLabel(anchor.provision))),
        h("div", { class: "tags" }, tag(BASIS[anchor.basis] || anchor.basis, anchor.basis === "CITED_IN_SOURCE" ? "ok" : "warn")),
        anchor.quote ? h("p", null, "“" + anchor.quote + "”") : null,
        anchor.note ? h("p", { class: "meta" }, anchor.note) : null));
    });
    if (item.legal_anchors.some(function (anchor) { return anchor.basis === "EDITORIAL"; })) {
      out.push(h("p", { class: "meta" }, "“编者关联”表示来源没有写明本案适用了该条文，是编者按主题对应上的，不能当作裁判依据引用。"));
    }

    out.push(h("h2", null, "字段出处"));
    out.push(h("p", { class: "meta" }, "每条出处都只在本案自己的段落里核对，不借用同一页面上其他案件的句子。“结果”和“是否终局”是编者对下列原句的解读。"));
    Object.keys(item.field_evidence).forEach(function (field) {
      item.field_evidence[field].forEach(function (evidence) {
        out.push(h("div", { class: "ev" }, h("b", null, [(FIELD[field] || field) + (evidence.page_level ? "（取自页面导语）" : "") + " · ", sourceLine(evidence.source_id)]), "“" + evidence.quote + "”"));
      });
    });
    Object.keys(item.scope_links || {}).forEach(function (sourceId) {
      out.push(h("p", { class: "note" }, "编者对应 · " + sourceId + "：" + item.scope_links[sourceId]));
    });
    item.also_reported_in.forEach(function (other) {
      out.push(h("p", { class: "note" }, "编者注 · 另见 " + other.source_id + (other.locator ? " " + other.locator : "") + "：" + other.note));
    });
    if (item.notes) { out.push(h("h2", null, "备注"), h("p", null, item.notes)); }
    out.push(h("p", { class: "meta" }, "线索来源：" + (item.discovered_via || "")));
    return out;
  }

  function leadNode(lead) {
    return h("div", { class: "lead" }, h("div", { class: "band" }, "未核验线索 · 不是库内记录"),
      h("div", { class: "body" },
        h("h3", null, lead.title),
        h("div", { class: "tags" }, jur(lead.jurisdiction), tag(lead.type === "CASE" ? "案例线索" : "法规线索")),
        h("p", null, lead.claim),
        h("p", { class: "meta" }, "见于：" + lead.seen_in.join("；")),
        h("p", { class: "meta" }, "下一步：" + lead.next_step)));
  }
  function viewLeads() {
    var out = page("LEADS", "线索", "这里是从二手材料和第三方数据库看到、还没有取到原文的条目。其中的案号、日期、金额和结论都没有核对过，不能引用。");
    DB.leads.forEach(function (lead) { out.push(leadNode(lead)); });
    return out;
  }

  function viewSources() {
    var out = page("SOURCES", "来源快照", "库内每一处引文都指向下面某一份快照。SHA-256 是取回当时文件的指纹，用来确认本地文件没有被改动。");
    var body = h("tbody");
    DB.sources.forEach(function (source) {
      append(body, h("tr", null,
        h("td", null, h("span", { class: "mono" }, source.id), h("br"), source.publisher, source.note ? h("div", { class: "meta" }, source.note) : null),
        h("td", null, KIND[source.kind] || source.kind, h("br"), tag(source.official ? "发布机关页面" : "转载页", source.official ? "ok" : "warn")),
        h("td", null, source.fetched_at),
        h("td", null, external(source.url, "打开原址"), h("div", { class: "mono" }, source.sha256.slice(0, 16) + "…"))));
    });
    out.push(h("table", null, h("thead", null, h("tr", null, h("th", null, "快照"), h("th", null, "类型"), h("th", null, "取回日期"), h("th", null, "地址与指纹"))), body));
    return out;
  }

  function figure(value, label) { return h("div", null, h("b", null, String(value)), h("span", null, label)); }
  function viewAbout() {
    var s = DB.stats;
    var out = page("SCOPE", "口径", "这个库收什么、没收什么、每个数字怎么来的。");
    out.push(h("p", { class: "note" }, "覆盖范围：试点只做“生成式 AI × 中国、欧盟、美国”。它不是全球库，也不是三地的全量库。数据截至 " + DB.built_at + "。"));
    out.push(h("div", { class: "figures" }, figure(s.instruments, "部法规"), figure(s.provisions, "条条文"), figure(s.obligations, "条义务"),
      figure(s.cases, "件案例"), figure(s.issues, "个争点"), figure(s.leads_open, "条待核线索"), figure(s.sources, "份快照")));
    out.push(h("p", { class: "meta" }, "以上数字由构建脚本从数据文件清点得出。"));

    out.push(h("h2", null, "核验等级"));
    Object.keys(VERIFICATION).forEach(function (level) {
      out.push(h("p", null, seal(level), " " + VERIFICATION_HELP[level] + "。"));
    });
    out.push(h("p", null, "等级不是人工填写的，由构建脚本按记录所引快照的性质算出。任何一处引文与快照对不上，构建即失败。"));
    out.push(h("p", null, "案例 " + s.cases + " 件中：" + Object.keys(s.cases_by_verification).map(function (level) { return (VERIFICATION[level] || level) + " " + s.cases_by_verification[level] + " 件"; }).join("，") +
      "；取得裁判文书（判决书或裁定书）的 " + s.cases_with_judgment + " 件；载有案号的 " + s.cases_with_case_number + " 件，其中 " + s.cases_with_editorial_link + " 件的案号与本案的对应是编者比对的；标为终局的 " + s.cases_final + " 件。"));

    out.push(h("h2", null, "案例与条文的关联"));
    out.push(h("p", null, "共 " + s.anchors + " 处关联，其中“来源明文援引” " + (s.anchors_by_basis.CITED_IN_SOURCE || 0) + " 处，“编者关联” " + (s.anchors_by_basis.EDITORIAL || 0) + " 处；" + s.cases_without_anchor + " 件案例暂无关联条文。"));
    out.push(h("p", null, "“来源明文援引”只在取得判决书全文的案例上才有。其余中国案例取自法院发布的典型案例稿，稿中通常不写条文序号；美国案例适用的版权法条文尚未入库。"));

    out.push(h("h2", null, "义务层与涉外标记"));
    out.push(h("p", null, "库内 " + s.obligations + " 条义务，其中“应当” " + (s.obligations_by_modality.MUST || 0) +
      " 条、“不得” " + (s.obligations_by_modality.MUST_NOT || 0) + " 条，标注域外效力的 " + s.obligations_extraterritorial + " 条。"));
    out.push(h("p", null, "每条义务的“原句”必须逐字出现在它所指向的条文里，而那条条文早已与快照逐字比对；所以义务的证据链是：原句 ⊆ 条文 ⊆ 快照。义务不会比它读的那条法更可靠。"));
    out.push(h("p", null, "涉外标记是编者的分类，脚本不核对：" + Object.keys(s.instruments_by_foreign_related).map(function (key) {
      return (FOREIGN[key] || key) + " " + s.instruments_by_foreign_related[key] + " 部";
    }).join("，" ) + "。"));
    out.push(h("p", null, "争点层多了两项：每栏声明所依据材料的性质（规范性文件、个案裁判、库内无材料等），整个争点声明各栏是否可比，不可比时要写明理由。"));

    out.push(h("h2", null, "已知缺口"));
    out.push(h("ul", null,
      h("li", null, "欧盟《人工智能法》收的是 2024 年公报原始文本。2026/1744 号修订条例只登记了元数据，对各条的修改尚未逐条标注。"),
      h("li", null, "欧盟部分没有案例。"),
      h("li", null, "中国案例的摘录来自法院案例稿，不是判决书。" + (s.cases_by_verification.PARSED || 0) + " 件取自新闻客户端转载的法院发布稿，所以只到“转载核对”。"),
      h("li", null, "法规“现行”状态只依据原文所载的施行日期，没有逐部核查此后是否被修订或废止。"),
      h("li", null, "条文之间的引用关系（例如标识办法援引深度合成规定）尚未结构化。")));

    var agora = DB.reference.agora;
    if (agora) {
      out.push(h("h2", null, "对照：AGORA 数据集"));
      out.push(h("p", null, "AGORA（乔治城大学 CSET）是目前公开可下载的最大的 AI 治理文件库。下表是对其 " + agora.version + " 版（" + agora.published + "，" + agora.license + "）整包实测的结果，不是其官网的自述。"));
      var body = h("tbody");
      Object.keys(agora.by_jurisdiction).forEach(function (name) {
        append(body, h("tr", null, h("td", null, name), h("td", { class: "num" }, String(agora.by_jurisdiction[name])), h("td", { class: "num" }, (100 * agora.by_jurisdiction[name] / agora.documents).toFixed(1) + "%")));
      });
      out.push(h("table", null, h("thead", null, h("tr", null, h("th", null, "法域"), h("th", null, "文件数"), h("th", null, "占比"))), body));
      out.push(h("p", null, "共 " + agora.documents + " 件文件。中国 " + agora.china_documents + " 件，其“文件链接”指向 .gov.cn 域名的有 " + agora.china_links_on_gov_cn + " 件，其余指向英译本或研究机构页面。该数据集不收案例。"));
      out.push(h("p", { class: "meta" }, "本库只把 AGORA 当线索，条文一律另取中文官方原文。AGORA 为非商业许可，其数据不随本库分发。"));
    }
    return out;
  }

  /* ---- search ---- */

  function viewSearch(query) {
    var out = page("SEARCH", "检索：" + query);
    var key = fold(query);
    if (key.length < 2) { out.push(h("p", { class: "empty" }, "请输入至少两个字。")); return out; }
    var hits = 0;
    function section(title, nodes) {
      if (!nodes.length) { return; }
      hits += nodes.length;
      out.push(h("h2", null, title + "（" + nodes.length + "）"));
      nodes.slice(0, 40).forEach(function (node) { out.push(node); });
      if (nodes.length > 40) { out.push(h("p", { class: "meta" }, "只显示前 40 条。")); }
    }
    var provisions = [];
    DB.instruments.forEach(function (item) {
      item.provisions.forEach(function (provision) {
        if (fold(provision.text + (provision.heading || "") + provision.no).indexOf(key) < 0) { return; }
        provisions.push(link(refRoute(item.id + "#" + provision.no), [h("h3", null, item.short_title + " " + provision.no), snippet(provision.text, query)], "card"));
      });
    });
    section("条文", provisions);
    section("案例", DB.cases.filter(function (item) {
      var text = item.caption + item.short_name + item.forum + item.case_numbers.join("") + item.excerpts.map(function (e) { return e.text; }).join("");
      return fold(text).indexOf(key) >= 0;
    }).map(function (item) {
      var hit = item.excerpts.filter(function (e) { return fold(e.text).indexOf(key) >= 0; })[0];
      return link("case/" + item.id, [h("h3", null, item.short_name), caseTags(item), hit ? snippet(hit.text, query) : null], "card");
    }));
    section("争点", DB.issues.filter(function (issue) {
      return fold(issue.title + issue.question + issue.positions.map(function (p) { return p.summary; }).join("")).indexOf(key) >= 0;
    }).map(function (issue) { return link("issue/" + issue.id, [h("h3", null, issue.title), h("p", null, issue.question)], "card"); }));
    section("未核验线索", DB.leads.filter(function (lead) { return fold(lead.title + lead.claim).indexOf(key) >= 0; }).map(leadNode));
    if (!hits) { out.push(h("p", { class: "empty" }, "库内没有匹配的内容。这只说明本库没有收，不说明不存在。")); }
    return out;
  }

  function notFound() { return page("404", "没有这条记录", "地址可能有误，或者该记录尚未入库。"); }

  /* ---- routing ---- */

  function route() {
    var parts = location.hash.replace(/^#\/?/, "").split("/");
    var name = parts[0] || "issues";
    var arg = safeDecode(parts[1] || "");
    var views = {
      issues: viewIssues, issue: function () { return viewIssue(arg); },
      obligations: viewObligations, obligation: function () { return viewObligation(arg); },
      instruments: viewInstruments, instrument: function () { return viewInstrument(arg, safeDecode(parts.slice(2).join("/"))); },
      cases: viewCases, "case": function () { return viewCase(arg); },
      leads: viewLeads, sources: viewSources, about: viewAbout,
      search: function () { return viewSearch(safeDecode(parts.slice(1).join("/"))); }
    };
    var render = Object.prototype.hasOwnProperty.call(views, name) ? views[name] : notFound;
    view.textContent = "";
    append(view, render());
    var section = { issue: "issues", obligation: "obligations", instrument: "instruments", "case": "cases" }[name] || name;
    Array.prototype.forEach.call(document.querySelectorAll("#nav a"), function (item) {
      if (item.getAttribute("data-section") === section) { item.setAttribute("aria-current", "page"); } else { item.removeAttribute("aria-current"); }
    });
    if (!(name === "instrument" && parts[2])) { window.scrollTo(0, 0); }
    document.title = (view.querySelector("h1") ? view.querySelector("h1").textContent + " · " : "") + "涉外法治与人工智能治理对应库";
  }

  NAV.forEach(function (entry) {
    append(document.getElementById("nav"), h("a", { href: "#/" + entry[0], "data-section": entry[0] }, entry[1], h("span", null, String(entry[2]()))));
  });
  append(document.getElementById("rail-foot"), ["试点范围：涉外数据 · AI 治理", h("br"), "中国 · 欧盟 · 美国", h("br"), "数据截至 " + DB.built_at]);
  append(document.getElementById("top-note"), ["红色“已核验”章：引文与发布机关的原文逐字一致。", link("about", "口径说明")]);
  append(document.getElementById("foot"), "本库供研究检索使用，不构成法律意见。摘录为原文节录，概述为编者撰写；引用前请打开原址核对。结构版本 " + DB.schema + "。");
  document.getElementById("search-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var query = document.getElementById("q").value.trim();
    if (query) { location.hash = "#/search/" + encodeURIComponent(query); }
  });
  window.addEventListener("hashchange", route);
  route();
})();
