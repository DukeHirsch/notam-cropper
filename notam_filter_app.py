import sys
import warnings
import asyncio
import time
import random

# --- WINDOWS ASYNCIO FIX FOR STREAMLIT + PLAYWRIGHT ---
if sys.platform.startswith('win32'):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

warnings.simplefilter(action='ignore', category=FutureWarning)
sys.stdout.reconfigure(encoding='utf-8')

import streamlit as st
import fitz  # PyMuPDF
import os
import datetime
import re
import io
import math
import base64
import pandas as pd
import subprocess
from streamlit_gsheets import GSheetsConnection
from playwright.sync_api import sync_playwright

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="NOTAM Filter & Cropper",
    page_icon="✂️",
    layout="wide"
)

SHEET_URL = "https://docs.google.com/spreadsheets/d/1hG8BDR9R1Wz4t9nU-lCy82sVIT8-oGfhyy7NT1mbbss/edit"


# --- STREAMLIT CLOUD HOOK ---
@st.cache_resource
def install_playwright():
    """Forces the Streamlit container to download the Firefox binary safely."""
    try:
        subprocess.run(["playwright", "install", "firefox"], check=False)
    except Exception as e:
        print(f"[WARNING] Playwright binary installation hook failed: {e}")


install_playwright()


# --- DATA LOADERS & INGESTION (CLOUD) ---
@st.cache_data(ttl=600, show_spinner=False)
def load_blacklist():
    """Fetches the Blacklist from Google Sheets and caches it for 10 minutes."""
    blacklist_dict = {}
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(spreadsheet=SHEET_URL, worksheet="Blacklist", ttl=600)

        for _, row in df.iterrows():
            notam_id = str(row.get("ID", "")).strip()
            if notam_id and notam_id.lower() != "nan":
                loc = str(row.get("Location", "UNK")).strip()
                tag = str(row.get("Type", "")).strip()
                blacklist_dict[notam_id] = (notam_id, loc, tag)
    except Exception as e:
        st.error(f"⚠️ Failed to load Blacklist from cloud: {e}")

    return blacklist_dict


@st.cache_data(ttl=600, show_spinner=False)
def load_and_prune_known_notams():
    """Fetches the Known NOTAMs from Google Sheets and caches it."""
    known_dict = {}
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(spreadsheet=SHEET_URL, worksheet="Known_NOTAMs", ttl=600)

        for _, row in df.iterrows():
            notam_id = str(row.get("ID", "")).strip()
            tag = str(row.get("Tag", "")).strip()
            if notam_id and notam_id.lower() != "nan" and tag and tag.lower() != "nan":
                known_dict[notam_id] = tag
    except Exception as e:
        st.error(f"⚠️ Failed to load Known NOTAMs from cloud: {e}")

    return known_dict


@st.cache_data(ttl=600, show_spinner=False)
def load_unknown_notams_cache():
    """Fetches the Unknown NOTAMs from Google Sheets to prevent redundant FAA checks."""
    unknown_set = set()
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(spreadsheet=SHEET_URL, worksheet="Unknown_NOTAMs", ttl=600)

        if not df.empty and "ID" in df.columns:
            unknown_set = set(df["ID"].dropna().astype(str).str.strip().tolist())
    except Exception as e:
        st.warning(f"⚠️ Failed to load Unknown NOTAMs cache from cloud: {e}")

    return unknown_set


@st.cache_data(ttl=600, show_spinner=False)
def load_false_positives():
    """Fetches the dynamic list of false positive ICAO codes from the cloud."""
    fp_set = {"TKOF", "LNAV", "VNAV", "AMSL", "ACFT", "WILL", "ELEV", "DEST", "ORIG", "ALTN", "RNAV", "GNSS", "ILSX",
              "RWYS"}
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(spreadsheet=SHEET_URL, worksheet="False_Positives", ttl=600)

        if not df.empty and "Code" in df.columns:
            cloud_fps = set(df["Code"].dropna().astype(str).str.strip().str.upper().tolist())
            fp_set.update(cloud_fps)
    except Exception as e:
        st.warning(f"⚠️ Failed to load False_Positives from cloud: {e}")

    return fp_set


