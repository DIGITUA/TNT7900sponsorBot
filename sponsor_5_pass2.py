import asyncio
import aiohttp # Asynchronous HTTP client
from bs4 import BeautifulSoup # For parsing HTML
import gspread # For interacting with Google Sheets
from google.oauth2.service_account import Credentials # For Google API authentication
# Assuming 'done.sponsor1__vars' is a module containing configuration like SheetID and keywords
# If it's meant to be just 'sponsor1__vars', adjust the import.
try:
    import sponsor1__vars # Standard import
except ImportError:
    # Fallback if the 'done' prefix is intentional for some reason or a typo
    try:
        import done.sponsor1__vars as sponsor1__vars
        print("Warning: Imported configuration from 'done.sponsor1__vars'. Ensure this is intended.")
    except ImportError:
        print("Error: Could not import 'sponsor1__vars' or 'done.sponsor1__vars'. Place configuration in 'sponsor1__vars.py'.")
        exit() # Exit if config is missing

from urllib.parse import urljoin, urlparse # For URL validation and manipulation

# --- Google Sheet Configuration ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"] # Permissions for Google Sheets API
SHEET_ID = sponsor1__vars.SheetID # Your Google Sheet ID from config
SHEET_NAME = "Sheet1"  # The name of the worksheet to read URLs from and write results to
START_ROW_INDEX = 2  # 1-based index for sheet rows, so 2 means skip header

# --- Form Identification Keywords & Logic ---
# Keywords to identify if a form is likely related to sponsorships or grants.
# These should ideally be comprehensive and context-aware.
SPONSORSHIP_KEYWORDS = getattr(sponsor1__vars, 'SPONSORSHIP_KEYWORDS', [
    'sponsorship', 'grant', 'funding', 'donation', 'support', 'partner', 'apply', 
    'nonprofit', '501(c)(3)', 'foundation', 'community', 'outreach', 'youth', 'education', 'frc'
]) # Get from vars or use a default

def get_form_elements(soup: BeautifulSoup) -> list:
    """Extracts all <form> elements from a BeautifulSoup soup object."""
    return soup.find_all('form')

def get_form_input_fields(form_soup: BeautifulSoup) -> list:
    """Extracts all <input>, <textarea>, and <select> elements from a form soup."""
    return form_soup.find_all(['input', 'textarea', 'select'])

def is_form_likely_sponsorship_related(form_soup: BeautifulSoup) -> bool:
    """
    Analyzes a form to determine if it's likely for sponsorships, grants, or contact.
    Checks form attributes, field names, placeholders, and surrounding text.
    """
    form_text_content = form_soup.get_text(" ", strip=True).lower() # All text within the form
    
    # Check attributes of the form tag itself (e.g., id, class)
    form_attributes = str(form_soup.attrs).lower()
    if any(keyword.lower() in form_attributes for keyword in SPONSORSHIP_KEYWORDS):
        return True

    fields = get_form_input_fields(form_soup)
    field_details_text = ""
    for field in fields:
        field_details_text += field.get('name', '').lower() + " "
        field_details_text += field.get('id', '').lower() + " "
        field_details_text += field.get('placeholder', '').lower() + " "
        # Check labels associated with fields (if any)
        label = form_soup.find('label', {'for': field.get('id')})
        if label:
            field_details_text += label.get_text(strip=True).lower() + " "

    combined_text_to_search = form_text_content + " " + field_details_text
    
    # More sophisticated check: require multiple distinct keywords or specific combinations
    # For now, a simple "any keyword" check:
    return any(keyword.lower() in combined_text_to_search for keyword in SPONSORSHIP_KEYWORDS)


def is_form_a_search_form(form_soup: BeautifulSoup) -> bool:
    """Determines if a form is primarily a site search form."""
    fields = get_form_input_fields(form_soup)
    for f in fields:
        if f.get('type', '').lower() == 'search' or \
           any(search_kw in f.get('name', '').lower() for search_kw in ['search', 'query', 'q']) or \
           any(search_kw in f.get('id', '').lower() for search_kw in ['search', 'query']) or \
           any(search_kw in f.get('placeholder', '').lower() for search_kw in ['search...', 'find']):
            return True
    # Check form's role attribute
    if form_soup.get('role', '').lower() == 'search':
        return True
    return False

