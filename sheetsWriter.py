# sheets_writer.py

import asyncio
import gspread # For interacting with Google Sheets
from google.oauth2.service_account import Credentials # For Google API authentication
from datetime import datetime # For timestamping (though not directly used in append_row here)
import sponsor1__vars # Assuming this is a custom module for storing variables like Sheet ID

# --- Configuration ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"] # Permissions scope for Google Sheets API
SHEET_ID = sponsor1__vars.SheetID1 # The ID of the Google Sheet (from sponsor1__vars)
SHEET_NAME = 'Sheet1'  # The name of the specific tab/worksheet
SHEET_HEADER = ['Company Name', 'Timestamp', 'Email', 'Phone', 'Source URL'] # Example header

# --- Rate Limiting for Google Sheets Writes ---
write_lock = asyncio.Semaphore(1)  # A semaphore to ensure only one write operation happens at a time (mutual exclusion)
WRITE_LIMIT = 60  # Maximum writes per minute allowed by Google Sheets API (per user, per project)
SECONDS_BETWEEN_WRITES = 60.0 / WRITE_LIMIT  # Calculate delay needed between writes to stay within limits

def init_sheet_client():
    """
    Initializes and returns a gspread client authorized to access the specified Google Sheet.
    If the sheet appears empty (no values), it appends the defined header row.
    """
    try:
        # Load credentials from a JSON file (ensure 'credentials.json' is in the same directory or provide correct path)
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        client = gspread.authorize(creds) # Authorize the client
        sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME) # Open the specific worksheet
        
        # Check if the sheet is empty and add header if needed
        if not sheet.get_all_values(): # get_all_values() can be slow for large sheets; consider checking cell A1 instead
            print(f"Sheet '{SHEET_NAME}' appears empty. Appending header row.")
            sheet.append_row(SHEET_HEADER, value_input_option='USER_ENTERED') # USER_ENTERED treats data like it's typed in
        return sheet
    except Exception as e:
        print(f"[!] Failed to initialize Google Sheet client: {e}")
        raise # Reraise the exception to signal failure to the caller

async def safe_append_row(sheet, row_data: list, retries: int = 3, delay_seconds: float = 1.5):
    """
    Appends a row to the Google Sheet safely, with rate limiting and retries.

    Args:
        sheet: The gspread worksheet object.
        row_data: A list of values representing the row to append.
        retries: Number of times to retry on failure.
        delay_seconds: Seconds to wait between retries.

    Returns:
        True if the row was appended successfully, False otherwise.
    """
    for attempt in range(retries):
        try:
            async with write_lock: # Acquire the semaphore before writing
                # Append the row; 'RAW' means input values are not parsed by Google Sheets.
                # 'USER_ENTERED' would have Google Sheets parse them (e.g., for dates, formulas).
                sheet.append_row(row_data, value_input_option='RAW') 
                # Wait after a successful write to respect the overall rate limit.
                await asyncio.sleep(SECONDS_BETWEEN_WRITES) 
            print(f"✅ Successfully appended row: {row_data[:2]}...") # Log part of the row
            return True
        except gspread.exceptions.APIError as e: # Catch specific gspread API errors
            print(f"[!] Google Sheets API error (attempt {attempt + 1}/{retries}): {e}")
            # Specific handling for rate limit exceeded errors (HTTP 429)
            if e.response.status_code == 429:
                print("   Rate limit exceeded. Waiting longer before retry...")
                # Wait for a longer period if rate limited, e.g., the 'Retry-After' header if available, or a fixed longer delay.
                # For simplicity, using an increased fixed delay here.
                await asyncio.sleep(delay_seconds * (attempt + 2) * 5) # Exponentially increase delay more significantly
            else:
                await asyncio.sleep(delay_seconds * (attempt + 1)) # Standard delay for other API errors
        except Exception as e: # Catch other potential exceptions
            print(f"[!] Generic error during Google Sheets write (attempt {attempt + 1}/{retries}): {e}")
            await asyncio.sleep(delay_seconds * (attempt + 1)) # Standard delay

    print(f"❌ Failed to append row after {retries} retries: {row_data[:2]}...")
    return False

# --- Example Usage (if this script were to be run directly) ---
# This part would typically be in another script that uses this sheetsWriter module.
if __name__ == "__main__":
    async def example_main():
        try:
            sheet = init_sheet_client() # Initialize the sheet
        except Exception as e:
            print(f"Could not start example: {e}")
            return

        # Example data to write
        example_rows = [
            ["Example Company A", datetime.now().isoformat(), "contact@examplea.com", "123-456-7890", "http://examplea.com"],
            ["Example Company B", datetime.now().isoformat(), "info@exampleb.com", "987-654-3210", "http://exampleb.com"],
            # Add more rows as needed
        ]

        print(f"Attempting to write {len(example_rows)} example rows to sheet '{SHEET_NAME}'...")
        
        tasks = []
        for row in example_rows:
            tasks.append(safe_append_row(sheet, row))
        
        results = await asyncio.gather(*tasks) # Run all append operations concurrently (respecting the semaphore)
        
        successful_writes = sum(1 for r in results if r)
        print(f"\nFinished example run. {successful_writes}/{len(example_rows)} rows written successfully.")

    asyncio.run(example_main())