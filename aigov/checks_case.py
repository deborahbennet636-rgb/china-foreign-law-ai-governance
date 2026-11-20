"""Checks on case records.

A court digest page holds several cases, and they share stock sentences
("the judgment has taken effect"). Every quote is therefore searched only
inside the block that belongs to the case: the ``scopes`` of a record name,
for each source it uses, the block of that source that is about this case.
A block counts as the case's own only if the case's caption or one of its
case numbers stands in it, so a spec cannot point a case at its neighbour.

What is checked mechanically: excerpts, caption, court name, case numbers,
decision dates, the procedural stage, the courts and dates of earlier
instances, and the provision named in a cited anchor. What is not:
``outcome`` and ``is_final`` are the editor's reading of the quoted
sentence, and the viewer marks them so.
"""
import re
from typing import Any, Dict, List, Mapping, Optional, Set

from .config import AI_ROLES, ANCHOR_BASIS, EXCERPT_KINDS, FORUM_TYPES, OUTCOMES, STAGES
from .evidence import SnapshotIndex, contains_name, long_enough, quote_states_date, states_token
from .textnorm import normalize

Record = Dict[str, Any]

# Only the court's name may be evidenced by the page as a whole, because a
# digest page names the publishing court once, above all its cases.
PAGE_LEVEL_FIELDS = frozenset({"forum"})
# Only a judgment is about a single case and may be used without a block.
# A judgment saved from a case-law database page is the exception: the page
# also carries the database's own panels (case history, related cases), so
# its manifest entry is flagged and the judgment text must be given as a block.
WHOLE_DOCUMENT_KINDS = frozenset({"JUDGMENT"})
MIN_FORUM_CHARS = 6
MIN_PARTY_CHARS = 4
PARTY_SEPARATOR = " v. "
CN_CASE_NUMBER = re.compile(r"（\d{4}）\S*?\d+号")
# Words by which a source shows which instance a decision belongs to.
STAGE_MARKERS = {
    "FIRST_INSTANCE": ("一审", "民初", "提起上诉", "均未上诉", "district court"),
    "APPEAL": ("二审", "民终", "court of appeals"),
}


def _quote_problem(record: Record, item: Mapping[str, Any], index: SnapshotIndex, field: str = "") -> Optional[str]:
    """Return why a ``{source_id, quote}`` item is not acceptable evidence."""
    scopes = record.get("scopes", {})
    source_id = item.get("source_id", "")
    quote = item.get("quote", "")
    if source_id not in scopes:
        return f"source {source_id!r} is not listed in the case's scopes"
    if not long_enough(quote):
        return f"quote is too short to prove anything: {quote!r}"
    page_level = bool(item.get("page_level"))
    if page_level and field not in PAGE_LEVEL_FIELDS:
        return "page-level evidence is allowed only for the court's name"
    if page_level and index.entry(source_id).get("all_cases_by") != record.get("forum"):
        return f"page-level evidence needs {source_id} to be registered as holding only this court's cases"
    if not index.found(source_id, quote, None if page_level else scopes[source_id]):
        return f"quote not found in the case's own block of {source_id}: {quote[:40]!r}"
    return None


def _caption_in(index: SnapshotIndex, source_id: str, scope: Optional[Mapping[str, str]], caption: str) -> bool:
    """Tell whether a block carries the case's caption.

    The caption must occur verbatim. A caption of the form "A v. B" is a
    citation convention that judgments do not print as such, so for it both
    party names must occur.
    """
    if long_enough(caption) and index.found(source_id, caption, scope, ignore_case=True):
        return True
    parties = caption.split(PARTY_SEPARATOR)
    return len(parties) == 2 and all(
        len(party) >= MIN_PARTY_CHARS and index.found(source_id, party, scope, ignore_case=True) for party in parties
    )


def _shows_stage(quote: str, stage: Any) -> bool:
    """Tell whether a quote carries a marker of the given procedural stage."""
    markers = STAGE_MARKERS.get(stage)
    if markers is None:
        return True
    flat = normalize(quote).casefold()
    return any(normalize(marker) in flat for marker in markers)


def _states_date(quotes: List[str], iso_date: str) -> bool:
    """Tell whether any quote states the date; a malformed date states nothing."""
    try:
        return any(quote_states_date(quote, iso_date) for quote in quotes)
    except ValueError:
        return False