def log_new_false_positives(new_codes):
    """Appends newly discovered false positive ICAOs to the cloud."""
    if not new_codes: return
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df_fp = conn.read(spreadsheet=SHEET_URL, worksheet="False_Positives", ttl=0)

        existing_codes = set()
        if not df_fp.empty and "Code" in df_fp.columns:
            existing_codes = set(df_fp["Code"].dropna().astype(str).str.strip().str.upper().tolist())
        else:
            df_fp = pd.DataFrame(columns=["Code"])

        new_rows = [{"Code": code} for code in new_codes if code not in existing_codes]

        if new_rows:
            new_df = pd.DataFrame(new_rows)
            updated_df = pd.concat([df_fp, new_df], ignore_index=True)
            conn.update(spreadsheet=SHEET_URL, worksheet="False_Positives", data=updated_df)
            load_false_positives.clear()
            print(f"[STATUS] Auto-Learning: Pushed {len(new_rows)} new false positive(s) to the cloud.")
    except Exception as e:
        print(f"[WARNING] Failed to log new false positives to cloud: {e}")


def save_new_known_notams(new_entries_dict):
    """Appends newly discovered Public NOTAM tags to the Google Sheet."""
    if not new_entries_dict: return
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df_known = conn.read(spreadsheet=SHEET_URL, worksheet="Known_NOTAMs", ttl=0)

        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

        new_rows = []
        for notam_id, (tag, loc) in new_entries_dict.items():
            new_rows.append({"ID": notam_id, "Tag": tag, "Location": loc, "Timestamp": today_str})

        new_df = pd.DataFrame(new_rows)
        updated_df = pd.concat([df_known, new_df], ignore_index=True)

        conn.update(spreadsheet=SHEET_URL, worksheet="Known_NOTAMs", data=updated_df)
        load_and_prune_known_notams.clear()
    except Exception as e:
        st.warning(f"Failed to push new known NOTAMs to cloud: {e}")


def log_unknown_notams(unknown_dict):
    """Logs unknown NOTAMs to the Unknown_NOTAMs tab, avoiding duplicates."""
    if not unknown_dict: return
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df_unknown = conn.read(spreadsheet=SHEET_URL, worksheet="Unknown_NOTAMs", ttl=0)

        existing_ids = set()
        if not df_unknown.empty and "ID" in df_unknown.columns:
            existing_ids = set(df_unknown["ID"].dropna().astype(str).str.strip().tolist())

        new_rows = []
        for notam_id, location in unknown_dict.items():
            if notam_id not in existing_ids:
                new_rows.append({"ID": notam_id, "Location": location, "Type": ""})

        if new_rows:
            new_df = pd.DataFrame(new_rows)
            updated_df = pd.concat([df_unknown, new_df], ignore_index=True) if not df_unknown.empty else new_df
            conn.update(spreadsheet=SHEET_URL, worksheet="Unknown_NOTAMs", data=updated_df)
    except Exception as e:
        st.warning(f"Failed to log unknown NOTAMs to cloud: {e}")


# --- FAA ENGINE HELPERS ---
def get_age_data(valid_from_str):
    """Returns a tuple of (integer_age, string_age). Uses actual numbers without underscores."""
    try:
        year = 2000 + int(valid_from_str[0:2])
        month = int(valid_from_str[2:4])
        day = int(valid_from_str[4:6])
        valid_date = datetime.date(year, month, day)

        today = datetime.datetime.now(datetime.timezone.utc).date()
        delta = (today - valid_date).days
        age = max(0, delta)

        if age > 999:
            return age, "999+"
        return age, str(age)
    except:
        return 999, "999+"


