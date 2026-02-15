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
import base64
import urllib.request

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="NOTAM Pilot Briefing",
    page_icon="✈️",
    layout="wide"
)


# --- HELPER: FETCH GITHUB VERSION ---
@st.cache_data(ttl=3600)  # Cache for 1 hour to prevent GitHub API rate-limiting
def get_github_version():
    try:
        # Ping the public GitHub API for the latest release tag
        url = "https://api.github.com/repos/DukeHirsch/notam-cropper/releases/latest"
        req = urllib.request.Request(url, headers={'User-Agent': 'Streamlit-App'})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get("tag_name", "v1.0.0")
    except Exception:
        # Fallback if the iPad is offline or GitHub API is temporarily blocking us
        return "v1.0.0"


# --- HELPER: FETCH GITHUB README ---
@st.cache_data(ttl=3600)  # Cache for 1 hour to prevent GitHub API rate-limiting
def get_github_readme():
    try:
        # Fetch the raw markdown directly from the main branch
        url = "https://raw.githubusercontent.com/DukeHirsch/notam-cropper/main/README.md"
        req = urllib.request.Request(url, headers={'User-Agent': 'Streamlit-App'})
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.read().decode('utf-8')
    except Exception:
        return "⚠️ Could not load documentation from GitHub. Please ensure you have an active internet connection."


# --- AUTHENTICATION HANDLER ---
def get_api_key():
    # 1. Check Lead Engineer's absolute central config path first
    central_key_path = r"C:\Users\chris\OneDrive\Desktop\PublicDemandBot\Config\gemini_key.txt"
    if os.path.exists(central_key_path):
        with open(central_key_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    # 2. Check local project Streamlit secrets path
    local_key_path = r"C:\Users\chris\OneDrive\Desktop\NOTAM-cropper\.streamlit\secrets.toml"
    if os.path.exists(local_key_path):
        with open(local_key_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Extract just the key value, ignoring the TOML syntax
            match = re.search(r'GEMINI_KEY\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)

    # 3. Fallback to standard Streamlit Cloud secrets manager
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

    2. EXCLUSION RULE (CRITICAL): DO NOT include Company NOTAMs. Completely ignore any NOTAM ID that starts with "CO" (e.g., CO11/26, CO152/22).

    3. AGE RULE: Calculate days elapsed since the valid start date. Max limit is 999.

    4. PADDING RULE (CRITICAL): Pad the age to exactly 3 characters using underscores (_).
       - 5 days -> __5
       - 45 days -> _45
       - 120 days -> 120
       - 1000+ days -> 999

    5. FORMAT: [ TYPE | AGE ]

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
    Guarantees only one stamp per NOTAM to prevent double-stamping.
    """
    stamped_notams = set()

    for page in doc:
        for notam_id, tag in notam_data.items():
            if notam_id in stamped_notams:
                continue

            # Find the exact coordinates of the NOTAM ID on the page
            text_instances = page.search_for(notam_id)
            for inst in text_instances:
                # Left margin check: ensures we only stamp the actual header line,
                # not a reference to the NOTAM buried mid-sentence.
                if inst.x0 < 100:
                    # Calculate the X position (shifted 2 chars left per Lead's request)
                    # Align the Y coordinate to the baseline of the NOTAM ID text
                    x_pos = page.rect.width - 130
                    y_pos = inst.y1 - 1

                    # Stamp the tag in bold courier
                    page.insert_text((x_pos, y_pos), tag, fontname="courier-bold", fontsize=10, color=(0, 0, 0))

                    stamped_notams.add(notam_id)
                    break  # Stop checking this NOTAM ID on this page to prevent duplicates

    # Save to a bytes buffer for Streamlit download
    out_pdf = io.BytesIO()
    doc.save(out_pdf)
    return out_pdf.getvalue()


# --- MAIN INTERFACE ---
st.title("✈️ NOTAM Pilot Briefing")

# Fetch and display the dynamic GitHub version
app_version = get_github_version()
st.caption(f"**Live Build:** `{app_version}`")

# Fetch and display the README in a collapsible expander
with st.expander("📖 View Documentation & Setup Guide", expanded=False):
    readme_text = get_github_readme()
    st.markdown(readme_text)

st.markdown("### Upload -> AI Analyze -> Send to EFB")

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

                        # 1. Convert to Base64
                        b64_pdf = base64.b64encode(annotated_pdf_bytes).decode('utf-8')

                        # 2. JavaScript Blob workaround to bypass Safari restrictions
                        js_code = (
                            f"event.preventDefault();"
                            f"var b64='{b64_pdf}';"
                            f"var bin=atob(b64);"
                            f"var arr=new Uint8Array(bin.length);"
                            f"for(var i=0;i<bin.length;i++){{arr[i]=bin.charCodeAt(i);}}"
                            f"var blob=new Blob([arr],{{type:'application/pdf'}});"
                            f"window.open(URL.createObjectURL(blob),'_blank');"
                        )

                        # 3. Inject Button
                        pdf_display_html = f'''
                        <a href="#" onclick="{js_code}" 
                           style="display: inline-block; padding: 0.6em 1.2em; color: white; 
                                  background-color: #FF4B4B; text-decoration: none; 
                                  border-radius: 4px; font-weight: 600; font-family: sans-serif;
                                  text-align: center; margin-top: 10px;">
                            📄 Open Briefing in New Tab
                        </a>
                        <br><br>
                        <p style="font-size: 0.85em; color: gray;">
                            <i><b>iPad Tip:</b> Tap the button above to view the PDF. Use the iOS Share icon (square with an up arrow) to send it directly to GoodReader, ForeFlight, or your preferred EFB.</i>
                        </p>
                        '''
                        st.markdown(pdf_display_html, unsafe_allow_html=True)
                    else:
                        st.error(status_msg)

    except Exception as e:
        st.error(f"Error processing PDF: {e}")