def _check_enums(owner: str, record: Record, issue_ids: Set[str]) -> List[str]:
    errors = []
    for field, allowed in (("forum_type", FORUM_TYPES), ("procedural_stage", STAGES), ("outcome", OUTCOMES)):
        if record.get(field) not in allowed:
            errors.append(f"{owner}: unknown {field} {record.get(field)!r}")
    errors += [f"{owner}: unknown ai_role {role!r}" for role in record.get("ai_roles", []) if role not in AI_ROLES]
    errors += [f"{owner}: unknown issue {issue!r}" for issue in record.get("issues", []) if issue not in issue_ids]
    return errors


def _check_scopes(owner: str, record: Record, index: SnapshotIndex) -> List[str]:
    """Check that every scope is a block about this case.

    A block belongs to the case when it carries the case's caption, or a
    case number that also stands in a block already tied to the case. A
    block tied in neither way needs an entry in ``scope_links`` saying why
    the editor takes it to be the same case; the viewer shows that note, so
    an identification made by judgement is never presented as checked.
    """
    errors = []
    caption = record.get("caption") or ""
    links = record.get("scope_links", {})
    numbers = [number for number in record.get("case_numbers", []) if number]
    scopes: Dict[str, Any] = {}
    for source_id, scope in record.get("scopes", {}).items():
        if not index.has(source_id):
            errors.append(f"{owner}: scope source {source_id!r} is not registered")
            continue
        entry = index.entry(source_id)
        if scope is None and entry.get("kind") not in WHOLE_DOCUMENT_KINDS:
            errors.append(f"{owner}: {source_id} holds more than one case and needs a block")
        elif scope is None and entry.get("has_page_metadata"):
            errors.append(f"{owner}: {source_id} is a database page with panels of its own and needs a block")
        scopes[source_id] = scope

    tied = {source_id for source_id, scope in scopes.items() if _caption_in(index, source_id, scope, caption)}
    if not tied:
        errors.append(f"{owner}: caption does not occur verbatim in any of the case's blocks")
    pending = [source_id for source_id in scopes if source_id not in tied]
    progress = True
    while pending and progress:
        progress = False
        for source_id in list(pending):
            shares_number = any(
                index.found(source_id, number, scopes[source_id])
                and any(index.found(other, number, scopes[other]) for other in tied)
                for number in numbers
            )
            if shares_number or links.get(source_id):
                tied.add(source_id)
                pending.remove(source_id)
                progress = True
    errors += [
        f"{owner}: the block of {source_id} is tied to the case neither by caption, nor by a shared case number, nor by an editorial link"
        for source_id in pending
    ]
    errors += [f"{owner}: scope_links names {source_id!r}, which is not one of the case's scopes" for source_id in links if source_id not in scopes]
    return errors


def _check_texts(owner: str, record: Record, index: SnapshotIndex) -> List[str]:
    """Check the excerpts and the source title."""
    errors = []
    excerpts = record.get("excerpts", [])
    if not excerpts:
        errors.append(f"{owner}: a case needs at least one excerpt")
    for excerpt in excerpts:
        if excerpt.get("kind") not in EXCERPT_KINDS:
            errors.append(f"{owner}: unknown excerpt kind {excerpt.get('kind')!r}")
        problem = _quote_problem(record, {"source_id": excerpt.get("source_id"), "quote": excerpt.get("text", "")}, index)
        if problem:
            errors.append(f"{owner}: excerpt: {problem}")
    title = record.get("source_title")
    if title:
        problem = _quote_problem(record, {"source_id": title.get("source_id"), "quote": title.get("text", "")}, index)
        if problem:
            errors.append(f"{owner}: source_title: {problem}")
    return errors


def _check_fields(owner: str, record: Record, index: SnapshotIndex) -> List[str]:
    """Check each stated fact against the quotes given for it."""
    errors = []
    evidence: Dict[str, List[Record]] = record.get("field_evidence", {})
    for field, items in evidence.items():
        for item in items:
            problem = _quote_problem(record, item, index, field)
            if problem:
                errors.append(f"{owner}: evidence for {field}: {problem}")

    def quotes(field: str) -> List[str]:
        return [item.get("quote", "") for item in evidence.get(field, [])]

    forum = record.get("forum") or ""
    if not any(contains_name(quote, forum, MIN_FORUM_CHARS) for quote in quotes("forum")):
        errors.append(f"{owner}: forum {forum!r} is not named in full in its evidence")
    for number in record.get("case_numbers", []):
        well_formed = CN_CASE_NUMBER.fullmatch(number) if re.search(r"[^\x00-\x7f]", number) else number.startswith("No.")
        if not well_formed or not any(states_token(quote, number) for quote in quotes("case_numbers")):
            errors.append(f"{owner}: case number {number!r} is malformed or not stated in its evidence")
    decided = record.get("decided_at")
    if decided and not _states_date(quotes("decided_at"), decided):
        errors.append(f"{owner}: decided_at={decided} is not stated in its evidence")
    stage = record.get("procedural_stage")
    if not any(_shows_stage(quote, stage) for quote in quotes("procedural_stage")):
        errors.append(f"{owner}: procedural_stage {stage} is not shown by its evidence")
    if record.get("outcome") != "UNVERIFIED" and not quotes("outcome"):
        errors.append(f"{owner}: an outcome other than UNVERIFIED needs evidence")
    if record.get("is_final") is not None and not quotes("is_final"):
        errors.append(f"{owner}: is_final is set but has no evidence; use null when unknown")
    return errors