def normalize_notam_id(raw_id):
    """Universal Hash: Strips LIDO prefixes and FAA leading zeros to ensure perfect matches."""
    raw_id = str(raw_id).strip().upper()
    # Strip LIDO leading digit (e.g., 1A1234/25 -> A1234/25)
    raw_id = re.sub(r'^\d+([A-Z])', r'\1', raw_id)
    # Strip leading zeros in the numeric part (e.g., A0123/25 -> A123/25)
    if '/' in raw_id:
        parts = raw_id.split('/')
        prefix = re.match(r'^([A-Z]*)0*(\d+)$', parts[0])
        if prefix:
            raw_id = f"{prefix.group(1)}{prefix.group(2)}/{parts[1]}"
    return raw_id


def classify_by_icao_standard(q_code_4_letters):
    if not q_code_4_letters or len(q_code_4_letters) < 2:
        return "MISC"

    subject = q_code_4_letters[0:2].upper()

    rwy_subjects = {'MR', 'MT', 'MW', 'MD'}
    twy_subjects = {'MX', 'MY'}
    nav_subjects = {'IC', 'IG', 'IL', 'ID', 'IS', 'IT', 'IU', 'IW', 'IX', 'IY', 'IZ',
                    'NA', 'NB', 'NC', 'ND', 'NE', 'NF', 'NL', 'NM', 'NN', 'NO', 'NT', 'NV',
                    'PA', 'PD', 'PE', 'PF', 'PI', 'PK', 'PL', 'PM', 'PN', 'PO', 'PR', 'PT', 'PU', 'PX', 'PZ',
                    'CA', 'CS', 'CB', 'CC', 'CD', 'CE', 'CG', 'CL', 'CM', 'CP', 'CR', 'CT'}
    obs_subjects = {'OB', 'OL', 'OA'}
    air_subjects = {'RA', 'RD', 'RM', 'RO', 'RP', 'RT', 'WA', 'WE', 'WM', 'WP', 'WR', 'WS', 'WT', 'WU', 'WV', 'WZ'}

    if subject in rwy_subjects: return "RWY"
    if subject in twy_subjects: return "TWY"
    if subject in nav_subjects: return "NAV"
    if subject in obs_subjects: return "OBS"
    if subject in air_subjects: return "AIR"

    return "MISC"


