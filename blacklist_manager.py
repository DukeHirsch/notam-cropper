import sys
import warnings
import traceback

warnings.simplefilter(action='ignore', category=FutureWarning)
sys.stdout.reconfigure(encoding='utf-8')

import os
import re
import datetime
import requests
import ctypes
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# --- SETUP PATHS & CONFIG ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHEET_URL = "https://docs.google.com/spreadsheets/d/1hG8BDR9R1Wz4t9nU-lCy82sVIT8-oGfhyy7NT1mbbss/edit?gid=101773839#gid=101773839"

# Add your custom ICAO to IATA mappings here. The script handles both directions automatically.
AIRPORT_MAP = {
    "RCSS": "TSA",
    "RCTP": "TPE",
    "LOWW": "VIE",
    "RJTT": "HND",
    "RJAA": "NRT"
}
IATA_TO_ICAO = {v: k for k, v in AIRPORT_MAP.items()}


# --- CORE LOGIC ---
def fetch_public_notam_type(notam_id, location_id):
    """
    Queries the public FAA NOTAM Search API for the exact Q-Code.
    Returns the mapped classification tag, or None if the API fails.
    """
    try:
        url = "https://" + "notams.aim.faa.gov/notamSearch/search"
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': 'https://notams.aim.faa.gov',
            'Referer': 'https://notams.aim.faa.gov/notamSearch/',
            'X-Requested-With': 'XMLHttpRequest',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin'
        }
        data = {'searchType': 0, 'designatorsForLocation': location_id}

        response = requests.post(url, headers=headers, data=data, timeout=15)
        if response.status_code == 200:
            notam_list = response.json().get('notamList', [])
            print(f"      [API] Searched FAA database: {len(notam_list)} NOTAMs found for {location_id}.")
            for n in notam_list:
                raw_msg = n.get('icaoMessage', '') or n.get('traditionalMessage', '')
                if notam_id in raw_msg:
                    q_match = re.search(r'Q\)\s*[^/]+/Q([A-Z]{2})', raw_msg)
                    if q_match:
                        first_letter = q_match.group(1)[0]
                        if first_letter in ['M', 'F']:
                            return 'RWY'
                        elif first_letter in ['L']:
                            return 'TWY'
                        elif first_letter in ['N', 'P', 'I']:
                            return 'NAV'
                        elif first_letter in ['O']:
                            return 'OBS'
                        elif first_letter in ['A', 'R', 'W']:
                            return 'AIR'
                        else:
                            return 'MISC'
    except Exception as e:
        print(f"      [WARNING] API fetch failed for {notam_id}: {e}")

    return None


def maintain_blacklist():
    print("[STATUS] Starting Cloud-Connected Blacklist Manager...")

    try:
        conn = st.connection("gsheets", type=GSheetsConnection)

        # 1. READ GOOGLE SHEETS INBOX
        print("[STATUS] Fetching Blacklist_Inbox from cloud...")
        inbox_df = conn.read(spreadsheet=SHEET_URL, worksheet="Blacklist_Inbox", ttl=0)

        new_items = []
        for index, row in inbox_df.iterrows():
            val_str = str(row.iloc[0]).strip() if len(row) > 0 else ""
            loc_str = str(row.iloc[1]).strip() if len(row) > 1 else "UNK"

            if val_str and val_str.lower() != "nan" and not val_str.startswith(
                    "#") and "INSTRUCTIONS" not in val_str and "ID to be blacklisted" not in val_str:
                new_items.append({"id": val_str, "loc": loc_str, "df_index": index})

        if not new_items:
            print("[INFO] No valid NOTAM IDs found in the Inbox. Exiting.")
            return

        print(f"[STATUS] Found {len(new_items)} new IDs in cloud inbox to process.")

        for item in new_items:
            inbox_df.iat[item["df_index"], 0] = ""
            if inbox_df.shape[1] > 1:
                inbox_df.iat[item["df_index"], 1] = ""

        # 2. READ & PRUNE MAIN BLACKLIST
        print("[STATUS] Fetching Main Blacklist and checking for expired entries...")
        blacklist_df = conn.read(spreadsheet=SHEET_URL, worksheet="Blacklist", ttl=0)

        valid_rows = []
        current_date = datetime.date.today()
        pruned_count = 0

        for _, row in blacklist_df.iterrows():
            if pd.isna(row.get("ID")) or str(row.get("ID")).strip() == "":
                continue

            date_str = str(row.get("Timestamp", "")).strip()
            keep_row = True

            if date_str and date_str != "nan":
                try:
                    entry_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                    if (current_date - entry_date).days > 730:
                        keep_row = False
                        pruned_count += 1
                except ValueError:
                    pass

            if keep_row:
                valid_rows.append(
                    [row.get("ID", ""), row.get("Location", ""), row.get("Type", ""), row.get("Timestamp", "")])

        if pruned_count > 0:
            print(f"[STATUS] Pruned {pruned_count} expired NOTAMs (>2 years old).")

        # 3. TAGGING & ASSEMBLY
        print("[STATUS] Analyzing identifiers and assembling update...")
        added_count = 0
        check_count = 0
        today_str = current_date.strftime("%Y-%m-%d")

        for item in new_items:
            original_id = item["id"]
            raw_loc = item["loc"].upper()

            # A. Resolve Location Code
            if raw_loc in IATA_TO_ICAO:
                api_loc = IATA_TO_ICAO[raw_loc]
                sheet_loc = raw_loc
            elif raw_loc in AIRPORT_MAP:
                api_loc = raw_loc
                sheet_loc = AIRPORT_MAP[raw_loc]
            else:
                api_loc = raw_loc
                sheet_loc = raw_loc

            # B. Convert LIDO NOTAM ID to standard ICAO format (e.g., 1A1234/25 -> A1234/25)
            api_notam_id = re.sub(r'^\d+([A-Za-z])', r'\1', original_id)

            tag = fetch_public_notam_type(api_notam_id, api_loc)

            if tag:
                print(f"   -> [AUTO] {original_id} identified as {tag} (FAA API format: {api_notam_id} for {api_loc})")
            else:
                tag = "CHECK"
                check_count += 1
                print(f"   -> [MANUAL] {original_id} not found in API results for {api_loc}. Marking as CHECK.")

            valid_rows.append([original_id, sheet_loc, tag, today_str])
            added_count += 1

        # 4. UPDATE GOOGLE SHEETS
        updated_blacklist_df = pd.DataFrame(valid_rows, columns=["ID", "Location", "Type", "Timestamp"])
        conn.update(spreadsheet=SHEET_URL, worksheet="Blacklist", data=updated_blacklist_df)
        conn.update(spreadsheet=SHEET_URL, worksheet="Blacklist_Inbox", data=inbox_df)

        print(f"\n[DONE] Successfully migrated {added_count} NOTAMs to the cloud. Wiped Inbox IDs.")

        # 5. WINDOWS NATIVE POP-UP CONFIRMATION
        popup_message = f"Transfer Complete!\n\nFiles Transferred: {added_count}\nManual 'CHECK' Required: {check_count}"
        ctypes.windll.user32.MessageBoxW(0, popup_message, "Blacklist Sync Summary", 0x40 | 0x0)

    except Exception as e:
        print(f"[ERROR] A critical error occurred: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    maintain_blacklist()