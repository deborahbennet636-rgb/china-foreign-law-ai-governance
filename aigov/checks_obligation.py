"""Checks on obligation records.

An obligation is one thing a provision requires, forbids or allows. It is an
editorial reading, so two fields are treated differently:

* ``quote`` is the provision's own words. It must occur verbatim inside the
  text of the provision it names, which itself was matched against a
  snapshot when the instrument was ingested. The chain is therefore
  ``quote`` ⊆ ``provision.text`` ⊆ snapshot, and an obligation can never be
  more certain than the provision it reads.
* ``duty`` and ``trigger`` are optional paraphrase. When ``duty`` is absent
  the quote itself stands as the obligation, so the default record is fully
  verified and a reader can always check a paraphrase against the quote
  printed next to it.

What is *not* checked: whether the editor picked the right category. That is
a judgement, and the viewer labels it as one.
"""
from typing import Any, Dict, List, Mapping, Optional, Set

from .config import MODALITIES, OBLIGATION_KINDS, OBLIGATION_SUBJECTS
from .evidence import long_enough
from .textnorm import normalize

Record = Dict[str, Any]

# A paraphrase is short. Anything longer is a second provision in disguise,
# and should have been quoted instead.
MAX_PARAPHRASE_CHARS = 300


def find_provision(instrument: Mapping[str, Any], label: str) -> Optional[Mapping[str, Any]]:
    """Return the provision of ``instrument`` whose label is ``label``."""
    for provision in instrument.get("provisions", []):
        if provision.get("no") == label:
            return provision
    return None


def quote_inside_provision(quote: str, provision_text: str) -> bool:
    """Tell whether ``quote`` occurs verbatim inside a provision's text.

    Whitespace and full-width variants are folded away, as everywhere else in
    this project; nothing else is.
    """
    needle = normalize(quote)
    return bool(needle) and needle in normalize(provision_text)


def _check_vocab(owner: str, record: Record) -> List[str]:
    """Check the controlled vocabularies of one obligation."""
    errors = []
    if record.get("kind") not in OBLIGATION_KINDS:
        errors.append(f"{owner}: unknown obligation kind {record.get('kind')!r}")
    if record.get("modality") not in MODALITIES:
        errors.append(f"{owner}: unknown modality {record.get('modality')!r}")
    subjects = record.get("subject") or []
    if not subjects:
        errors.append(f"{owner}: an obligation needs at least one subject")
    unknown = [item for item in subjects if item not in OBLIGATION_SUBJECTS]
    if unknown:
        errors.append(f"{owner}: unknown subject(s) {unknown}")
    for field in ("duty", "trigger", "exception", "penalty", "note"):
        value = record.get(field)
        if value is not None and len(normalize(str(value))) > MAX_PARAPHRASE_CHARS:
            errors.append(f"{owner}: {field} is longer than {MAX_PARAPHRASE_CHARS} characters; quote the provision instead")
    if record.get("extraterritorial") and not record.get("extraterritorial_basis"):
        errors.append(f"{owner}: extraterritorial is set but extraterritorial_basis is empty")
    return errors


def check_obligation(record: Record, by_id: Mapping[str, Record], refs: Set[str]) -> List[str]:
    """Check one obligation record.

    Args:
        record: The obligation record.
        by_id: Every instrument in the database, keyed by id.
        refs: Reference of every provision in the database.

    Returns:
        One message per problem found.
    """
    owner = record.get("id", "?")
    errors = _check_vocab(owner, record)

    instrument_id = record.get("instrument_id")
    instrument = by_id.get(instrument_id)
    if instrument is None:
        return errors + [f"{owner}: unknown instrument {instrument_id!r}"]

    label = record.get("provision")
    ref = f"{instrument_id}#{label}"
    if ref not in refs:
        return errors + [f"{owner}: {instrument_id} has no provision {label!r}"]
    provision = find_provision(instrument, label) or {}

    quote = record.get("quote", "")
    if not long_enough(quote):
        errors.append(f"{owner}: quote is too short to prove anything")
    elif not quote_inside_provision(quote, provision.get("text", "")):
        errors.append(f"{owner}: quote does not occur verbatim in {ref}")

    if record.get("duty") is not None and not normalize(str(record["duty"])):
        errors.append(f"{owner}: duty is given but empty; leave it out to let the quote stand")
    return errors


def effective_duty(record: Record) -> str:
    """Return what the obligation requires, as shown to a reader.

    The paraphrase when the editor wrote one, the verified quote otherwise.
    """
    return record.get("duty") or record.get("quote", "")