def fetch_bulk_faa_data(icao_codes_list, ui_status):
    """Fires a Headless Firefox request to the FAA, handling pagination and auto-healing."""
    parsed_faa_results = {}

    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
                viewport={'width': 1280, 'height': 720}
            )
            page = context.new_page()

            ui_status.write("🌐 Establishing secure session with FAA portal...")
            page.goto("https://notams.aim.faa.gov/notamSearch/", wait_until="commit", timeout=30000)
            page.wait_for_timeout(2000)

            try:
                disclaimer_button = page.locator("button:has-text(\"I've read and understood\")")
                if disclaimer_button.is_visible(timeout=2000):
                    disclaimer_button.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass

            # REDUCED CHUNK SIZE: 2 items per request to prevent FAA backend truncation
            chunk_size = 2
            for i in range(0, len(icao_codes_list), chunk_size):
                chunk = icao_codes_list[i:i + chunk_size]
                current_icaos = ",".join(chunk)

                # --- AUTO-HEALING RETRY LOOP (5 Attempts) ---
                for attempt in range(1, 6):
                    offset = 0
                    total_downloaded_for_chunk = 0
                    error_hit = False
                    chunk_aborted = False

                    ui_status.write(f"📡 API Search: **{current_icaos}** (Attempt {attempt}/5)")

                    # --- PAGINATION LOOP ---
                    while True:
                        post_data = {
                            'searchType': '0',
                            'designatorsForLocation': current_icaos,
                            'offset': str(offset),
                            'notamsOnly': 'false',
                            'flightPathResultsType': 'All NOTAMs',
                            'sortColumns': '5 false',
                            'sortDirection': 'true'
                        }

                        try:
                            response = context.request.post(
                                "https://notams.aim.faa.gov/notamSearch/search",
                                form=post_data,
                                headers={
                                    'Origin': 'https://notams.aim.faa.gov',
                                    'Referer': 'https://notams.aim.faa.gov/notamSearch/'
                                }
                            )

                            if response.ok:
                                json_data = response.json()

                                if 'error' in json_data and json_data['error']:
                                    err_msg = json_data['error']
                                    ui_status.warning(f"⚠️ FAA internal error: {err_msg}")

                                    if "Invalid location(s):" in err_msg:
                                        bad_codes = re.findall(r"'([A-Z0-9]{4})'", err_msg)
                                        if bad_codes:
                                            ui_status.info(
                                                f"🔧 Auto-Healing: Stripping invalid codes {bad_codes} and retrying...")
                                            log_new_false_positives(bad_codes)
                                            current_list = current_icaos.split(',')
                                            current_icaos = ",".join([c for c in current_list if c not in bad_codes])
                                            error_hit = True
                                            break  # Break pagination to retry the attempt
                                    else:
                                        chunk_aborted = True
                                        break
                                else:
                                    notam_list = json_data.get('notamList', [])
                                    if not notam_list:
                                        break

                                    for n in notam_list:
                                        raw_msg = n.get('icaoMessage', '') or n.get('traditionalMessage', '')

                                        q_match = re.search(r'Q\)\s*[^/]+/Q([A-Z]{4})', raw_msg)
                                        q_code = q_match.group(1) if q_match else ""
                                        tag = classify_by_icao_standard(q_code)

                                        # Create a dense alphanumeric string for Fingerprint matching
                                        clean_msg = re.sub(r'[^A-Z0-9]', '', raw_msg.upper())

                                        # 1. Map the official notamNumber provided by FAA
                                        base_id = normalize_notam_id(n.get('notamNumber', 'UNK'))
                                        parsed_faa_results[base_id] = {'tag': tag, 'clean_text': clean_msg}

                                        # 2. THE TIGHT NET: Extract IDs from the first 20 chars
                                        for embedded_id in re.findall(r'\b[A-Z]?\d{1,4}/\d{2}\b', raw_msg[:20]):
                                            parsed_faa_results[normalize_notam_id(embedded_id)] = {'tag': tag,
                                                                                                   'clean_text': clean_msg}

                                    offset += len(notam_list)
                                    total_downloaded_for_chunk += len(notam_list)

                                    # End of available pages
                                    if len(notam_list) < 30:
                                        break
                            else:
                                ui_status.warning(f"⚠️ HTTP Error: {response.status} on {current_icaos}")
                                chunk_aborted = True
                                break

                        except Exception as network_error:
                            # Catches ECONNRESET, Timeouts, and hard Playwright crashes
                            ui_status.warning(f"⚠️ WAF bite or network failure on {current_icaos}: {network_error}")
                            chunk_aborted = True
                            break

                    # End of Pagination Loop checks
                    if error_hit and current_icaos:
                        continue  # Retry immediately with cleaned list
                    elif chunk_aborted:
                        if attempt < 5:
                            ui_status.info("⏳ Cooling down for 15 seconds before retry...")
                            time.sleep(15)
                            continue
                        else:
                            ui_status.error(f"❌ Hard failure on {current_icaos} after 5 attempts. Abandoning chunk.")
                            break
                    else:
                        ui_status.write(f"✅ Downloaded {total_downloaded_for_chunk} records for chunk.")
                        # HUMAN PACING: Random delay between 3 and 6 seconds to placate the WAF
                        time.sleep(random.uniform(3.0, 6.0))
                        break  # Move to next chunk

            browser.close()
    except Exception as e:
        ui_status.error(f"❌ Fatal Playwright error: {e}")

    return parsed_faa_results


