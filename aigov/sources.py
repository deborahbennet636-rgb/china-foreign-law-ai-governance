"""Source snapshots: fetch a page once, keep the bytes, record the hash.

Every quote in the database points at a snapshot kept under ``data/raw``.
The manifest ``data/sources.json`` says where each snapshot came from, when
it was taken and what its SHA-256 is. Text is only ever read from a file
whose bytes still match the registered hash.

A PDF gets a stored text layer next to it, with a hash of its own, so that
matching does not depend on which version of the PDF library is installed.
"""
import functools
import hashlib
import io
import json
import logging
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from .config import PATHS, SOURCE_KINDS
from .textnorm import html_to_text

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
TIMEOUT_SECONDS = 60
PDF_MAGIC = b"%PDF"

SourceEntry = Dict[str, Any]
Manifest = Dict[str, SourceEntry]


def load_manifest(path: Path = PATHS.sources) -> Manifest:
    """Read the source manifest, or return an empty one if none exists yet."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(manifest: Manifest, path: Path = PATHS.sources) -> None:
    """Write the manifest with stable key order so diffs stay readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {key: manifest[key] for key in sorted(manifest)}
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_of(payload: bytes) -> str:
    """Hex SHA-256 of a snapshot."""
    return hashlib.sha256(payload).hexdigest()


def download(url: str, proxy: Optional[str] = None) -> bytes:
    """Fetch one URL.

    Args:
        url: Address of the page or file.
        proxy: Optional ``http://host:port`` proxy. Domestic official sites
            are fetched directly; pass a proxy only for sites that need one.

    Returns:
        The response body.

    Raises:
        urllib.error.URLError: When the request fails.
    """
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})]
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.URLError:
        logger.error("download failed: %s", url)
        raise


def pdf_to_text(payload: bytes) -> Dict[str, str]:
    """Extract the text layer of a PDF.

    Returns:
        The text, one page after another, and the name and version of the
        library that produced it.

    Raises:
        RuntimeError: When ``pypdf`` is not installed.
    """
    try:
        import pypdf  # deferred: needed only when a PDF is first snapshotted
    except ImportError as error:
        raise RuntimeError("snapshotting a PDF needs pypdf: pip install pypdf") from error
    reader = pypdf.PdfReader(io.BytesIO(payload))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return {"text": text, "extractor": f"pypdf {pypdf.__version__}"}


def text_layer_fields(pdf_file: str, payload: bytes) -> SourceEntry:
    """Store the text layer of a PDF and return the manifest fields for it.

    Args:
        pdf_file: Path of the PDF relative to ``data``.
        payload: The bytes of the PDF.

    Returns:
        ``text_file``, ``text_sha256`` and ``extractor``.
    """
    extracted = pdf_to_text(payload)
    text_bytes = extracted["text"].encode("utf-8")
    text_file = pdf_file + ".txt"
    (PATHS.data / text_file).write_bytes(text_bytes)
    return {"text_file": text_file, "text_sha256": sha256_of(text_bytes), "extractor": extracted["extractor"]}


def snapshot(
    source_id: str,
    url: str,
    publisher: str,
    kind: str,
    official: bool,
    proxy: Optional[str] = None,
    suffix: str = ".html",
    note: str = "",
) -> SourceEntry:
    """Download a source, store it under ``data/raw`` and register it.

    An existing snapshot is never replaced: if the id is already in the
    manifest the stored entry is returned untouched, and a file already on
    disk under that name is never overwritten. Re-fetching a source is a
    deliberate act, because records verified against the old bytes would
    otherwise change meaning.

    Args:
        source_id: Stable identifier, e.g. ``SRC-CN-SPC-511101``.
        url: Where the source lives.
        publisher: Who published the page.
        kind: One of ``SOURCE_KINDS``.
        official: True when the publisher is the issuing authority itself.
        proxy: Optional proxy for this request.
        suffix: File extension for the stored snapshot.
        note: Free-text remark kept in the manifest.

    Returns:
        The manifest entry for the source.

    Raises:
        ValueError: When ``kind`` is unknown, the suffix does not fit the
            content, or an unregistered file is already in the way.
    """
    if kind not in SOURCE_KINDS:
        raise ValueError(f"unknown source kind: {kind}")
    manifest = load_manifest()
    if source_id in manifest:
        logger.info("already snapshotted, keeping existing bytes: %s", source_id)
        return manifest[source_id]
    target = PATHS.raw / f"{source_id}{suffix}"
    if target.exists():
        raise ValueError(f"{target.name} exists but is not registered; move it away first")

    payload = download(url, proxy)
    if payload.startswith(PDF_MAGIC) != (suffix == ".pdf"):
        raise ValueError(f"{source_id}: content and suffix {suffix!r} disagree about being a PDF")
    PATHS.raw.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    entry: SourceEntry = {
        "id": source_id,
        "url": url,
        "publisher": publisher,
        "kind": kind,
        "official": official,
        "fetched_at": date.today().isoformat(),
        "file": f"raw/{target.name}",
        "sha256": sha256_of(payload),
        "bytes": len(payload),
        "via": "proxy" if proxy else "direct",
    }
    if suffix == ".pdf":
        entry.update(text_layer_fields(entry["file"], payload))
    if note:
        entry["note"] = note
    manifest[source_id] = entry
    save_manifest(manifest)
    logger.info("snapshotted %s (%d bytes)", source_id, len(payload))
    return entry