def is_form_relevant_for_analysis(form_soup: BeautifulSoup) -> bool:
    """
    Combines checks: is it a sponsorship-related form and NOT a search form?
    """
    if not form_soup: return False # Should not happen if called after find_all('form')
    
    # Basic heuristics to ignore very small or likely irrelevant forms (e.g., login, newsletter)
    fields = get_form_input_fields(form_soup)
    if len(fields) < 2 and not any(ftype in str(fields).lower() for ftype in ['textarea']): # Very few fields, no textarea
        # Check for common irrelevant form types based on field names/ids
        field_names_ids = " ".join([f.get('name','').lower() + f.get('id','').lower() for f in fields])
        if any(kw in field_names_ids for kw in ['login', 'email_signup', 'newsletter', 'password', 'username']):
            if not is_form_likely_sponsorship_related(form_soup): # Unless it also has strong sponsorship keywords
                 return False # Likely a simple login/signup, not a detailed contact/application

    is_sponsorship = is_form_likely_sponsorship_related(form_soup)
    is_search = is_form_a_search_form(form_soup)
    
    return is_sponsorship and not is_search

# --- Google Sheet Client Initialization ---
def init_google_sheet_client():
    """Initializes and returns an authorized gspread client and the specific worksheet."""
    try:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        client = gspread.authorize(creds)
        worksheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        print(f"✅ Successfully connected to Google Sheet: '{SHEET_NAME}'")
        return worksheet
    except FileNotFoundError:
        print("[!] Error: 'credentials.json' not found. Place your Google Service Account key file here.")
        raise
    except Exception as e:
        print(f"[!] Failed to initialize Google Sheet client: {e}")
        raise

# Initialize sheet client globally or pass it around. Global for this script's structure.
try:
    google_sheet = init_google_sheet_client()
    all_sheet_rows = google_sheet.get_all_values() # Fetch all data once
    print(f"📖 Loaded {len(all_sheet_rows)} rows from the sheet.")
except Exception:
    print("❌ Critical error initializing Google Sheet. Exiting.")
    # In a real application, handle this more gracefully or exit.
    # For this script, if sheet init fails, it can't proceed.
    google_sheet = None 
    all_sheet_rows = []
    # exit(1) # Or raise an error to stop execution


# --- Asynchronous Form Detection on Web Pages ---
async def check_page_for_forms(session: aiohttp.ClientSession, page_url: str) -> tuple[bool, bool]:
    """
    Fetches a URL and checks its content for any forms and specifically relevant sponsorship forms.

    Args:
        session: The aiohttp ClientSession to use for requests.
        page_url: The URL of the page to check.

    Returns:
        A tuple: (found_any_form: bool, found_relevant_sponsorship_form: bool)
    """
    found_any_form_flag = False
    found_relevant_sponsorship_form_flag = False
    
    try:
        # Standard headers to mimic a browser
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"}
        async with session.get(page_url, timeout=15, headers=headers, allow_redirects=True) as response:
            if response.status == 200:
                html_content = await response.text()
                soup = BeautifulSoup(html_content, "html.parser") # Use html.parser for broader compatibility
                
                forms_on_page = get_form_elements(soup)
                if forms_on_page:
                    found_any_form_flag = True
                    for form_element in forms_on_page:
                        if is_form_relevant_for_analysis(form_element):
                            found_relevant_sponsorship_form_flag = True
                            break # Found one relevant form, no need to check others on this page
            else:
                print(f"   ⚠️ Failed to fetch {page_url} - Status: {response.status}")
            return found_any_form_flag, found_relevant_sponsorship_form_flag
            
    except asyncio.TimeoutError:
        print(f"   Timeout fetching {page_url}")
    except aiohttp.ClientError as e: # Catches various client-side errors (DNS, connection, etc.)
        print(f"   ClientError fetching {page_url}: {str(e)[:100]}") # Print first 100 chars of error
    except Exception as e:
        print(f"   [!] Unexpected error processing {page_url}: {e}")
    
    return found_any_form_flag, found_relevant_sponsorship_form_flag # Default to false if errors