# --- ANALYSIS ENGINE ---
def analyze_notams(full_text, blacklist_dict, known_dict, unknown_cache, fp_set, ui_status):
    """
    Parses the text, bulk fetches the FAA DB, pulls cached tags, and handles UNKNOWN rules.
    """
    tags_for_pdf = {}
    new_known = {}
    unknown_notams_to_log = {}

    # 1. FIND THE FIR/ENROUTE CUTOFF BOUNDARY (Gracefully handles leading spaces)
    cutoff_idx = len(full_text)
    for header in [r'^\s*ENROUTE AIRPORT\(S\)', r'^\s*EXTENDED AREA', r'^\s*AREA ENROUTE']:
        match = re.search(header, full_text, re.MULTILINE)
        if match and match.start() < cutoff_idx:
            cutoff_idx = match.start()

    # 2. EXTRACT RELEVANT ICAOs (Only from the Regular Airport Zone)
    regular_text = full_text[:cutoff_idx]
    icao_set = set()
    airport_regex = r'\b([A-Z]{4})\s*/\s*[A-Z]{3,4}\b'
    loc_matches = re.findall(airport_regex, regular_text)
    if loc_matches:
        valid_matches = [m for m in loc_matches if m not in fp_set]
        icao_set.update(valid_matches)
    icao_list = list(icao_set)

    # 3. PRE-FLIGHT SCAN (FAST TRACK OPTIMIZATION)
    pending_notams = set()
    for match in re.finditer(r'^\s*([A-Z0-9]{2,8}/[0-9]{2})\s+VALID:\s+([0-9]{10})', full_text, re.MULTILINE):
        notam_id = match.group(1)

        if match.start() >= cutoff_idx:
            continue  # FIR/Enroute zone, skip FAA fetch entirely

        preceding_text = full_text[:match.start()]
        boundaries = re.findall(r'(?:\+{4,}[^\n]+\+{4,}|={2,}[^\n]+={2,}|^-{4,}$)', preceding_text, re.MULTILINE)
        last_boundary = boundaries[-1].upper() if boundaries else ""

        is_company = "COMPANY" in last_boundary or notam_id.startswith("CO")
        is_u_type = notam_id.startswith("U")

        if notam_id in blacklist_dict or is_company or is_u_type:
            continue
        if notam_id in known_dict or notam_id in unknown_cache:
            continue

        pending_notams.add(notam_id)

    # 4. CONDITIONAL FAA FETCH
    bulk_faa_data = {}
    if pending_notams:
        if icao_list:
            ui_status.write(f"🔍 Found {len(pending_notams)} unknown NOTAMs. Fetching {len(icao_list)} target ICAOs...")
            bulk_faa_data = fetch_bulk_faa_data(icao_list, ui_status)
        else:
            ui_status.warning("⚠️ Unknown NOTAMs found, but no valid target ICAOs detected to query FAA.")
    else:
        ui_status.write("⚡ FAST TRACK: All Regular NOTAMs are Known, Blacklisted, or Cached. Skipping FAA API!")

    # 5. MAIN TAGGING LOOP
    for match in re.finditer(r'^\s*([A-Z0-9]{2,8}/[0-9]{2})\s+VALID:\s+([0-9]{10})', full_text, re.MULTILINE):
        notam_id = match.group(1)
        valid_str = match.group(2)

        if notam_id in blacklist_dict:
            continue

        age_int, age_str = get_age_data(valid_str)

        preceding_text = full_text[:match.start()]

        loc_matches_local = [m for m in re.findall(airport_regex, preceding_text) if m not in fp_set]
        icao_code = loc_matches_local[-1] if loc_matches_local else "UNK"

        boundaries = re.findall(r'(?:\+{4,}[^\n]+\+{4,}|={2,}[^\n]+={2,}|^-{4,}$)', preceding_text, re.MULTILINE)
        last_boundary = boundaries[-1].upper() if boundaries else ""

        is_company = "COMPANY" in last_boundary or notam_id.startswith("CO")
        is_u_type = notam_id.startswith("U")
        is_fir_or_enroute = match.start() >= cutoff_idx

        # COMPANY OR FIR ZONE NOTAMS: Only tag if < 8 days old, else leave blank
        if is_company or is_u_type or is_fir_or_enroute:
            if age_int < 8:
                tags_for_pdf[notam_id] = "[NEW THIS WEEK]"
            continue

        # --- REGULAR AIRPORT NOTAMS (Constant 13-character locked width formatting) ---
        if notam_id in known_dict:
            type_tag = known_dict[notam_id]
            tags_for_pdf[notam_id] = f"[{type_tag.ljust(4)} | {age_str.rjust(4)}]"
            continue

        if notam_id in unknown_cache:
            tags_for_pdf[notam_id] = f"[UNKN | {age_str.rjust(4)}]"
            continue

        # PASS 4: The FAA Engine using universal hash & Dynamic Fingerprint Fallback
        api_notam_id = normalize_notam_id(notam_id)
        match_found = False
        type_tag = ""

        # 4A. Direct ID Match
        if api_notam_id in bulk_faa_data:
            type_tag = bulk_faa_data[api_notam_id]['tag']
            match_found = True
        else:
            # 4B. Dynamic Text Fingerprint Match (Middle & Tail)
            body_start = match.end()
            next_match = re.search(r'^\s*[A-Z0-9]{2,8}/[0-9]{2}\s+VALID:', full_text[body_start:], re.MULTILINE)
            body_end = body_start + next_match.start() if next_match else len(full_text)
            raw_pdf_body = full_text[body_start:body_end]

            pdf_clean = re.sub(r'[^A-Z0-9]', '', raw_pdf_body.upper())
            if pdf_clean.endswith("EST"): pdf_clean = pdf_clean[:-3]
            if pdf_clean.endswith("UFN"): pdf_clean = pdf_clean[:-3]

            chunks_to_test = []
            if len(pdf_clean) < 25:
                # For extremely short NOTAMs, just grab the tail end
                chunks_to_test.append(pdf_clean[-12:])
            else:
                # Grab the last 25 chars (dodges LIDO headers)
                chunks_to_test.append(pdf_clean[-25:])
                # Grab 25 chars from the exact middle
                mid_idx = len(pdf_clean) // 2
                chunks_to_test.append(pdf_clean[mid_idx:mid_idx + 25])

            for faa_id, faa_data in bulk_faa_data.items():
                faa_text = faa_data['clean_text']
                # If either the middle or tail chunk exists perfectly in the FAA text, it's a match
                if any(chunk in faa_text for chunk in chunks_to_test if len(chunk) >= 10):
                    type_tag = faa_data['tag']
                    match_found = True
                    break

        if match_found:
            new_known[notam_id] = (type_tag, icao_code)
            tags_for_pdf[notam_id] = f"[{type_tag.ljust(4)} | {age_str.rjust(4)}]"
            continue

        # PASS 5: The Blind-Spot
        tags_for_pdf[notam_id] = f"[UNKN | {age_str.rjust(4)}]"
        unknown_notams_to_log[notam_id] = icao_code

    if unknown_notams_to_log:
        log_unknown_notams(unknown_notams_to_log)

    return tags_for_pdf, new_known, "Success"


