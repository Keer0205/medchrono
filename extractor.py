"""
extractor.py
============
Core extraction engine for MedChronology AI.

Stack:
  - PyMuPDF (fitz)   — accurate PDF text extraction
  - dateparser       — normalises messy date strings
  - OpenAI gpt-4o-mini — structured event extraction
  - logging          — production-grade debug trail

Features:
  - Page-level extraction → precise page citations
  - Confidence scoring (high / medium / low)
  - Deduplication across multiple documents
  - dateparser post-processing for edge-case dates
"""

import json
import logging
import re
from datetime import datetime

import dateparser
import fitz  # PyMuPDF
from openai import OpenAI

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("medchrono.extractor")

# ── System prompt ──────────────────────────────────────────────────────────────
EXTRACTION_SYSTEM = """You are a medical records analyst extracting clinical events.

Extract every discrete medical event that has a date (exact or approximate).

Medical events include:
- Diagnoses, test results, procedures, operations
- Hospital admissions and discharges
- GP or specialist appointments
- Prescriptions started, stopped, or changed
- Symptom onset dates
- Referrals made or received
- Investigations ordered or reported

For each event return a JSON array. Each object must have:
  "date_raw"   : exact date string as written in the text (e.g. "14th January 2023")
  "event"      : concise description, max 20 words, plain English
  "detail"     : one extra sentence of context if helpful, else empty string ""
  "confidence" : "high" if exact date, "medium" if month+year only, "low" if year only or inferred

Rules:
- Return ONLY valid JSON array. No markdown, no explanation, no preamble.
- If no medical events found, return []
- Do NOT invent dates. If truly undated, skip the event.
- Preserve medical terminology accurately.
"""

# ── PDF extraction ─────────────────────────────────────────────────────────────
def extract_pages(pdf_bytes: bytes, source_name: str) -> list[dict]:
    """
    Extract text from each page using PyMuPDF.
    Returns list of {page, text} dicts — only non-empty pages.
    """
    pages = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        log.info("Opened '%s' — %d page(s)", source_name, len(doc))
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if len(text) > 40:  # skip near-empty pages
                pages.append({"page": i, "text": text})
        doc.close()
    except Exception as exc:
        log.error("Failed to open '%s': %s", source_name, exc)
    return pages


# ── Date normalisation ─────────────────────────────────────────────────────────
DATEPARSER_SETTINGS = {
    "PREFER_DAY_OF_MONTH": "first",
    "DATE_ORDER": "DMY",                 # UK date order: day/month/year
    "PREFER_LOCALE_DATE_ORDER": True,    # must be bool
    "RETURN_AS_TIMEZONE_AWARE": False,
    "STRICT_PARSING": False,
}

def normalise_date(date_raw: str) -> tuple[str | None, str]:
    """
    Convert a raw date string to ISO YYYY-MM-DD using dateparser.
    Returns (iso_string_or_None, confidence_level).

    confidence:
      high   — day + month + year resolved
      medium — month + year only
      low    — year only or parse failed
    """
    if not date_raw or not date_raw.strip():
        return None, "low"

    cleaned = date_raw.strip()

    # Try dateparser first
    parsed = dateparser.parse(cleaned, settings=DATEPARSER_SETTINGS)

    if parsed:
        iso = parsed.strftime("%Y-%m-%d")
        # Assess confidence from raw string
        has_day   = bool(re.search(r"\b\d{1,2}(st|nd|rd|th)?\b", cleaned))
        has_month = bool(re.search(
            r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
            r"|january|february|march|april|june|july|august"
            r"|september|october|november|december)\b",
            cleaned, re.I
        ))
        has_year  = bool(re.search(r"\b(19|20)\d{2}\b", cleaned))

        if has_day and (has_month or has_year):
            return iso, "high"
        elif has_month and has_year:
            return iso, "medium"
        else:
            return iso, "low"

    # Fallback — year-only
    year_match = re.search(r"\b(19|20)\d{2}\b", cleaned)
    if year_match:
        return f"{year_match.group()}-01-01", "low"

    return None, "low"