def register_file(source_id: str, path: Path, url: str, publisher: str, kind: str, official: bool,
                  note: str = "") -> SourceEntry:
    """Register a file that was captured outside this module.

    Pages behind a login (subscription databases reached over a campus
    network) cannot be fetched by ``snapshot``. They are saved from a
    logged-in browser and registered here, under the same rules: a source id
    is never reused and a stored file is never overwritten.

    Args:
        source_id: Stable identifier of the snapshot.
        path: The captured file; its bytes are copied into ``data/raw``.
        url: Address the content was captured from.
        publisher: Who published the page.
        kind: One of ``SOURCE_KINDS``.
        official: True when the publisher is the issuing authority itself.
        note: Free-text remark kept in the manifest.

    Returns:
        The manifest entry for the source.

    Raises:
        ValueError: When the kind is unknown, the id is taken, the target
            exists, or the file is empty.
    """
    if kind not in SOURCE_KINDS:
        raise ValueError(f"unknown source kind: {kind}")
    manifest = load_manifest()
    if source_id in manifest:
        raise ValueError(f"{source_id} is already registered")
    payload = path.read_bytes()
    if not payload.strip():
        raise ValueError(f"{path.name} is empty")
    target = PATHS.raw / f"{source_id}{path.suffix}"
    if target.exists():
        raise ValueError(f"{target.name} exists but is not registered; move it away first")
    PATHS.raw.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    entry: SourceEntry = {
        "id": source_id, "url": url, "publisher": publisher, "kind": kind, "official": official,
        "fetched_at": date.today().isoformat(), "file": f"raw/{target.name}",
        "sha256": sha256_of(payload), "bytes": len(payload), "via": "browser",
    }
    if note:
        entry["note"] = note
    manifest[source_id] = entry
    save_manifest(manifest)
    logger.info("registered %s (%d bytes)", source_id, len(payload))
    return entry


def decode(payload: bytes) -> str:
    """Decode a page, trying UTF-8 first and GB18030 for older Chinese sites."""
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("gb18030", errors="replace")


@functools.lru_cache(maxsize=None)
def _text_of(file: str, sha256: str) -> str:
    """Return the text of one stored file after checking its hash.

    The cache is keyed by file and hash, so whatever it returns is the text
    of bytes that matched the registered hash when they were read.
    """
    payload = (PATHS.data / file).read_bytes()
    if sha256_of(payload) != sha256:
        raise ValueError(f"{file}: bytes on disk do not match the registered hash")
    if payload.startswith(PDF_MAGIC):
        raise ValueError(f"{file}: a PDF must be read through its stored text layer")
    raw = decode(payload)
    if file.endswith((".html", ".htm")):
        return html_to_text(raw)
    return raw


def read_text(entry: SourceEntry) -> str:
    """Return a snapshot as plain text with paragraph breaks kept.

    Raises:
        ValueError: When the file on disk no longer matches its hash, or a
            PDF has no stored text layer.
    """
    if "text_file" in entry:
        return _text_of(entry["text_file"], entry["text_sha256"])
    return _text_of(entry["file"], entry["sha256"])
