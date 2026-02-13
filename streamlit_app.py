import streamlit as st
from pypdf import PdfReader, PdfWriter
from google import genai
import io
import os
import datetime
import re

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="NOTAM Cropper",
    page_icon="✈️",
    layout="wide"
)


# --- AUTHENTICATION HANDLER ---
def get_api_key():
    """
    Robust key retrieval.
    1. Checks Streamlit Cloud Secrets (Production).
    2. Checks local .streamlit/secrets.toml (Development).
    """
    try:
        return st.secrets["GEMINI_KEY"]
    except:
        return None


# --- HELPER: SMART PAGE DETECTION ---
def suggest_relevant_pages(reader):
    """
    Scans pages for NOTAM-specific keywords (RCTP format, ICAO codes, Valid periods).
    Returns a list of 0-indexed page numbers that appear to contain actual data.
    """
    relevant_indices = []
    # Keywords found in your RCTP example and standard NOTAMs
    keywords = [
        r"RCTP", r"VALID:", r"CLSD", r"NOTAM", r"EST",
        r"RWY", r"TWY", r"OPERATIONAL", r"Q\)", r"FIR"
    ]

    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            if any(re.search(k, text, re.IGNORECASE) for k in keywords):
                relevant_indices.append(i)

    return relevant_indices


# --- AI ENGINE ---
def summarize_notam_data(text):
    api_key = get_api_key()
    if not api_key:
        return "❌ Error: API Key not found. Please set GEMINI_KEY in secrets."

    client = genai.Client(api_key=api_key)
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    # --- THE PILOT PROMPT ---
    # Upgraded with Red Markers and Fleet Filters
    prompt = f"""
    ROLE: You are a Senior Captain creating a legal Pilot Briefing.
    TODAY'S DATE: {today_str}

    TASK: Reformat the raw NOTAM text into a structured, categorized, and collapsible HTML view.

    --- DISPLAY RULES (STRICT) ---
    1. **GROUPING:** Group NOTAMs strictly by **STATION/AIRPORT** (e.g., RCTP, VECF, EDDM).

    2. **CATEGORIES & SORTING:** Inside each station, group NOTAMs into these specific types. 
       **CRITICAL RULE:** Any NOTAM mentioning "A380" or "Code Letter F" MUST go to the "IRRELEVANT" group, regardless of its content.

       - **RUNWAY** (Closures, Friction, WIP) -> Default: OPEN
       - **APPROACH** (ILS, VOR, PAPI, Lights) -> Default: OPEN
       - **TAXI/APRON** (Closures, Pushback) -> Default: CLOSED
       - **AIRSPACE** (FIR Restrictions, Military Exercises, Danger Areas) -> Default: CLOSED
       - **OTHER** (Admin, Services, Obstacles) -> Default: CLOSED
       - **IRRELEVANT** (A380, Code F, Code Letter F) -> Default: CLOSED

    3. **THE HEADER TAG (Heads-Up Display):** Format: `**NOTAM_ID** VALIDITY_PERIOD &nbsp;&nbsp;&nbsp;&nbsp; ` **`[ TYPE | AGE ]`**
       * **TYPE:** RWY, NAV, TWY, AIR, OBS, MIL, IRR (for Irrelevant).
       * **AGE:** Days elapsed since start date (Zero-padded: 003, 014).

    4. **RED MARKER HIGHLIGHTING:**
       You MUST wrap the following restrictive words in this HTML span: `<span style='color: red; font-weight: bold;'>WORD</span>`.
       * **Target Words:** CLSD, CLOSED, U/S, UNSERVICEABLE, NOT AUTH, NOT AUTHORIZED, SUSPENDED, PROHIBITED, RESTRICTED.
       * *Example:* `RWY 05R <span style='color: red; font-weight: bold;'>CLSD</span> due to work.`

    5. **CONTENT FORMAT:**
       - Summarize the NOTAM text into 1-2 clean lines below the header.
       - Remove legal garbage (e.g., "REF AIP...").

    6. **COLLAPSIBILITY (HTML):**
       - **CRITICAL** categories (Runway, Approach) -> `<details open>`
       - **NON-CRITICAL** categories (Airspace, Taxi, Irrelevant) -> `<details>` (Closed)

    --- OUTPUT TEMPLATE ---

    ### **RCTP (Taipei)**
    <details open> <summary><b>🚨 RUNWAY (2 Items)</b></summary>
    * **1A293/26** 10FEB - 03MAR &nbsp;&nbsp;&nbsp; **[ RWY | 003 ]**
        <br>RWY 05R/23L <span style='color: red; font-weight: bold;'>CLSD</span> 0400-0430 Daily due to inspection.
    </details>

    <details> <summary><b>📵 IRRELEVANT / FLEET (2 Items)</b></summary>
    * **1A206/26** 26JAN - 25APR &nbsp;&nbsp;&nbsp; **[ IRR | 017 ]**
        <br>ACFT with Code Letter F must follow specific taxi guidance.
    </details>

    INPUT TEXT:
    {text[:45000]} 
    """

    try:
        # Using Gemini 2.0 Flash for speed and large context window
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        return response.text
    except Exception as e:
        return f"⚠️ AI Analysis Failed: {e}"


