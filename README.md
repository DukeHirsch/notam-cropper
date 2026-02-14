# ✈️ NOTAM Pilot Briefing Annotator

A secure, AI-powered web application designed to automatically categorize and age-stamp NOTAMs within LIDO pilot briefing PDFs. 

Built specifically for iPad and Electronic Flight Bag (EFB) integration, this tool minimizes visual clutter in the cockpit by providing instantly readable, margin-aligned NOTAM classifications without altering the original dispatcher text.

## 🚀 Features

* **Smart Categorization:** Uses Google Gemini to classify standard NOTAMs into six distinct operational categories:
  * `RWY` (Runway)
  * `NAV` (Approach/Navigation)
  * `TWY` (Taxiway/Apron)
  * `AIR` (Airspace)
  * `OBS` (Obstacles/Other)
  * `IRR` (Irrelevant - e.g., A380/Code F specific)
* **Age Calculation:** Automatically calculates the age of each NOTAM in days (capped at `999`) and formats it with strict visual padding (e.g., `__5`, `_45`) for instant recognition in a dark flight deck.
* **Non-Destructive Stamping:** Annotates the right margin of the briefing using exact PDF coordinate math, guaranteeing a clean visual buffer that never overwrites the original text.
* **Company NOTAM Exclusion (By Design):** Automatically ignores all Company NOTAMs (IDs starting with `CO`). Due to their free-text nature and long-term validity, these are left blank to reduce visual noise.

## 🔒 Security & Data Compliance

This tool is strictly scoped to process public aviation data. It operates exclusively on the standard NOTAM sections of the LIDO briefing. It is structurally designed to require no sensitive inputs—avoiding any interaction with proprietary Operational Flight Plans (OFP), fuel calculations, or passenger data, strictly adhering to corporate AI data security mindsets.

## 📱 iPad & EFB Workflow (GoodReader / ForeFlight)

This application is built to hand off the annotated PDF seamlessly to your preferred EFB using native iOS architecture:

1. **Access the Web App:** Open the deployment URL in Safari on your iPad.
2. **Upload & Analyze:** Drop your LIDO PDF into the uploader and tap **Generate Annotated PDF**.
3. **Open in Preview:** Tap the red **📄 Open Briefing in New Tab** button. The annotated PDF will open full-screen in Safari.
4. **Export to EFB:** Tap the native Apple **Share** icon (the square with the up arrow) in the top right corner and select **GoodReader**, **ForeFlight**, or your EFB of choice.

## 💻 Local Development Setup

For colleagues looking to fork or run this locally on Windows:

1. Clone the repository and create a Python virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Add your API key to a local secrets file at `.streamlit/secrets.toml`:
   ```toml
   GEMINI_KEY = "your_api_key_here"
