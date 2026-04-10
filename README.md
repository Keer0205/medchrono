# MedChronology AI 🏥

**Medical Records Chronology Builder** — upload multiple medical PDFs and extract a sorted timeline of events with source document and page citations.

Built for personal injury law firms and legal professionals who spend hours manually sorting medical records into chronologies.

---

## What it does

1. **Upload** — drag in any number of medical PDFs (GP letters, hospital discharge summaries, specialist reports, test results)
2. **Extract** — AI reads every page and identifies dated medical events
3. **Chronology** — events are sorted oldest → newest with source doc + page number citations
4. **Export** — download as CSV or JSON for further use

### Example output

| Date | Event | Source | Page | Confidence |
|------|-------|--------|------|------------|
| 2022-11-03 | Emergency PCI following ST-elevation MI | hospital_letter.pdf | 2 | high |
| 2022-11-22 | Echocardiogram — EF 45% | discharge_summary.pdf | 1 | high |
| 2022-12-10 | Commenced Bisoprolol 2.5mg and Ramipril 5mg | gp_letter.pdf | 3 | high |
| 2023-01-02 | Ramipril increased to 10mg following BP review | gp_letter.pdf | 3 | medium |

---

## Architecture

```
Uploaded PDFs
    │
    ▼
pypdf (page-by-page text extraction)
    │
    ▼
OpenAI GPT-4o-mini (event extraction per page)
    │  Extracts: date, event, detail, confidence
    │
    ▼
Deduplication (remove near-duplicates across docs)
    │
    ▼
Sorted chronological timeline
    │
    ▼
Streamlit UI (cards / table / JSON export)
```

**Key design decisions:**
- Page-by-page extraction (not whole-document) → precise page citations
- GPT-4o-mini chosen for cost efficiency (~£0.001 per page)
- Confidence scoring: high/medium/low based on date specificity
- Deduplication handles the same event appearing across multiple docs

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/yourusername/medchrono
cd medchrono
pip install -r requirements.txt
```

### 2. Add your OpenAI API key

```bash
mkdir -p .streamlit
echo 'OPENAI_API_KEY = "sk-..."' > .streamlit/secrets.toml
```

Never commit `secrets.toml` — it's in `.gitignore`.

### 3. Run

```bash
streamlit run app.py
```

### 4. Test without PDFs

```bash
export OPENAI_API_KEY=sk-...
python test_extractor.py
```

---

## Deploying to Streamlit Cloud

1. Push to GitHub (secrets.toml is gitignored — do NOT push it)
2. Go to share.streamlit.io → New app → select your repo
3. In **Secrets** settings, paste: `OPENAI_API_KEY = "sk-..."`
4. Deploy

---

## Cost estimate

| Documents | Pages | Approx cost |
|-----------|-------|-------------|
| 1 GP letter | 2 pages | ~£0.001 |
| 5 documents | 20 pages | ~£0.01 |
| 50 documents | 200 pages | ~£0.10 |

GPT-4o-mini is used for extraction — very low cost. A full medical bundle of 200 pages costs under £0.15.

---

## Limitations

- Text-based PDFs only — scanned images need OCR pre-processing
- Handwritten notes not supported in current version
- Dates in unusual formats may have lower confidence
- Always verify the output against original source documents
- Not a substitute for professional legal or medical review

## Next steps (roadmap)

- [ ] OCR support for scanned PDFs (Tesseract or Azure OCR)
- [ ] Handwritten note support
- [ ] Export to Word document with formatted chronology table
- [ ] Highlight conflicting dates across documents
- [ ] Streamlit login for multi-user clinic/firm access

---

## Related projects

- **ClinicOps Copilot** — same RAG architecture, applied to aesthetic clinic documents
- **Contract Clause Risk Checker** — coming soon

---

*Built by Keerthana | Legal AI portfolio project*