# --- MAIN INTERFACE ---
st.title("✈️ NOTAM Cropper & Sort")
st.markdown("### Upload -> Crop -> Intelligent Briefing")

# 1. AUTH CHECK
if not get_api_key():
    st.error("🔐 SYSTEM LOCKED. Missing API Key.")
    st.info("Local: Add to .streamlit/secrets.toml \nCloud: Add to App Settings > Secrets")
    st.stop()

# 2. FILE UPLOADER
uploaded_file = st.file_uploader("Drop your PDF here", type="pdf")

if uploaded_file:
    # Read PDF
    try:
        reader = PdfReader(uploaded_file)
        total_pages = len(reader.pages)

        suggested_indices = suggest_relevant_pages(reader)

        if suggested_indices:
            if len(suggested_indices) == total_pages:
                default_range = f"1-{total_pages}"
                auto_msg = "✅ All pages contain NOTAM data."
            else:
                start = suggested_indices[0] + 1
                end = suggested_indices[-1] + 1
                default_range = f"{start}-{end}"
                auto_msg = f"🔍 Detected NOTAM data on pages {default_range}."
        else:
            default_range = f"1-{total_pages}"
            auto_msg = "⚠️ No standard NOTAM format detected."

        st.success(f"Loaded **{uploaded_file.name}** ({total_pages} pages)")
        st.info(auto_msg)

        # --- TABS ---
        tab1, tab2 = st.tabs(["✂️ The Scalpel", "🧠 The Brain"])

        with tab1:
            st.header("Remove Irrelevant Pages")
            keep_range = st.text_input("Page Range", value=default_range)

            if st.button("Generate Clean PDF", type="primary"):
                try:
                    writer = PdfWriter()
                    selected_indices = set()

                    parts = keep_range.replace(" ", "").split(',')
                    for part in parts:
                        if '-' in part:
                            start, end = map(int, part.split('-'))
                            for i in range(start, end + 1):
                                selected_indices.add(i - 1)
                        else:
                            selected_indices.add(int(part) - 1)

                    final_indices = sorted([i for i in list(selected_indices) if 0 <= i < total_pages])

                    if not final_indices:
                        st.error("No valid pages selected!")
                    else:
                        for i in final_indices:
                            writer.add_page(reader.pages[i])

                        output_buffer = io.BytesIO()
                        writer.write(output_buffer)

                        st.write(f"✅ Keeping **{len(final_indices)}** pages.")
                        st.download_button(
                            label="⬇️ Download Cropped PDF",
                            data=output_buffer.getvalue(),
                            file_name=f"Clean_{uploaded_file.name}",
                            mime="application/pdf"
                        )

                except Exception as e:
                    st.error(f"Invalid Format. Error: {e}")

        # --- TAB 2: AI SORTING ---
        with tab2:
            st.header("Smart Pilot Sort")
            st.caption("Grouped by Airport > Type | Collapsible FIR Data | Heads-Up Tags")

            if st.button("Analyze & Sort NOTAMs"):
                with st.spinner("🤖 Categorizing & Tagging..."):
                    full_text = ""
                    # Increased page limit to handle long FIR sections if needed
                    limit = min(30, total_pages)

                    for i in range(limit):
                        page_text = reader.pages[i].extract_text()
                        if page_text:
                            full_text += f"--- PAGE {i + 1} ---\n{page_text}\n"

                    if len(full_text) < 50:
                        st.warning("⚠️ Text extraction failed (Scanned PDF?).")
                    else:
                        summary = summarize_notam_data(full_text)

                        st.subheader("Pilot Briefing")
                        # unsafe_allow_html is CRITICAL for the <details> tags to render
                        st.markdown(summary, unsafe_allow_html=True)

                        st.download_button("Download Briefing (.txt)", summary, file_name="pilot_briefing.txt")

    except Exception as e:
        st.error(f"Error reading PDF: {e}")