def _check_history(owner: str, record: Record, index: SnapshotIndex) -> List[str]:
    """Check each instance: its quote, court, date and stage.

    When a history is given, the record's own court, date and stage must be
    those of the last step, so the first-instance date cannot stand in for
    the appeal's.
    """
    errors = []
    history = record.get("history", [])
    for step in history:
        result = step.get("result", {})
        quote = result.get("quote", "")
        problem = _quote_problem(record, result, index)
        if problem:
            errors.append(f"{owner}: history step: {problem}")
        if not contains_name(quote, step.get("forum", ""), MIN_FORUM_CHARS):
            errors.append(f"{owner}: history court {step.get('forum')!r} is not named in its quote")
        if step.get("decided_at") and not _states_date([quote], step["decided_at"]):
            errors.append(f"{owner}: history date {step['decided_at']} is not stated in its quote")
        if step.get("stage") not in STAGES or not _shows_stage(quote, step.get("stage")):
            errors.append(f"{owner}: history stage {step.get('stage')!r} is not shown by its quote")
    if history:
        last = history[-1]
        for field, step_field in (("forum", "forum"), ("decided_at", "decided_at"), ("procedural_stage", "stage")):
            if record.get(field) != last.get(step_field):
                errors.append(f"{owner}: {field} must equal that of the last history step")
    return errors


def _check_anchor(owner: str, record: Record, anchor: Record, index: SnapshotIndex,
                  instruments: Mapping[str, Record], refs: Set[str]) -> List[str]:
    """Check one link from a case to a provision."""
    ref = anchor.get("provision", "")
    if ref not in refs:
        return [f"{owner}: anchor points at unknown provision {ref!r}"]
    basis = anchor.get("basis")
    if basis not in ANCHOR_BASIS:
        return [f"{owner}: unknown anchor basis {basis!r}"]
    if basis == "EDITORIAL":
        return [] if anchor.get("note") else [f"{owner}: an EDITORIAL anchor must explain itself in a note"]
    problem = _quote_problem(record, anchor, index)
    if problem:
        return [f"{owner}: anchor citation: {problem}"]
    instrument_id, label = ref.split("#", 1)
    instrument = instruments[instrument_id]
    quote = anchor.get("quote", "")
    names = [instrument.get("short_title", ""), instrument.get("title", "")]
    # "§107." and "Sec. 2." end in the heading's full stop, which a citation
    # such as "§ 107(1)" does not repeat; the number itself must still match.
    token = label.rstrip(".")
    if not states_token(quote, token) or not any(contains_name(quote, name, 2) for name in names):
        return [f"{owner}: cited anchor quote does not name {instrument.get('short_title')} {label}"]
    return []


def check_case(record: Record, index: SnapshotIndex, instruments: Mapping[str, Record], refs: Set[str],
               issue_ids: Set[str]) -> List[str]:
    """Check one case record.

    Args:
        record: The case record.
        index: Snapshot index.
        instruments: Instrument records keyed by id.
        refs: References of every provision in the database.
        issue_ids: Ids of every issue.

    Returns:
        One message per problem found.
    """
    owner = record.get("id", "?")
    errors = _check_enums(owner, record, issue_ids)
    errors += _check_scopes(owner, record, index)
    errors += _check_texts(owner, record, index)
    errors += _check_fields(owner, record, index)
    errors += _check_history(owner, record, index)
    for anchor in record.get("legal_anchors", []):
        errors += _check_anchor(owner, record, anchor, index, instruments, refs)
    for other in record.get("also_reported_in", []):
        if not index.has(other.get("source_id", "")):
            errors.append(f"{owner}: also_reported_in names unregistered source {other.get('source_id')!r}")
    return errors


def sources_of_case(record: Record) -> List[str]:
    """List every snapshot a case rests on.

    Every quote of a case must come from a source listed in its scopes, so
    the scopes are the complete set.
    """
    return sorted(record.get("scopes", {}))