# --- Main Asynchronous Task ---
async def process_sheet_urls_and_update():
    """
    Iterates through URLs in the Google Sheet (from `all_sheet_rows`),
    checks each for forms, and prepares batch updates for the sheet.
    """
    if not google_sheet or not all_sheet_rows:
        print("❌ Cannot proceed: Google Sheet not initialized or no data loaded.")
        return

    # Use an aiohttp ClientSession for managing connections efficiently
    async with aiohttp.ClientSession() as http_session:
        batch_updates_for_sheet = [] # List to hold data for gspread.batch_update

        # Iterate through rows, starting from START_ROW_INDEX (skip headers)
        # all_sheet_rows is 0-indexed, START_ROW_INDEX is 1-based for user display/config
        for row_index_0based, row_data in enumerate(all_sheet_rows):
            current_sheet_row_num = row_index_0based + 1 # 1-based sheet row number
            
            if current_sheet_row_num < START_ROW_INDEX: # Skip header rows as configured
                continue

            # Assuming URL is in the second column (index 1)
            if len(row_data) < 2 or not row_data[1]:
                print(f"⏭️ Skipping row {current_sheet_row_num}: URL column is missing or empty.")
                # Optionally mark this row in the sheet
                # batch_updates_for_sheet.append({
                #     'range': f'G{current_sheet_row_num}:H{current_sheet_row_num}', # Assuming G and H are target columns
                #     'values': [["N/A", "URL Missing"]],
                # })
                continue

            url_to_check = row_data[1].strip()

            # Basic URL validation
            parsed_url = urlparse(url_to_check)
            if not parsed_url.scheme or not parsed_url.netloc: # Must have scheme (http/https) and domain
                print(f"❌ Invalid URL format at row {current_sheet_row_num}: {url_to_check}")
                batch_updates_for_sheet.append({
                    'range': f'G{current_sheet_row_num}:H{current_sheet_row_num}', # Columns for "Any Form?" and "Sponsorship Form?"
                    'values': [["❌", f"Invalid URL"]],
                })
                continue
            
            print(f"🔍 ({current_sheet_row_num}/{len(all_sheet_rows)}) Checking URL: {url_to_check}")
            
            # Perform the asynchronous check for forms
            found_any, found_relevant = await check_page_for_forms(http_session, url_to_check)
            
            # Prepare the update for this row
            # Column G for "Any Form Found?", Column H for "Relevant Sponsorship Form Found?" (example)
            # Adjust column letters as per your sheet structure.
            update_values = [["✅" if found_any else "❌", "✅" if found_relevant else "❌"]]
            batch_updates_for_sheet.append({
                'range': f'G{current_sheet_row_num}:H{current_sheet_row_num}', # Target cells for this row
                'values': update_values,
            })

            # Google Sheets API has write quotas (e.g., 60 writes/min/user).
            # Batching is good, but also avoid hitting API too rapidly if processing is very fast.
            # A small sleep can help if many URLs are processed very quickly, though aiohttp handles concurrency.
            await asyncio.sleep(0.2) # Small delay between initiating checks, actual requests are concurrent

            # Periodically update the sheet in batches to avoid one massive update at the end
            # and to save progress in case of interruption.
            if len(batch_updates_for_sheet) >= 20: # Update every 20 rows, for example
                print(f"💾 Writing batch of {len(batch_updates_for_sheet)} updates to Google Sheet...")
                try:
                    google_sheet.batch_update(batch_updates_for_sheet)
                    batch_updates_for_sheet.clear() # Clear the list after successful update
                    print("   Batch written successfully.")
                    await asyncio.sleep(1) # Pause briefly after a batch write
                except gspread.exceptions.APIError as e:
                    print(f"   [!] Google Sheets API error during batch update: {e}")
                    print(f"   Will retry remaining updates later.") # Keep items in batch for next attempt
                    # Consider more robust error handling here, like retrying the batch.
                except Exception as e:
                    print(f"   [!] Unexpected error during batch update: {e}")


        # After the loop, write any remaining updates
        if batch_updates_for_sheet:
            print(f"💾 Writing final batch of {len(batch_updates_for_sheet)} updates to Google Sheet...")
            try:
                google_sheet.batch_update(batch_updates_for_sheet)
                print("   Final batch written successfully.")
            except Exception as e:
                print(f"   [!] Error writing final batch to Google Sheet: {e}")
        
        print("🏁 All URLs processed.")

# --- Script Execution Start ---
if __name__ == "__main__":
    if google_sheet: # Only run if sheet initialization was successful
        print("🚀 Starting script to check URLs from Google Sheet for forms...")
        asyncio.run(process_sheet_urls_and_update())
        print("✅ Script finished.")
    else:
        print("❌ Script cannot run because Google Sheet initialization failed.")