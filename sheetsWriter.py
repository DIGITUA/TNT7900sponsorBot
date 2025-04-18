# sheets_writer.py

import asyncio
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import sponsor1__vars

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = sponsor1__vars.SheetID1
SHEET_NAME = 'Sheet1'
SHEET_HEADER = ['Company Name', 'Timestamp', 'Email', 'Phone', 'Source URL']

write_lock = asyncio.Semaphore(1)
WRITE_LIMIT = 60  # writes per minute
SECONDS_BETWEEN_WRITES = 60 / WRITE_LIMIT

def init_sheet_client():
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    
    if not sheet.get_all_values():
        sheet.append_row(SHEET_HEADER)
    return sheet

async def safe_append_row(sheet, row, retries=3, delay=1.5):
    for attempt in range(retries):
        try:
            async with write_lock:
                sheet.append_row(row, value_input_option='RAW')
                await asyncio.sleep(SECONDS_BETWEEN_WRITES)
            return True
        except Exception as e:
            print(f"[!] Google Sheets write failed (attempt {attempt+1}): {e}")
            await asyncio.sleep(delay)
    return False