# --- CORE LOGIC: FILTER & REBUILD ---
def process_and_filter_briefing(extracted_text, blacklist_dict, processed_tags):
    lines = extracted_text.split('\n')
    output_lines = []
    filtered_this_flight = []
    is_omitted = False
    flight_info = "LIDO BRIEFING"

    for line in lines:
        clean_line = line.strip()

        # --- LIDO PAGINATION SHREDDER ---
        # Destroys repeating header lines like "BR 024/12 FEB/TPE-SEA" but saves the first one found
        if re.match(r'^[A-Z0-9]{2,3}\s+\d{1,4}/\d{2}\s+[A-Z]{3}/[A-Z]{3}-[A-Z]{3}$', clean_line):
            if flight_info == "LIDO BRIEFING":
                flight_info = clean_line
            continue
        # Destroys the "Page X" lines
        if re.match(r'^Page\s+\d+$', clean_line):
            continue

        match = re.match(r'^\s*([A-Z0-9]{2,8}/[0-9]{2})\s+VALID:', line)
        if match:
            notam_id = match.group(1)

            if notam_id in blacklist_dict:
                is_omitted = True
                item_tuple = blacklist_dict[notam_id]
                if item_tuple not in filtered_this_flight:
                    filtered_this_flight.append(item_tuple)
                continue
            else:
                is_omitted = False
                if notam_id in processed_tags:
                    tag = processed_tags[notam_id]
                    # Adjusted padding to 68 to nudge the tags 2 chars to the left
                    base_line = line.rstrip()
                    if len(base_line) < 68:
                        line = f"{base_line.ljust(68)} {tag}"
                    else:
                        line = f"{base_line} {tag}"
                output_lines.append(line)
                continue

        is_airport_or_fir = bool(re.match(r'^\s*([A-Z]{4}\s*/\s*[A-Z]{3,4}\b|[A-Z]{4}\s+.*FIR\b)', line))
        is_major_boundary = line.strip().startswith('==') or '[Airport WX List]' in line or is_airport_or_fir

        if is_major_boundary:
            is_omitted = False
            if filtered_this_flight:
                output_lines.append("\n" + "-" * 82)
                output_lines.append("OMITTED NOTAMs (FILTERED)".center(82))
                output_lines.append("-" * 82 + "\n")

                filtered_this_flight.sort(key=lambda x: x[0])
                cols = 4
                rows = math.ceil(len(filtered_this_flight) / cols)

                col_max_id = [0] * cols
                for c in range(cols):
                    for r in range(rows):
                        idx = c * rows + r
                        if idx < len(filtered_this_flight):
                            col_max_id[c] = max(col_max_id[c], len(filtered_this_flight[idx][0]))

                for r in range(rows):
                    row_items = []
                    for c in range(cols):
                        idx = c * rows + r
                        if idx < len(filtered_this_flight):
                            n_id, loc, tag = filtered_this_flight[idx]

                            clean_id = n_id.strip()
                            clean_loc = loc.strip()
                            clean_tag = tag.strip()

                            id_padded = clean_id.ljust(col_max_id[c] + 1)
                            loc_padded = clean_loc.ljust(4)
                            tag_str = f"[{clean_tag[:4].ljust(4)}]"

                            combined = f"{id_padded}{loc_padded}{tag_str}"

                            col_width = col_max_id[c] + 1 + 4 + 6
                            row_items.append(combined.ljust(col_width))

                    output_lines.append(" ".join(row_items))

                output_lines.append("\n" + "-" * 82 + "\n")
                filtered_this_flight = []

            output_lines.append(line)
            continue

        if line.strip().startswith('----') or line.strip().startswith('++++'):
            is_omitted = False
            output_lines.append(line)
            continue

        if not is_omitted:
            output_lines.append(line)

    return "\n".join(output_lines), flight_info


