# ✂️ NOTAM-cropper
**Make NOTAMs great again.**

NOTAM-cropper is a robust, deterministic Python application designed to automatically filter, classify, and reflow LIDO Pilot Briefings. Built specifically for iPad Electronic Flight Bags (EFBs), it strips out irrelevant data, categorizes essential NOTAMs into clear operational tags, and outputs a clean, highly readable PDF.

## 🚀 Key Features

* **Intelligent PDF Reflowing:** Parses dense LIDO briefing PDFs, strips out repeating headers/pagination, and reflows the text into a clean, monospaced layout.
* **Live FAA Database Integration:** Utilizes a stealthy Headless Firefox engine (Playwright) to query the official FAA NOTAM database, bypassing WAF restrictions to accurately pull Q-Codes and categorize NOTAMs.
* **Hybrid Fallback Engine:** For foreign NOTAMs and AIP Supplements not found in the FAA database, a bespoke fallback engine categorizes the NOTAM using LIDO's native boundary headers combined with operational keyword overrides (e.g., overriding an `AIRPORT` header to `[NAV]` if the text contains "ILS" or "DVOR").
* **Cloud-Synced Memory:** Integrates directly with Google Sheets to maintain a global state. It caches Known NOTAMs for lightning-fast processing, dynamically learns False Positives, and syncs a custom Blacklist to instantly shred recurring irrelevant NOTAMs.
* **Zero-LLM Architecture:** 100% deterministic and locally processed. No AI hallucinations, no API costs, and strict, predictable tagging (`RWY`, `TWY`, `APN`, `NAV`, `OBS`, `LGT`, `AIR`).

## 🧠 How the Tagging Engine Works

When a new LIDO PDF is uploaded, the engine processes each NOTAM through a strict hierarchy:

1.  **The Cache (Fastest):** Checks the cloud-synced Blacklist and `Known_NOTAMs` database. If found, it tags it instantly.
2.  **The FAA Engine (Primary Data):** Fires a headless browser request to the FAA. It attempts a direct ID match, and if that fails, uses a 25-character text fingerprint to find the matching Q-Code.
3.  **The Hybrid Fallback (The Safety Net):** If the FAA returns nothing, it defaults to the preceding LIDO Boundary Header (e.g., `APPROACH PROCEDURE`), then scans the text for override keywords to ensure geographical headers don't mask operational hazards.
4.  **The Unknown Log:** Only if all else fails is it tagged `[UNKN]` and logged to Google Sheets for manual review.

## 🛠️ Tech Stack

* **Frontend:** Streamlit (Optimized for iPad / Local Network access)
* **PDF Manipulation:** PyMuPDF (`fitz`)
* **Web Scraping:** Playwright (Headless Firefox)
* **Data Handling:** Pandas, RegEx
* **Cloud Database:** Google Sheets API (`st-gsheets-connection`)

## ⚙️ Installation & Setup

**1. Clone the repository & setup virtual environment (Windows)**
```bash
git clone [https://github.com/DukeHirsch/notam-cropper.git](https://github.com/DukeHirsch/notam-cropper.git)
cd notam-cropper
python -m venv .venv
.venv\Scripts\activate