# ── OpenAI event extraction ────────────────────────────────────────────────────
def extract_events_from_page(
    page_text: str,
    page_num: int,
    source_name: str,
) -> list[dict]:
    """
    Send one page to GPT-4o-mini and extract structured medical events.
    Each event gets source + page citation attached.
    """
    if len(page_text.strip()) < 40:
        return []

    client = OpenAI()

    try:
        log.debug("Extracting events from '%s' p.%d", source_name, page_num)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user",   "content": page_text[:4000]},
            ],
            temperature=0,
            max_tokens=1500,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if GPT wraps in ```json
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$",          "", raw).strip()

        events = json.loads(raw)
        if not isinstance(events, list):
            log.warning("Non-list response from GPT on '%s' p.%d", source_name, page_num)
            return []

        enriched = []
        for ev in events:
            date_raw = ev.get("date_raw", "")
            iso_date, conf_from_parser = normalise_date(date_raw)

            # Use GPT confidence if it's stricter than dateparser's verdict
            gpt_conf = ev.get("confidence", "medium")
            # Take the lower (more cautious) of the two
            conf_rank = {"high": 2, "medium": 1, "low": 0}
            final_conf = (
                gpt_conf
                if conf_rank.get(gpt_conf, 1) <= conf_rank.get(conf_from_parser, 1)
                else conf_from_parser
            )

            enriched.append({
                "date":       iso_date,
                "date_raw":   date_raw,
                "event":      ev.get("event", "").strip(),
                "detail":     ev.get("detail", "").strip(),
                "confidence": final_conf,
                "source":     source_name,
                "page":       page_num,
            })

        log.info(
            "  '%s' p.%d → %d event(s)", source_name, page_num, len(enriched)
        )
        return enriched

    except json.JSONDecodeError as exc:
        log.error("JSON parse failed for '%s' p.%d: %s", source_name, page_num, exc)
        return []
    except Exception as exc:
        log.error("API error for '%s' p.%d: %s", source_name, page_num, exc)
        return []


# ── Full pipeline ──────────────────────────────────────────────────────────────
def process_pdfs(uploaded_files) -> list[dict]:
    """
    Accept a list of Streamlit UploadedFile objects.
    Returns all extracted events, sorted chronologically.
    """
    all_events: list[dict] = []

    for uf in uploaded_files:
        source_name = uf.name
        pdf_bytes   = uf.read()
        uf.seek(0)  # reset so Streamlit can re-read if needed

        log.info("Processing: %s (%d bytes)", source_name, len(pdf_bytes))
        pages = extract_pages(pdf_bytes, source_name)

        if not pages:
            log.warning("No extractable text in '%s' — may be scanned.", source_name)

        for p in pages:
            events = extract_events_from_page(p["text"], p["page"], source_name)
            all_events.extend(events)

    log.info("Total events before dedup: %d", len(all_events))
    unique = deduplicate(all_events)
    log.info("Total events after dedup:  %d", len(unique))

    return sort_events(unique)


# ── Sorting ────────────────────────────────────────────────────────────────────
def sort_events(events: list[dict]) -> list[dict]:
    """Sort events chronologically. Null dates go to the end."""
    def key(ev):
        d = ev.get("date")
        if d:
            try:
                return (0, datetime.fromisoformat(d))
            except ValueError:
                pass
        return (1, datetime.max)

    return sorted(events, key=key)


# ── Deduplication ──────────────────────────────────────────────────────────────
def deduplicate(events: list[dict]) -> list[dict]:
    """
    Remove near-duplicate events (same date, very similar description).
    Keeps the first occurrence — which has the source/page citation.
    """
    seen: list[tuple[str, str]] = []
    unique: list[dict] = []

    for ev in events:
        date = ev.get("date") or ""
        desc = ev.get("event", "").lower().strip()

        is_dup = False
        for s_date, s_desc in seen:
            if date == s_date and date:  # only dedup within same date
                words_a = set(desc.split())
                words_b = set(s_desc.split())
                if words_a and words_b:
                    overlap = len(words_a & words_b) / max(len(words_a), len(words_b))
                    if overlap >= 0.75:
                        is_dup = True
                        log.debug("Dedup removed: '%s' on %s", desc[:40], date)
                        break

        if not is_dup:
            seen.append((date, desc))
            unique.append(ev)

    return unique