# --- PDF GENERATOR ---
def create_monospaced_pdf(text_content, flight_info):
    doc = fitz.open()

    # A4 Dimensions
    page_width = 595
    page_height = 842
    margin_x = 20
    margin_y = 30
    header_h = 24

    def draw_page_template(page, page_num):
        # Header Rect (Light Grey Fill)
        hdr_rect = fitz.Rect(margin_x, margin_y, page_width - margin_x, margin_y + header_h)
        page.draw_rect(hdr_rect, color=(0, 0, 0), fill=(0.9, 0.9, 0.9), width=1)

        # Body Rect (Transparent Fill)
        body_rect = fitz.Rect(margin_x, margin_y + header_h, page_width - margin_x, page_height - margin_y)
        page.draw_rect(body_rect, color=(0, 0, 0), width=1)

        # Center the Title: courier is monospaced, width is approx 60% of font size
        title_width = len(flight_info) * (14 * 0.6)
        title_x = (page_width - title_width) / 2

        # Header Text (Bold)
        page.insert_text((title_x, margin_y + 16), flight_info, fontname="courier-bold", fontsize=14, color=(0, 0, 0))
        page.insert_text((page_width - margin_x - 70, margin_y + 16), f"Page {page_num}", fontname="courier-bold",
                         fontsize=13, color=(0, 0, 0))

    page_num = 1
    page = doc.new_page(width=page_width, height=page_height)
    draw_page_template(page, page_num)

    y_start = margin_y + header_h + 16
    y_pos = y_start
    line_height = 14
    text_margin_left = margin_x + 6
    lines = text_content.split('\n')

    for line in lines:
        if y_pos > page_height - margin_y - 15:
            page_num += 1
            page = doc.new_page(width=page_width, height=page_height)
            draw_page_template(page, page_num)
            y_pos = y_start

        # Body text now explicitly forced to Bold
        page.insert_text((text_margin_left, y_pos), line, fontname="courier-bold", fontsize=11, color=(0, 0, 0))
        y_pos += line_height

    out_pdf = io.BytesIO()
    doc.save(out_pdf)
    return out_pdf.getvalue()


