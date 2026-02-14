import sys
import warnings

warnings.simplefilter(action='ignore', category=FutureWarning)
sys.stdout.reconfigure(encoding='utf-8')

import streamlit as st
import fitz  # PyMuPDF
import google.generativeai as genai
import os
import datetime
import re
import json
import io

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


# --- HELPER: FULL TEXT EXTRACTION ---
def extract_pdf_text(doc):
    """
    Extracts text from all pages using PyMuPDF.
    """
    full_text = ""
    total_pages = len(doc)
    for i in range(total_pages):
        page_text = doc[i].get_text()
        if page_text:
            full_text += f"--- PAGE {i + 1} ---\n{page_text}\n"
    return full_text, total_pages


# --- HELPER: CLEAN AI OUTPUT ---
def clean_json_response(text):
    """
    Strips markdown code fences so json.loads() doesn't crash.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


# --- AI ENGINE ---
def analyze_notams(text):
    api_key = get_api_key()
    if not api_key:
        return None, "❌ Error: API Key not found. Please check secrets.toml or Streamlit secrets."

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    # --- THE JSON PROMPT ---
    prompt = f"""
    ROLE: You are a Senior Captain creating a legal Pilot Briefing.
    TODAY'S DATE: {today_str}

    TASK: Analyze the raw NOTAM text and return a STRICT JSON DICTIONARY mapping each NOTAM ID to its classification tag.

    --- RULES ---
    1. CATEGORIES (Map to these exact 3-letter codes):
       - RUNWAY -> RWY
       - APPROACH -> NAV
       - TAXI/APRON -> TWY
       - AIRSPACE -> AIR
       - OTHER -> OBS
       - IRRELEVANT (A380, Code F) -> IRR

    2. AGE RULE: Calculate days elapsed since the valid start date. Max limit is 999.

    3. PADDING RULE (CRITICAL): Pad the age to exactly 3 characters using underscores (_).
       - 5 days -> __5
       - 45 days -> _45
       - 120 days -> 120
       - 1000+ days -> 999

    4. FORMAT: [ TYPE | AGE ]

    --- OUTPUT FORMAT ---
    Return ONLY a valid JSON dictionary. No explanations, no markdown fences.
    {{
        "1A293/26": "[ RWY | __3 ]",
        "1A206/26": "[ IRR | _17 ]"
    }}

    INPUT TEXT:
    {text} 
    """

    try:
        response = model.generate_content(prompt)
        cleaned_json = clean_json_response(response.text)
        return json.loads(cleaned_json), "Success"
    except json.JSONDecodeError:
        return None, "⚠️ AI did not return a valid JSON format."
    except Exception as e:
        return None, f"⚠️ AI Analysis Failed: {e}"


# --- PDF ANNOTATION ENGINE ---
def stamp_pdf(doc, notam_data):
    """
    Searches the PDF for NOTAM IDs and stamps the AI tag on the right margin.
    """
    for page in doc:
        for notam_id, tag in notam_data.items():
            # Find the exact coordinates of the NOTAM ID on the page
            text_instances = page.search_for(notam_id)
            for inst in text_instances:
                # Calculate the X position (shifted 2 chars left per Lead's request)
                # Align the Y coordinate to the baseline of the NOTAM ID text
                x_pos = page.rect.width - 130
                y_pos = inst.y1 - 1

                # Stamp the tag in bold courier
                page.insert_text((x_pos, y_pos), tag, fontname="courier-bold", fontsize=10, color=(0, 0, 0))

    # Save to a bytes buffer for Streamlit download
    out_pdf = io.BytesIO()
    doc.save(out_pdf)
    return out_pdf.getvalue()


# --- MAIN INTERFACE ---
st.title("✈️ NOTAM Pilot Briefing")
st.markdown("### Upload -> AI Analyze -> Download Annotated PDF")

# 1. AUTH CHECK
if not get_api_key():
    st.error("🔐 SYSTEM LOCKED. Missing API Key.")
    st.info("Local: Add to .streamlit/secrets.toml \nCloud: Add to App Settings > Secrets")
    st.stop()

# 2. FILE UPLOADER
uploaded_file = st.file_uploader("Drop your LIDO PDF here", type="pdf")

if uploaded_file:
    try:
        # Load directly into PyMuPDF
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        total_pages = len(doc)
        st.success(f"Loaded **{uploaded_file.name}** ({total_pages} pages)")

        if st.button("Generate Annotated PDF", type="primary"):
            with st.spinner("🤖 Extracting text & having AI analyze NOTAMs..."):
                extracted_text, page_count = extract_pdf_text(doc)

                if len(extracted_text) < 50:
                    st.warning("⚠️ No readable text found. Is this a scanned image?")
                else:
                    st.info(f"✅ Processed all {page_count} pages. Generating JSON tags...")

                    # Run AI JSON mapping
                    notam_dict, status_msg = analyze_notams(extracted_text)

                    if notam_dict:
                        with st.spinner("📑 Stamping tags onto the PDF..."):
                            annotated_pdf_bytes = stamp_pdf(doc, notam_dict)

                        st.success("✅ Briefing successfully annotated!")

                        st.download_button(
                            label="Download Annotated Briefing (.pdf)",
                            data=annotated_pdf_bytes,
                            file_name="annotated_pilot_briefing.pdf",
                            mime="application/pdf"
                        )
                    else:
                        st.error(status_msg)

    except Exception as e:
        st.error(f"Error processing PDF: {e}")