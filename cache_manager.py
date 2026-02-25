import sys
import warnings
import traceback

warnings.simplefilter(action='ignore', category=FutureWarning)
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

import datetime
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection
import ctypes

# --- CONFIGURATION ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/1hG8BDR9R1Wz4t9nU-lCy82sVIT8-oGfhyy7NT1mbbss/edit"


def manage_cache():
    print("[STATUS] Starting Local Cache Manager...")

    try:
        conn = st.connection("gsheets", type=GSheetsConnection)

        print("[STATUS] Fetching Unknown_NOTAMs from cloud...")
        df_unknown = conn.read(spreadsheet=SHEET_URL, worksheet="Unknown_NOTAMs", ttl=0)
        print("[STATUS] Fetching Known_NOTAMs from cloud...")
        df_known = conn.read(spreadsheet=SHEET_URL, worksheet="Known_NOTAMs", ttl=0)

        # Ensure the columns exist from the new layout
        if "ID" not in df_unknown.columns or "Type" not in df_unknown.columns:
            print("[ERROR] 'ID' or 'Type' column missing in Unknown_NOTAMs.")
            input("Press Enter to exit...")
            return

        # Sanitize inputs
        df_unknown["ID"] = df_unknown["ID"].fillna("").astype(str)
        df_unknown["Type"] = df_unknown["Type"].fillna("").astype(str)
        df_unknown["Location"] = df_unknown.get("Location", pd.Series([""] * len(df_unknown))).fillna("").astype(str)

        # 1. Separate Instructions from Data
        instructions_df = df_unknown[df_unknown["ID"].str.startswith("#")].copy()
        data_df = df_unknown[~df_unknown["ID"].str.startswith("#") & (df_unknown["ID"].str.strip() != "")].copy()

        if data_df.empty:
            print("[INFO] No pending or completed NOTAMs found. Exiting.")
            return

        # 2. Filter Completed (has Type) vs Pending (no Type)
        completed_df = data_df[data_df["Type"].str.strip() != ""].copy()
        pending_df = data_df[data_df["Type"].str.strip() == ""].copy()

        if completed_df.empty:
            print("[INFO] No fully tagged NOTAMs to transfer. Exiting.")
            return

        print(f"[STATUS] Found {len(completed_df)} completed entries to transfer. {len(pending_df)} remaining pending.")

        # 3. Format New Entries for Known_NOTAMs (ID, Location, Type, Timestamp)
        completed_df["Type"] = completed_df["Type"].str.replace("[", "", regex=False).str.replace("]", "", regex=False).str.strip()
        new_entries = completed_df[["ID", "Location", "Type"]].copy()

        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        new_entries["Timestamp"] = today_str

        updated_known_df = pd.concat([df_known, new_entries], ignore_index=True)

        # 4. Rebuild the Unknown_NOTAMs tab tightly (Instructions + Pending Data + 15 blank rows)
        blank_data = [["", "", ""] for _ in range(15)]
        blank_df = pd.DataFrame(blank_data, columns=["ID", "Location", "Type"])

        # Ensure column order is strict before concat
        instructions_df = instructions_df[["ID", "Location", "Type"]]
        pending_df = pending_df[["ID", "Location", "Type"]]

        updated_unknown_df = pd.concat([instructions_df, pending_df, blank_df], ignore_index=True)

        # 5. Push to Cloud
        print("[STATUS] Pushing updates to Google Sheets...")
        conn.update(spreadsheet=SHEET_URL, worksheet="Known_NOTAMs", data=updated_known_df)
        conn.update(spreadsheet=SHEET_URL, worksheet="Unknown_NOTAMs", data=updated_unknown_df)

        print(f"\n[DONE] Successfully stamped and moved {len(completed_df)} NOTAM(s) to Known_NOTAMs!")

        # 6. WINDOWS NATIVE POP-UP CONFIRMATION
        popup_message = f"Cache Sync Complete!\n\nMoved {len(completed_df)} NOTAMs to Known_NOTAMs.\nLeft {len(pending_df)} pending."
        ctypes.windll.user32.MessageBoxW(0, popup_message, "Cache Manager Summary", 0x40 | 0x0)

    except Exception as e:
        print(f"[ERROR] A critical error occurred: {e}")
        traceback.print_exc()
        input("Press Enter to exit...")


if __name__ == "__main__":
    manage_cache()