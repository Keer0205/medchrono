"""
MedChronology AI — Final Version
=================================
Upload medical PDFs → extract sorted timeline → export for legal use.

Run:   streamlit run app.py
Needs: OPENAI_API_KEY in .streamlit/secrets.toml
"""

import json
import logging
import os
from datetime import datetime
from itertools import groupby

import pandas as pd
import streamlit as st

from extractor import process_pdfs, sort_events

log = logging.getLogger("medchrono.app")

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MedChronology AI",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── API key ────────────────────────────────────────────────────────────────────
api_key = st.secrets.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
if api_key:
    os.environ["OPENAI_API_KEY"] = api_key

# ── Styles ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Timeline card */
  .ev-card {
    border-left: 4px solid #64748b;
    background: #f8fafc;
    border-radius: 0 8px 8px 0;
    padding: 10px 16px;
    margin-bottom: 8px;
  }
  .ev-card.high   { border-left-color: #22c55e; }
  .ev-card.medium { border-left-color: #f59e0b; }
  .ev-card.low    { border-left-color: #ef4444; }

  .ev-date   { font-size:.75rem; font-weight:600; letter-spacing:.06em;
               text-transform:uppercase; color:#475569; margin-bottom:3px; }
  .ev-title  { font-size:.95rem; font-weight:600; color:#0f172a; margin:2px 0; }
  .ev-detail { font-size:.82rem; color:#64748b; margin-bottom:6px; }
  .ev-badge  { display:inline-block; font-size:.7rem; font-weight:500;
               padding:2px 8px; border-radius:999px; margin-right:4px; }
  .badge-src  { background:#e2e8f0; color:#475569; }
  .badge-high   { background:#dcfce7; color:#166534; }
  .badge-medium { background:#fef9c3; color:#854d0e; }
  .badge-low    { background:#fee2e2; color:#991b1b; }

  /* Year divider */
  .year-marker {
    font-size:.8rem; font-weight:700; color:#94a3b8;
    letter-spacing:.1em; text-transform:uppercase;
    border-bottom:1px solid #e2e8f0;
    padding-bottom:4px; margin:1.2rem 0 .6rem;
  }

  /* Disclaimer */
  .disclaimer {
    background:#fff7ed; border:1px solid #fed7aa;
    border-radius:8px; padding:10px 14px;
    font-size:.78rem; color:#9a3412; margin-bottom:1rem;
  }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏥 MedChronology AI")
    st.markdown("*Medical records → sorted timeline*")
    st.divider()

    if not api_key:
        st.error("⚠️ No OpenAI API key.\nAdd OPENAI_API_KEY to Streamlit Secrets.")

    uploaded_files = st.file_uploader(
        "Upload medical PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        help="GP letters, hospital discharge summaries, specialist reports, test results",
    )

    st.divider()

    # Filters — shown only once results exist
    filters = {}
    if "events" in st.session_state and st.session_state.events:
        events_all = st.session_state.events
        sources = sorted(set(e["source"] for e in events_all))

        st.markdown("### Filters")
        filters["sources"] = st.multiselect("Documents", sources, default=sources)
        filters["confidence"] = st.multiselect(
            "Date confidence",
            ["high", "medium", "low"],
            default=["high", "medium", "low"],
            help="high = exact date  |  medium = month+year  |  low = year only",
        )
        filters["show_undated"] = st.checkbox("Show undated events", value=True)

        year_vals = sorted(set(
            datetime.fromisoformat(e["date"]).year
            for e in events_all if e.get("date")
        ))
        if len(year_vals) > 1:
            filters["year_range"] = st.slider(
                "Year range",
                min_value=min(year_vals),
                max_value=max(year_vals),
                value=(min(year_vals), max(year_vals)),
            )
        else:
            filters["year_range"] = (min(year_vals), max(year_vals)) if year_vals else (1900, 2100)

    st.session_state.filters = filters

    st.divider()
    st.markdown(
        "<div style='font-size:.72rem;color:#94a3b8'>"
        "PyMuPDF · dateparser · OpenAI gpt-4o-mini<br>"
        "Always verify outputs against source documents."
        "</div>",
        unsafe_allow_html=True,
    )


# ── Header ─────────────────────────────────────────────────────────────────────
st.title("Medical Records Chronology Builder")
st.markdown(
    "Upload medical PDFs and generate a **sorted chronology** "
    "with source document and page citations."
)

st.markdown("""
<div class="disclaimer">
⚠️ <strong>For informational use only.</strong>
This tool extracts and organises information from uploaded documents.
It does not provide medical or legal advice.
Always verify outputs against the original source documents.
</div>
""", unsafe_allow_html=True)

if not uploaded_files:
    c1, c2, c3 = st.columns(3)
    with c1:
        st.info("**Step 1 — Upload**\nOne or more medical PDFs in the sidebar, including GP letters, hospital summaries, test results, and discharge notes.")
    with c2:
        st.info("**Step 2 — Extract**\nAI reviews the uploaded records and extracts dated medical events. Each event is linked to its source document and page.")
    with c3:
        st.info("**Step 3 — Review & Export**\nA sorted chronology is generated with source document and page citations. Download as CSV.")
    st.stop()


# ── Run button ─────────────────────────────────────────────────────────────────
col_btn, col_info = st.columns([2, 5])
with col_btn:
    run = st.button(
        "⚡ Build Chronology",
        type="primary",
        disabled=not api_key,
        use_container_width=True,
    )
with col_info:
    names = ", ".join(f.name for f in uploaded_files[:3])
    if len(uploaded_files) > 3:
        names += f" … +{len(uploaded_files)-3} more"
    st.markdown(f"**{len(uploaded_files)} document(s):** {names}")

if run:
    st.session_state.pop("events", None)

    prog  = st.progress(0, text="Starting…")
    status = st.empty()
    all_ev = []

    for i, f in enumerate(uploaded_files):
        status.info(f"📄 Processing **{f.name}** ({i+1}/{len(uploaded_files)})…")
        prog.progress(i / len(uploaded_files), text=f"Extracting from {f.name}…")
        evs = process_pdfs([f])
        all_ev.extend(evs)
        log.info("Done with %s — running total: %d events", f.name, len(all_ev))

    prog.progress(1.0, text="Done.")
    prog.empty()
    status.empty()

    st.session_state.events = all_ev

    if all_ev:
        st.success(
            f"✅ Extracted **{len(all_ev)} events** "
            f"from **{len(uploaded_files)} document(s)**."
        )
        log.info("Extraction complete. %d events stored.", len(all_ev))
    else:
        st.warning(
            "No dated events found. "
            "Check PDFs are text-based (not scanned images). "
            "Scanned PDFs need OCR pre-processing."
        )


# ── Results ────────────────────────────────────────────────────────────────────
if not st.session_state.get("events"):
    st.stop()

events_all = st.session_state.events
f = st.session_state.get("filters", {})

# Apply filters
def apply_filters(evs, f):
    out = []
    yr_min, yr_max = f.get("year_range", (1900, 2100))
    for ev in evs:
        if f.get("sources") and ev["source"] not in f["sources"]:
            continue
        if f.get("confidence") and ev["confidence"] not in f["confidence"]:
            continue
        d = ev.get("date")
        if not d:
            if not f.get("show_undated", True):
                continue
        else:
            try:
                yr = datetime.fromisoformat(d).year
                if not (yr_min <= yr <= yr_max):
                    continue
            except ValueError:
                pass
        out.append(ev)
    return out

events = apply_filters(events_all, f)

# ── Metrics ────────────────────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total events",   len(events))
m2.metric("Documents",      len(set(e["source"] for e in events)))
dated   = [e for e in events if e.get("date")]
m3.metric("Dated events",   len(dated))
high    = sum(1 for e in events if e.get("confidence") == "high")
pct     = round(high / len(events) * 100) if events else 0
m4.metric("High confidence", f"{pct}%")
low_conf = sum(1 for e in events if e.get("confidence") == "low")
m5.metric("Low confidence",  low_conf,
          delta=f"-{low_conf} verify" if low_conf else None,
          delta_color="inverse")

st.divider()

# ── View toggle ────────────────────────────────────────────────────────────────
view = st.radio(
    "View",
    ["📋 Timeline", "📊 Table", "⬇️ Export"],
    horizontal=True,
    label_visibility="collapsed",
)

# ─── Timeline view ─────────────────────────────────────────────────────────────
if view == "📋 Timeline":

    def year_key(ev):
        d = ev.get("date")
        if d:
            try:
                return str(datetime.fromisoformat(d).year)
            except ValueError:
                pass
        return "Undated"

    sorted_ev = sort_events(events)
    for year, grp in groupby(sorted_ev, key=year_key):
        st.markdown(f'<div class="year-marker">{year}</div>', unsafe_allow_html=True)
        for ev in grp:
            conf     = ev.get("confidence", "medium")
            date_raw = ev.get("date_raw") or ev.get("date") or "Unknown date"
            event    = ev.get("event", "")
            detail   = ev.get("detail", "")
            source   = ev.get("source", "")
            page     = ev.get("page", "?")

            detail_html = (
                f'<div class="ev-detail">{detail}</div>' if detail else ""
            )
            st.markdown(f"""
            <div class="ev-card {conf}">
              <div class="ev-date">📅 {date_raw}</div>
              <div class="ev-title">{event}</div>
              {detail_html}
              <span class="ev-badge badge-src">📄 {source} · p.{page}</span>
              <span class="ev-badge badge-{conf}">{conf} confidence</span>
            </div>
            """, unsafe_allow_html=True)

# ─── Table view ────────────────────────────────────────────────────────────────
elif view == "📊 Table":
    rows = [
        {
            "Date (raw)":  ev.get("date_raw", ""),
            "Date (ISO)":  ev.get("date", ""),
            "Event":       ev.get("event", ""),
            "Detail":      ev.get("detail", ""),
            "Confidence":  ev.get("confidence", ""),
            "Source":      ev.get("source", ""),
            "Page":        ev.get("page", ""),
        }
        for ev in events
    ]
    df = pd.DataFrame(rows)

    def colour_conf(val):
        colours = {"high": "background-color:#dcfce7",
                   "medium": "background-color:#fef9c3",
                   "low": "background-color:#fee2e2"}
        return colours.get(val, "")

    styled = df.style.map(colour_conf, subset=["Confidence"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

# ─── Export view ───────────────────────────────────────────────────────────────
elif view == "⬇️ Export":
    rows = [
        {
            "Date (raw)":  ev.get("date_raw", ""),
            "Date (ISO)":  ev.get("date", ""),
            "Event":       ev.get("event", ""),
            "Detail":      ev.get("detail", ""),
            "Confidence":  ev.get("confidence", ""),
            "Source":      ev.get("source", ""),
            "Page":        ev.get("page", ""),
        }
        for ev in events
    ]
    df = pd.DataFrame(rows)

    ec1, ec2, ec3 = st.columns(3)

    # CSV
    with ec1:
        st.download_button(
            "⬇️ Download CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="medical_chronology.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # JSON
    with ec2:
        st.download_button(
            "⬇️ Download JSON",
            data=json.dumps(events, indent=2, default=str),
            file_name="medical_chronology.json",
            mime="application/json",
            use_container_width=True,
        )

    # Word-ready plain text chronology
    with ec3:
        lines = ["MEDICAL CHRONOLOGY\n", "=" * 50 + "\n"]
        current_year = None
        for ev in sort_events(events):
            yr = ev.get("date", "")[:4] if ev.get("date") else "Undated"
            if yr != current_year:
                lines.append(f"\n--- {yr} ---\n")
                current_year = yr
            lines.append(
                f"{ev.get('date_raw','Unknown date')}\n"
                f"  {ev.get('event','')}\n"
                + (f"  {ev.get('detail','')}\n" if ev.get("detail") else "")
                + f"  [Source: {ev.get('source','')} p.{ev.get('page','')} "
                  f"| {ev.get('confidence','')} confidence]\n\n"
            )
        txt = "".join(lines)
        st.download_button(
            "⬇️ Download TXT (Word-ready)",
            data=txt.encode("utf-8"),
            file_name="medical_chronology.txt",
            mime="text/plain",
            use_container_width=True,
        )

    st.markdown("---")
    st.markdown("**Preview**")
    st.dataframe(df, use_container_width=True, hide_index=True)