# --- MAIN INTERFACE ---
st.title("✂️ NOTAM Filter & Cropper")

blacklist = load_blacklist()
known_notams = load_and_prune_known_notams()
unknown_cache_set = load_unknown_notams_cache()
false_positives_db = load_false_positives()

with st.sidebar:
    st.header("⚙️ Configuration (Cloud Sync)")
    with st.expander(f"View Loaded Blacklist ({len(blacklist)} items)", expanded=False):
        if blacklist:
            for key, val in blacklist.items():
                st.code(val, language="text")
        else:
            st.warning("No blacklist items found in the cloud.")

    with st.expander(f"View Known Cache ({len(known_notams)} items)", expanded=False):
        if known_notams:
            for key, val in known_notams.items():
                st.code(f"{key} [{val}]", language="text")
        else:
            st.warning("Cache is empty. Will build on first run.")

st.markdown("### Upload LIDO Briefing to Filter & Reflow")
uploaded_file = st.file_uploader("Drop your PDF here", type="pdf")

if uploaded_file:
    try:
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        full_text = ""
        for page in doc:
            full_text += page.get_text() + "\n"

        if st.button("Apply Filters & Generate Clean PDF", type="primary"):
            # REPLACED SPINNER WITH EXPANDABLE STATUS CONTAINER
            with st.status("🤖 Booting Engine & querying FAA...", expanded=True) as status_ui:
                # Restored the new_known dictionary push so your cache builds automatically
                tags_for_pdf, new_known, status_msg = analyze_notams(full_text, blacklist, known_notams,
                                                                     unknown_cache_set, false_positives_db, status_ui)

                if tags_for_pdf is not None:
                    status_ui.update(label="✅ FAA Fetch & Tagging Complete!", state="complete", expanded=False)
                    save_new_known_notams(new_known)

                    with st.spinner("✂️ Cropping blacklist and reflowing text..."):
                        processed_text, flight_info_str = process_and_filter_briefing(full_text, blacklist,
                                                                                      tags_for_pdf)
                        final_pdf_bytes = create_monospaced_pdf(processed_text, flight_info_str)

                    st.success("✅ Briefing successfully filtered and reflowed!")
                    st.download_button(
                        label="📤 Download Cleaned Briefing",
                        data=final_pdf_bytes,
                        file_name=f"Filtered_{uploaded_file.name}",
                        mime="application/pdf",
                        type="primary",
                        use_container_width=True
                    )

                    b64_pdf = base64.b64encode(final_pdf_bytes).decode('utf-8')
                    pdf_display_html = f'''
                    <iframe src="data:application/pdf;base64,{b64_pdf}" width="100%" height="800" type="application/pdf" style="border: 1px solid #ccc; border-radius: 5px; margin-top: 10px;"></iframe>
                    '''
                    st.markdown(pdf_display_html, unsafe_allow_html=True)
                else:
                    status_ui.update(label="⚠️ Engine Failed", state="error")
                    st.error(status_msg)

    except Exception as e:
        st.error(f"Error processing document: {e}")