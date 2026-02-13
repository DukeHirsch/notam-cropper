import streamlit as st
from pypdf import PdfReader, PdfWriter
from google import genai
import io
import os

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="NOTAM Cropper",
    page_icon="✈️",
    layout="centered"
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


# --- AI ENGINE ---
def summarize_notam_data(text):
    api_key = get_api_key()
    if not api_key:
        return "❌ Error: API Key not found. Please set GEMINI_KEY in secrets."

    client = genai.Client(api_key=api_key)

    # Specialized Prompt for NOTAM/Flight Data
    prompt = f"""
    TASK: You are an Aviation Data Analyst. Process this text.

    GOAL: Remove administrative fluff and highlight operational risks.

    INSTRUCTIONS:
    1. FILTER: Ignore standard disclaimers, copyrights, and blank filler.
    2. EXTRACT: Keep dates, coordinates, altitudes, and specific warnings.
    3. FORMAT: Output as a clean, high-density bulleted list.
    4. HIGHLIGHT: If you see words like "PROHIBITED", "DANGER", or "CLOSED", put them in **BOLD CAPS**.

    INPUT TEXT:
    {text[:20000]} (truncated for token limits)
    """

    try:
        # Using Gemini 2.0 Flash for speed
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        return response.text
    except Exception as e:
        return f"⚠️ AI Analysis Failed: {e}"


# --- MAIN INTERFACE ---
st.title("✈️ NOTAM Cropper")
st.markdown("### Upload Report -> Crop Pages -> AI Summary")

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
        st.success(f"Loaded **{uploaded_file.name}** ({total_pages} pages)")

        # --- TAB 1: THE SCALPEL (CROPPING) ---
        tab1, tab2 = st.tabs(["✂️ The Scalpel", "🧠 The Brain"])

        with tab1:
            st.header("Remove Irrelevant Pages")
            st.caption("Enter pages to KEEP. (e.g. `1, 3-5, 10`)")

            keep_range = st.text_input("Page Range", value=f"1-{total_pages}")

            if st.button("Generate Clean PDF", type="primary"):
                try:
                    writer = PdfWriter()
                    selected_indices = set()

                    # Range Parsing Logic
                    parts = keep_range.replace(" ", "").split(',')
                    for part in parts:
                        if '-' in part:
                            start, end = map(int, part.split('-'))
                            # Clamp to valid range
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

                        # Save to RAM
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
                    st.error(f"Invalid Format. Use '1-5, 8'. Error: {e}")

        # --- TAB 2: THE BRAIN (AI SUMMARY) ---
        with tab2:
            st.header("AI Risk Analysis")
            st.info("This will extract text from the FIRST 10 PAGES of your selection to find critical info.")

            if st.button("Analyze Document"):
                with st.spinner("🤖 Reading..."):
                    full_text = ""
                    # Limit to first 10 pages to save wait time/tokens
                    limit = min(10, total_pages)

                    for i in range(limit):
                        page_text = reader.pages[i].extract_text()
                        if page_text:
                            full_text += f"--- PAGE {i + 1} ---\n{page_text}\n"

                    if len(full_text) < 50:
                        st.warning("⚠️ This PDF seems to be an image scan (no selectable text). AI cannot read it.")
                    else:
                        summary = summarize_notam_data(full_text)
                        st.subheader("Operational Summary")
                        st.markdown(summary)
                        st.download_button("Download Summary (.txt)", summary, file_name="summary.txt")

    except Exception as e:
        st.error(f"Error reading PDF: {e}")