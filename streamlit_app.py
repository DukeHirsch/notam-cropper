import sys
import warnings

warnings.simplefilter(action='ignore', category=FutureWarning)
sys.stdout.reconfigure(encoding='utf-8')

import streamlit as st
from pypdf import PdfReader
import google.generativeai as genai
import os
import datetime
import re

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="NOTAM Pilot Briefing",
    page_icon="✈️",
    layout="wide"
)


# --- AUTHENTICATION HANDLER ---
def get_api_key():
    # Check absolute Streamlit secrets path first
    key_path = r"C:\Users\chris\OneDrive\Desktop\NOTAM-cropper\.streamlit\secrets.toml"
    if os.path.exists(key_path):
        with open(key_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Extract just the key value, ignoring the TOML syntax
            match = re.search(r'GEMINI_KEY\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)

    # Fallback to standard Streamlit secrets manager
    try:
        return st.secrets["GEMINI_KEY"]
    except:
        return None


# --- HELPER: SMART PAGE DETECTION ---
def get_relevant_text(reader):
    """
    Scans pages for NOTAM-specific keywords.
    Returns the concatenated text of ONLY the relevant pages.
    """
    relevant_text = ""
    relevant_page_count = 0

    # Keywords found in your RCTP example and standard NOTAMs
    keywords = [
        r"RCTP", r"VALID:", r"CLSD", r"NOTAM", r"EST",
        r"RWY", r"TWY", r"OPERATIONAL", r"Q\)", r"FIR"
    ]

    total_pages = len(reader.pages)

    # Scan every page (up to a reasonable limit to prevent timeouts on massive docs)
    # We scan all, but text extraction is fast.
    for i in range(total_pages):
        page_text = reader.pages[i].extract_text()
        if page_text:
            # If page contains any NOTAM keyword, add it to the buffer
            if any(re.search(k, page_text, re.IGNORECASE) for k in keywords):
                relevant_text += f"--- PAGE {i + 1} ---\n{page_text}\n"
                relevant_page_count += 1

    # Fallback: If regex failed to find anything (e.g. weird formatting), return first 30 pages
    if not relevant_text:
        limit = min(30, total_pages)
        for i in range(limit):
            relevant_text += f"--- PAGE {i + 1} ---\n{reader.pages[i].extract_text()}\n"

    return relevant_text, relevant_page_count


# --- HELPER: CLEAN AI OUTPUT ---
def clean_ai_response(text):
    """
    Removes markdown code fences so Streamlit renders the HTML.
    """
    text = text.replace("```html", "").replace("```", "")
    return text


# --- AI ENGINE ---
def summarize_notam_data(text):
    api_key = get_api_key()
    if not api_key:
        return "❌ Error: API Key not found. Please check secrets.toml or Streamlit secrets."

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    # --- THE PILOT PROMPT ---
    prompt = f"""
    ROLE: You are a Senior Captain creating a legal Pilot Briefing.
    TODAY'S DATE: {today_str}

    TASK: Reformat the raw NOTAM text into a structured, categorized, and collapsible HTML view.

    --- DISPLAY RULES (STRICT) ---
    1. **GROUPING:** Group NOTAMs strictly by **STATION/AIRPORT** (e.g., RCTP, VECF, EDDM).

    2. **CATEGORIES & SORTING:** Inside each station, group NOTAMs into these specific types. 
       **CRITICAL RULE:** Any NOTAM mentioning "A380" or "Code Letter F" MUST go to the "IRRELEVANT" group.

       - **RUNWAY** (Closures, Friction, WIP) -> Default: OPEN
       - **APPROACH** (ILS, VOR, PAPI, Lights) -> Default: OPEN
       - **TAXI/APRON** (Closures, Pushback) -> Default: CLOSED
       - **AIRSPACE** (FIR Restrictions, Military Exercises, Danger Areas) -> Default: CLOSED
       - **OTHER** (Admin, Services, Obstacles) -> Default: CLOSED
       - **IRRELEVANT** (A380, Code F, Code Letter F) -> Default: CLOSED

    3. **THE HEADER TAG (Heads-Up Display):** Format: `**NOTAM_ID** &nbsp;&nbsp; ` **`[ TYPE | AGE ]`**
       * **TYPE:** RWY, NAV, TWY, AIR, OBS, MIL, IRR (for Irrelevant).
       * **AGE:** Days elapsed since start date (Zero-padded: 003).

    4. **RED MARKER HIGHLIGHTING:**
       You MUST wrap restrictive words (CLSD, U/S, NOT AUTH, CLOSED, SUSPENDED) in: 
       `<span style='color: red; font-weight: bold; background-color: #ffe6e6; padding: 2px;'>WORD</span>`

    5. **CONTENT FORMAT:**
       - Summarize into 1-2 clean lines. Remove "REF AIP...", "FLW...", "WI...".
       - DO NOT use Markdown code blocks. Output raw HTML text.

    6. **COLLAPSIBILITY (HTML):**
       - **CRITICAL** (Runway, Approach) -> `<details open>`
       - **NON-CRITICAL** (Airspace, Taxi, Irrelevant) -> `<details>` (Closed)

    --- OUTPUT TEMPLATE ---
    <h3>RCTP (Taipei)</h3>
    <details open> <summary><b>🚨 RUNWAY (2 Items)</b></summary>
    <ul>
    <li><b>1A293/26</b> &nbsp; <b>[ RWY | 003 ]</b><br>
    RWY 05R/23L <span style='color: red; font-weight: bold; background-color: #ffe6e6;'>CLSD</span> 0400-0430 Daily.</li>
    </ul>
    </details>

    <details> <summary><b>📵 IRRELEVANT (1 Item)</b></summary>
    <ul>
    <li><b>1A206/26</b> &nbsp; <b>[ IRR | 017 ]</b><br>
    Code Letter F restrictions.</li>
    </ul>
    </details>

    INPUT TEXT:
    {text} 
    """

    try:
        response = model.generate_content(prompt)
        return clean_ai_response(response.text)
    except Exception as e:
        return f"⚠️ AI Analysis Failed: {e}"


# --- MAIN INTERFACE ---
st.title("✈️ NOTAM Pilot Briefing")
st.markdown("### Upload -> AI Sort -> Fly")

# 1. AUTH CHECK
if not get_api_key():
    st.error("🔐 SYSTEM LOCKED. Missing API Key.")
    st.info("Local: Add to .streamlit/secrets.toml \nCloud: Add to App Settings > Secrets")
    st.stop()

# 2. FILE UPLOADER
uploaded_file = st.file_uploader("Drop your PDF here", type="pdf")

if uploaded_file:
    try:
        reader = PdfReader(uploaded_file)
        total_pages = len(reader.pages)
        st.success(f"Loaded **{uploaded_file.name}** ({total_pages} pages)")

        if st.button("Generate Briefing", type="primary"):
            with st.spinner("🤖 Scanning pages & sorting data..."):
                # Run smart extraction
                relevant_text, page_count = get_relevant_text(reader)

                if len(relevant_text) < 50:
                    st.warning("⚠️ No readable text found. Is this a scanned image?")
                else:
                    st.info(f"✅ Processed {page_count} relevant pages out of {total_pages}.")

                    summary = summarize_notam_data(relevant_text)

                    st.subheader("Pilot Briefing")
                    st.markdown(summary, unsafe_allow_html=True)

                    st.download_button(
                        label="Download Briefing (.html)",
                        data=summary,
                        file_name="pilot_briefing.html",
                        mime="text/html"
                    )

    except Exception as e:
        st.error(f"Error reading PDF: {e}")