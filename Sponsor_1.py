# Import necessary libraries
import asyncio  # For asynchronous programming
import aiohttp  # For asynchronous HTTP requests
import re  # For regular expressions (text matching)
import time  # For time-related functions (e.g., sleep)
from bs4 import BeautifulSoup  # For parsing HTML and XML
from datetime import datetime  # For working with dates and times
import gspread  # For interacting with Google Sheets
from google.oauth2.service_account import Credentials  # For Google API authentication
import requests  # For making HTTP requests (synchronous)
import pandas as pd  # For data manipulation and analysis (especially CSV files)
import tldextract  # For extracting top-level domain, domain, and subdomain from URLs
from urllib.parse import urljoin, urlparse  # For URL manipulation
import os  # For interacting with the operating system (e.g., file paths)
import sponsor1__vars  # Assuming this is a custom module for storing variables like API keys or sponsor lists

# --- Configuration ---
# List of sponsor lists (presumably defined in sponsor1__vars)
sponsors = [sponsor1__vars.sponsorList1, sponsor1__vars.sponsorList2]
chosenSponsor = 1  # Index to select a specific sponsor list
outputFileName = "sponsorship_info_auto"  # Base name for the output file
finalOutput = ""  # Will hold the final output file name
chosenSource = ""  # Will hold the path to the chosen sponsor list CSV

# Determine the final output file name and chosen source based on 'chosenSponsor'
if chosenSponsor >= len(sponsors):
    finalOutput = outputFileName
    chosenSource = sponsors[0]  # Default to the first sponsor list if index is out of bounds
else:
    finalOutput = outputFileName + sponsors[chosenSponsor] # Append sponsor list identifier to filename
    chosenSource = sponsors[chosenSponsor]
print("chosenSource: ", chosenSource, "finalOutput: ", finalOutput)

# --- Global Variables for Sheet Deduplication and Rate Limiting ---
write_counter = 0  # Counter for writes (not actively used in the provided snippet for rate limiting, but declared)
recent_entries = set()  # A set to store recently added entries to Google Sheets for quick duplicate checking
dedup_counter = 0  # Counter for triggering periodic full sheet deduplication

# --- Google Sheets Functions ---

def remove_sheet_duplicates(sheet):
    """
    Scans a Google Sheet for duplicate rows based on the first four columns
    (Company Name, URLs, Phones, Emails) and removes them.
    Also removes rows containing blacklisted keywords in the URL.
    """
    print("🧹 Scanning for and removing duplicates...")
    try:
        all_rows = sheet.get_all_values()  # Get all data from the sheet
        if not all_rows:
            print("Sheet is empty.")
            return

        header = all_rows[0]  # Assume the first row is the header
        data = all_rows[1:]  # The rest is data

        seen_keys = set()  # To keep track of unique rows encountered
        duplicates_indices = []  # To store indices of rows to be deleted

        # Keywords that, if present in a URL, mark the row for removal
        blacklist_keywords = ['job', 'careers', 'news', 'media', 'press']

        for i, row in enumerate(data):
            # Normalize the first 4 cells for comparison (strip whitespace, lowercase)
            normalized_row = [cell.strip().lower() for cell in row[:4]]
            url = normalized_row[1] if len(normalized_row) > 1 else ""  # Extract URL

            key = tuple(normalized_row)  # Create a unique key from the normalized cells

            # Check if the key has been seen or if the URL contains blacklisted words
            if key in seen_keys or any(bad in url for bad in blacklist_keywords):
                duplicates_indices.append(i + 2)  # gspread is 1-indexed, and header is row 1
            else:
                seen_keys.add(key)

        if duplicates_indices:
            print(f"🗑 Removing {len(duplicates_indices)} duplicates...")
            # Delete rows in reverse order to avoid index shifting issues
            for i in sorted(duplicates_indices, reverse=True):
                sheet.delete_rows(i)
        else:
            print("✅ No duplicates found.")

    except Exception as e:
        print(f"[!] Failed during duplicate removal: {e}")

def populate_recent_entries_from_sheet(sheet):
    """
    Loads existing entries from the Google Sheet into the `recent_entries` set.
    This helps in preventing immediate duplicate writes without needing to read the sheet every time.
    """
    print("⏳ Preloading previous entries into memory...")
    try:
        all_rows = sheet.get_all_values()
        for row in all_rows[1:]:  # Skip header row
            # Create a key from the first 4 cells (normalized)
            key = tuple(cell.strip().lower() for cell in row[:4])
            recent_entries.add(key)
        print(f"✅ Loaded {len(recent_entries)} recent entries.")
    except Exception as e:
        print(f"[!] Could not preload recent entries: {e}")

# --- Google Sheets Client Initialization ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]  # Permissions scope for Google Sheets API
SHEET_ID = sponsor1__vars.SheetID  # The ID of the Google Sheet (from sponsor1__vars)
SHEET_NAME = 'Sheet1'  # The name of the specific tab/worksheet
SHEET_HEADER = ['Company Name', 'URLs', 'Phones', 'Emails', 'Timestamp']  # Header row for the sheet

SHEET = None  # Global variable to hold the sheet object

def init_sheet_client():
    """
    Initializes and returns a gspread client authorized to access the specified Google Sheet.
    If the sheet is empty, it appends the header row.
    """
    global SHEET
    if SHEET:  # If already initialized, return the existing client
        return SHEET
    # Load credentials from a JSON file (ensure 'credentials.json' is in the same directory or provide the correct path)
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    client = gspread.authorize(creds)  # Authorize the client
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)  # Open the specific worksheet

    # Check if sheet is empty and add header if needed (currently commented out)
    # sheet.clear() # This would clear the sheet on every run if uncommented
    # sheet.append_row(SHEET_HEADER) # This would add a header every run if sheet.clear() isn't used carefully

    SHEET = sheet  # Store the initialized sheet object globally
    return sheet

# Initialize the sheet client and populate recent entries
sheet = init_sheet_client()
populate_recent_entries_from_sheet(sheet) # Load existing data to prevent immediate duplicates

# --- Rate Limiting for Google Sheets Writes ---
WRITE_LIMIT = 60  # Maximum writes per minute per user (Google Sheets API quota)
SECONDS_BETWEEN_WRITES = 60 / WRITE_LIMIT  # Calculate delay needed between writes
write_lock = asyncio.Semaphore(1)  # A semaphore to ensure only one write operation happens at a time (mutual exclusion)

async def safe_append_row(sheet, row, retries=2, delay=1.5):
    """
    Appends a row to the Google Sheet safely, checking for immediate duplicates
    in `recent_entries` and handling potential API errors with retries.
    Uses an asyncio.Semaphore to limit concurrent writes.
    """
    # Create a key from the row data to check against `recent_entries`
    key = tuple(cell.strip().lower() for cell in row[:4]) # Normalize key for comparison

    if key in recent_entries:
        print(f"⚠️ Duplicate detected (immediate, from recent_entries set): {key}")
        return False  # Don't write if it's a known recent entry

    for attempt in range(retries):
        try:
            async with write_lock:  # Acquire the lock before writing
                sheet.append_row(row, value_input_option='RAW')  # Append the row
                recent_entries.add(key)  # Add the new entry to the set of recent entries
                # Simple mechanism to prevent recent_entries from growing indefinitely
                if len(recent_entries) > 1000: # If set grows too large
                    recent_entries.pop() # Remove an arbitrary element (not ideal for LRU, but simple)

                await asyncio.sleep(SECONDS_BETWEEN_WRITES)  # Wait to respect rate limits
            return True  # Successfully appended
        except Exception as e:
            print(f"[!] Google Sheets write failed (attempt {attempt + 1}): {e}")
            await asyncio.sleep(delay)  # Wait before retrying
    return False # Failed to append after all retries

# --- DuckDuckGo Search Function ---
def duckduckgo_search(query, max_results=10):
    """
    Performs a search on DuckDuckGo (HTML version) and returns a list of result URLs.
    """
    print(f"🦆 Performing DuckDuckGo search for: {query}")
    url = "https://html.duckduckgo.com/html/"  # URL for the HTML version of DDG
    headers = {'User-Agent': 'Mozilla/5.0'}  # Standard User-Agent to mimic a browser
    data = {'q': query}  # Search query parameter
    
    try:
        # Make a POST request to DuckDuckGo
        res = requests.post(url, headers=headers, data=data, timeout=10) # Added timeout
        res.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
        soup = BeautifulSoup(res.text, "html.parser")  # Parse the HTML response
    except requests.exceptions.RequestException as e:
        print(f"[!] DuckDuckGo search request failed: {e}")
        return []

    results = []
    # Find all <a> tags with an 'href' attribute (links) in the search results area
    # This selector might need adjustment if DDG's HTML structure changes.
    # The previous selector 'soup.find_all("a", href=True)' was too broad.
    # A more specific selector would target result links, e.g., links within a certain class or ID.
    # For now, keeping it simple but adding a check for common non-result links.
    for result_link in soup.select('div.results .result__a, div.results .result__url'): # Example of a more specific selector
        href = result_link.get("href") if result_link.name == 'a' else result_link.text.strip()

        if href and href.startswith("http"): # and "duckduckgo.com/y.js" not in href: (y.js is a redirect script)
            # Further filter out DuckDuckGo's own utility links if necessary
            parsed_url = urlparse(href)
            if "duckduckgo.com" not in parsed_url.netloc: # Avoid DDG's own links unless they are actual results
                results.append(href)
                if len(results) >= max_results:
                    break
    print(f"✅ Found {len(results)} results from DuckDuckGo.")
    return results

# --- Asynchronous Web Scraper ---
# Keywords to identify business-related names (currently not used in process_company directly for name extraction)
business_keywords = ["Inc", "LLC", "Ltd", "Corp", "Company", "Co", "Incorporated", "Corporation"]
business_pattern = re.compile(r"\b(?:[A-Z][a-zA-Z&,\.\-\s]+)\s+(?:" + "|".join(business_keywords) + r")\b")

seen_companies = set()  # Set to store names of companies already processed or found in the sheet

async def load_existing_companies(sheet):
    """
    Loads company names from the first column of the Google Sheet into the `seen_companies` set.
    This is used to avoid reprocessing companies that are already in the sheet.
    """
    print("🔁 Loading existing companies from sheet...")
    try:
        all_rows = sheet.get_all_values()
        for row in all_rows[1:]:  # Skip header row
            if len(row) > 0 and row[0]: # Check if row is not empty and has a company name
                seen_companies.add(row[0].strip().lower()) # Add normalized company name
        print(f"✅ Loaded {len(seen_companies)} existing company names.")
    except Exception as e:
        print(f"[!] Failed to load existing company data from sheet: {e}")

seen_lock = asyncio.Lock()  # Lock for ensuring thread-safe access to shared resources like `seen_companies` or when writing to sheet

def find_sitemap(base_url):
    """
    Tries to find a sitemap URL for a given base URL.
    Checks common sitemap paths.
    """
    sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap", "/sitemap.php", "/robots.txt"] # Added robots.txt
    print(f"🔎 Searching for sitemap for {base_url}...")
    for path in sitemap_paths:
        sitemap_url = urljoin(base_url, path)
        try:
            res = requests.get(sitemap_url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
            res.raise_for_status()
            if path == "/robots.txt": # If it's robots.txt, look for Sitemap directive
                for line in res.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_loc = line.split(":", 1)[1].strip()
                        print(f"🗺️ Found sitemap in robots.txt: {sitemap_loc}")
                        return sitemap_loc # Return the sitemap URL from robots.txt
            elif "xml" in path and ("</urlset>" in res.text or "<sitemapindex" in res.text): # Check for XML sitemap content
                print(f"🗺️ Found sitemap: {sitemap_url}")
                return sitemap_url
        except requests.exceptions.RequestException as e:
            # print(f"   - No sitemap at {sitemap_url} ({e})") # Verbose logging
            continue
    print(f"   - No sitemap found for {base_url}")
    return None

def find_contact_pages(base_url):
    """
    Scrapes a base URL to find links that might lead to contact, sponsorship,
    or partnership pages.
    """
    print(f"🔗 Searching for contact/sponsorship pages on {base_url}...")
    try:
        res = requests.get(base_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'}) # Increased timeout
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        contact_links = set() # Use a set to store unique links
        # Keywords to identify relevant links
        link_keywords = ["contact", "sponsor", "partner", "apply", "nonprofit", "501(c)(3)", "grant", "foundation", "youth", "first frc", "about", "community", "social responsibility"]
        
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].lower()
            text = a_tag.get_text().lower()
            # Check if keywords are in the link's href or text
            if any(kw in href or kw in text for kw in link_keywords):
                full_url = urljoin(base_url, a_tag["href"]) # Construct absolute URL
                # Basic filter to avoid mailto, tel, and JavaScript links here
                if not full_url.startswith(("mailto:", "tel:", "javascript:")):
                    contact_links.add(full_url)
        
        print(f"   Found {len(contact_links)} potential contact/sponsorship pages.")
        return list(contact_links)
    except requests.exceptions.RequestException as e:
        print(f"[!] Failed to fetch {base_url} for contact pages: {e}")
        return []
    except Exception as e:
        print(f"[!] Error parsing {base_url} for contact pages: {e}")
        return []


def extract_info_from_page(url, page_content):
    """
    Extracts email addresses and phone numbers from the given HTML page content.
    """
    soup = BeautifulSoup(page_content, "html.parser")
    text = soup.get_text()  # Get all text from the page

    # Regex for emails (improved to be slightly more robust)
    emails = set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text))
    
    # Regex for phone numbers (North American focus, can be generalized)
    # This regex is a bit more general for various phone formats.
    phones = set(re.findall(r"\(?\+?[0-9]{0,3}\)?[-.\s]?\(?\d{2,5}\)?[-.\s]?\d{2,5}[-.\s]?\d{2,5}", text))
    
    # Filter out clearly invalid phone numbers (e.g., too short, too many zeros)
    # Example: filter numbers that are less than 7 digits after cleaning
    valid_phones = set()
    for phone in phones:
        digits = re.sub(r'\D', '', phone) # Remove non-digits
        if 7 <= len(digits) <= 15: # Basic length check
            valid_phones.add(phone.strip())

    return {
        "url": url,
        "emails": list(emails),
        "phones": list(valid_phones),
        "scraped_at": datetime.now().isoformat()
    }


def get_main_domain(url):
    """
    Extracts the main domain (e.g., 'https://example.com') from a URL.
    """
    try:
        ext = tldextract.extract(url)
        if ext.domain and ext.suffix:
            return f"https://{ext.domain}.{ext.suffix}"
        else: # Fallback for URLs like 'localhost' or IPs if needed, though tldextract handles many cases
            parsed_url = urlparse(url)
            return f"{parsed_url.scheme}://{parsed_url.netloc}" if parsed_url.netloc else None
    except Exception as e:
        print(f"[!] Error extracting domain from {url}: {e}")
        return None

def generate_queries(company_name):
    """
    Generates a list of search queries for a given company name.
    """
    return [
        f"{company_name} official site",
        f"{company_name} contact information",
        f"{company_name} corporate social responsibility",
        f"{company_name} community support",
        f"{company_name} foundation grants",
        f"{company_name} sponsorship request",
        f"{company_name} how to apply for sponsorship",
        f"{company_name} email phone contact page", # Generic
    ]

MAX_RETRIES = 2  # Max retries for scraping a single page
failed_pages = {}  # Dictionary to track failed page scrape attempts

async def process_company(name, session, previous_url=None):
    """
    Processes a single company:
    1. Finds its official website (uses DuckDuckGo if not provided).
    2. Finds sitemap and contact/sponsorship pages.
    3. Scrapes these pages for contact information (emails, phones).
    4. Appends valid new information to the Google Sheet.
    """
    # Normalize company name for internal processing and checking `seen_companies`
    normalized_name_key = name.strip().lower()
    async with seen_lock: # Ensure thread-safe check and addition to seen_companies
        if normalized_name_key in seen_companies:
            print(f"⏭ Company '{name}' already processed or in sheet (based on initial load). Skipping further processing.")
            return None # Skip if already seen

    base_url = None
    if previous_url:
        base_url = get_main_domain(previous_url)
    
    if not base_url: # If no previous URL or it's invalid, search for the official site
        print(f"🕵️ No previous URL for '{name}', searching for official site...")
        for query in generate_queries(name):
            search_results = duckduckgo_search(query, max_results=3) # Limit search results
            for result_url in search_results:
                potential_base_url = get_main_domain(result_url)
                if potential_base_url:
                    # Add a basic check: does the domain name contain parts of the company name?
                    # This is a heuristic and might need refinement.
                    company_name_parts = [part.lower() for part in name.split() if len(part) > 2] # Get significant parts of company name
                    if any(part in potential_base_url.lower() for part in company_name_parts):
                        base_url = potential_base_url
                        print(f"🌐 Tentatively found site via search for '{name}': {base_url} (from query: '{query}')")
                        break
                    else:
                        print(f"   - Search result {potential_base_url} for '{name}' did not seem to match company name closely.")
            if base_url:
                break
    
    if not base_url:
        print(f"❌ Could not determine official site for '{name}' after searching. Skipping.")
        return None

    print(f"🌐 Processing site: {base_url} for company: {name}")
    # sitemap_url = find_sitemap(base_url) # Sitemap finding can be slow, consider if essential for every run
    # print(f"📄 Sitemap: {sitemap_url or 'Not found'}")

    pages_to_scrape = set([base_url]) # Start with the base URL
    potential_contact_pages = find_contact_pages(base_url)
    if potential_contact_pages:
        pages_to_scrape.update(potential_contact_pages[:5]) # Limit number of contact pages to scrape initially

    print(f"🔗 Will attempt to scrape up to {len(pages_to_scrape)} pages for '{name}'...")

    collected_company_info = {"company": name, "urls": set(), "emails": set(), "phones": set()}
    
    for page_url in pages_to_scrape:
        if page_url in failed_pages and failed_pages[page_url] >= MAX_RETRIES:
            print(f"   ⚠️ Skipping {page_url} — too many previous failures.")
            continue

        # Skip blacklisted pages (e.g., job portals, news sections if not desired)
        blacklist_page_keywords = ['job', 'career', 'news', 'media', 'press', 'login', 'signin', 'shop', 'product']
        if any(bad_kw in page_url.lower() for bad_kw in blacklist_page_keywords):
            # Allow if "contact" or "sponsor" is also in URL, as it might be relevant despite other keywords
            if not any(good_kw in page_url.lower() for good_kw in ["contact", "sponsor", "about", "community"]):
                print(f"   🚫 Skipping blacklisted-like page: {page_url}")
                continue
        
        print(f"   📄 Scraping page: {page_url}")
        try:
            async with session.get(page_url, timeout=10, allow_redirects=True) as response: # Increased timeout, allow redirects
                if response.status == 200:
                    page_content = await response.text()
                    info = extract_info_from_page(str(response.url), page_content) # Use actual URL after redirects

                    if info["emails"] or info["phones"]:
                        print(f"      Found on {info['url']}: Emails: {info['emails']}, Phones: {info['phones']}")
                        collected_company_info["urls"].add(info['url'])
                        collected_company_info["emails"].update(info["emails"])
                        collected_company_info["phones"].update(info["phones"])
                    else:
                        print(f"      No new contacts found on {info['url']}.")
                else:
                    print(f"   ❌ Failed to fetch {page_url} - Status: {response.status}")
                    failed_pages[page_url] = failed_pages.get(page_url, 0) + 1

        except asyncio.TimeoutError:
            print(f"   ❌ Timeout scraping {page_url}")
            failed_pages[page_url] = failed_pages.get(page_url, 0) + 1
        except aiohttp.ClientError as e: # Catch more specific aiohttp errors
            print(f"   ❌ ClientError scraping {page_url}: {e}")
            failed_pages[page_url] = failed_pages.get(page_url, 0) + 1
        except Exception as e:
            failed_pages[page_url] = failed_pages.get(page_url, 0) + 1
            print(f"   ❌ Unknown error scraping {page_url} ({failed_pages[page_url]}/{MAX_RETRIES}): {e}")
            continue
    
    # After processing all pages for the company, if info was found, write to sheet
    if collected_company_info["emails"] or collected_company_info["phones"]:
        global dedup_counter
        dedup_counter += 1
        if dedup_counter >= 10: # Periodically run full sheet deduplication
            dedup_counter = 0
            remove_sheet_duplicates(sheet) # Call the deduplication function

        timestamp = datetime.now().isoformat()
        row_to_append = [
            name,
            ", ".join(sorted(list(collected_company_info["urls"]))), # Join multiple URLs
            ", ".join(sorted(list(collected_company_info["phones"]))), # Join multiple phones
            ", ".join(sorted(list(collected_company_info["emails"]))), # Join multiple emails
            timestamp
        ]
        
        # Use the safe_append_row which includes the recent_entries check
        if await safe_append_row(sheet, row_to_append):
            print(f"   ✅ Appended info for '{name}' to Google Sheet.")
            async with seen_lock: # Ensure thread-safe addition
                 seen_companies.add(normalized_name_key) # Add to seen_companies only after successful write
            return collected_company_info # Return the collected info
        else:
            print(f"   ⚠️ Failed to append info for '{name}' to sheet (possibly a duplicate or write error).")
            # Even if write fails, if it was due to recent_entries check, consider it "seen"
            if tuple(cell.strip().lower() for cell in row_to_append[:4]) in recent_entries:
                 async with seen_lock:
                    seen_companies.add(normalized_name_key)
            return None
    else:
        print(f"ℹ️ No contact information found for '{name}' after scraping.")
        # Optionally, add even companies with no found info to seen_companies to avoid re-processing
        # async with seen_lock:
        #     seen_companies.add(normalized_name_key)
        return None

# --- Main Entry Point ---
async def main(csv_file_path, deepen_search=False): # Renamed csv_file to csv_file_path for clarity
    """
    Main function to orchestrate the scraping process.
    Reads company names from a CSV file, processes each company,
    and saves results to another CSV and Google Sheets.
    """
    global sheet # Ensure sheet is initialized
    if not sheet:
        sheet = init_sheet_client()

    # Load existing company names from the Google Sheet to avoid reprocessing
    await load_existing_companies(sheet)

    all_scraped_data = [] # To store data for the final CSV output

    print(f"📂 Loading company names from CSV: {csv_file_path}")
    try:
        df = pd.read_csv(csv_file_path)
        # Assuming the company names are in the first column
        if df.empty or df.columns.empty:
            print(f"[!] CSV file '{csv_file_path}' is empty or has no header.")
            return
        company_names_from_csv = df.iloc[:, 0].dropna().astype(str).unique().tolist() # Get unique names
    except FileNotFoundError:
        print(f"[!] CSV file not found: {csv_file_path}")
        return
    except Exception as e:
        print(f"[!] Failed to load or parse CSV '{csv_file_path}': {e}")
        return

    total_companies = len(company_names_from_csv)
    print(f"✅ Loaded {total_companies} unique company names from CSV.")

    # Create an aiohttp ClientSession to be reused for all requests in this main function
    async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'}) as session:
        tasks = []
        for i, company_name in enumerate(company_names_from_csv):
            company_name_stripped = company_name.strip()
            if not company_name_stripped:
                print(f"[{i + 1}/{total_companies}] ⏭ Skipping empty company name.")
                continue

            # Check against `seen_companies` (which now includes sheet data and successfully processed items)
            normalized_name_key = company_name_stripped.lower()
            async with seen_lock: # Thread-safe check
                if normalized_name_key in seen_companies:
                    print(f"[{i + 1}/{total_companies}] ⏭ Already processed or in sheet: {company_name_stripped}")
                    continue
            
            print(f"[{i + 1}/{total_companies}] 🔍 Queueing processing for: {company_name_stripped}")
            # Create a task for each company processing
            # Pass the shared session to process_company
            tasks.append(process_company(company_name_stripped, session))

        # Run tasks concurrently
        # asyncio.gather will collect all results. Filter out None results.
        results = await asyncio.gather(*tasks)
        for result in results:
            if result: # If process_company returned data (not None)
                all_scraped_data.append(result)

    # This 'deepen' logic seems to re-process based on an output CSV, which might be redundant
    # if the initial processing is thorough. It also reads a different CSV.
    # Consider if this is still needed or how it fits with the main flow.
    # If 'sponsorship_info_auto.csv' is the output of a *previous* run, this makes sense.
    if deepen_search and os.path.exists(finalOutput + ".csv"): # Check if the output CSV exists
        print(f"🔁 Running deeper dive into previous results from '{finalOutput}.csv'...")
        try:
            df_deepen = pd.read_csv(finalOutput + ".csv")
            # Group by company name to get previously found URLs
            # This assumes 'company' and 'url' columns exist in 'sponsorship_info_auto.csv'
            if 'company' in df_deepen.columns and 'url' in df_deepen.columns:
                grouped = df_deepen.groupby("company")
                deepen_tasks = []
                async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'}) as deepen_session:
                    for name, group in grouped:
                        name_stripped = name.strip()
                        normalized_name_key = name_stripped.lower()
                        async with seen_lock: # Check if already processed in this run or from sheet
                            if normalized_name_key in seen_companies:
                                print(f"⏭ Deep-dive: '{name_stripped}' already handled in current run. Skipping.")
                                continue
                        
                        # Get a primary URL from the group to start the deep dive
                        known_urls = group["url"].dropna().tolist()
                        best_url_for_deepen = known_urls[0] if known_urls else None
                        
                        print(f"\n🔍 Deep-dive processing: {name_stripped} (using URL: {best_url_for_deepen or 'N/A'})")
                        deepen_tasks.append(process_company(name_stripped, deepen_session, previous_url=best_url_for_deepen))
                    
                    deepen_results = await asyncio.gather(*deepen_tasks)
                    for result in deepen_results:
                        if result:
                            all_scraped_data.append(result)
            else:
                print(f"[!] 'company' or 'url' column not found in '{finalOutput}.csv' for deepening search.")
        except Exception as e:
            print(f"[!] Error during deep dive processing: {e}")

    # Save all collected data to the final CSV
    if all_scraped_data:
        # Consolidate data for CSV: each company might have multiple URLs, emails, phones.
        # The current `all_scraped_data` structure is a list of dicts like:
        # {"company": name, "urls": set(), "emails": set(), "phones": set()}
        
        # Create a DataFrame for easier CSV writing
        # Normalize the structure for DataFrame (e.g., join sets into strings)
        final_df_data = []
        for item in all_scraped_data:
            final_df_data.append({
                "Company Name": item["company"],
                "URLs": ", ".join(sorted(list(item["urls"]))),
                "Phones": ", ".join(sorted(list(item["phones"]))),
                "Emails": ", ".join(sorted(list(item["emails"]))),
                "Timestamp": datetime.now().isoformat() # Add a general timestamp for the CSV row
            })
        
        if final_df_data:
            result_df = pd.DataFrame(final_df_data)
            # Ensure SHEET_HEADER matches the DataFrame columns if writing directly
            # Or select/rename columns in result_df to match SHEET_HEADER
            output_csv_path = finalOutput + ".csv"
            result_df.to_csv(output_csv_path, index=False, columns=SHEET_HEADER[:4]+['Timestamp']) # Match sheet header as much as possible
            print(f"\n✅ Results compiled and saved to {output_csv_path}")
        else:
            print("\nℹ️ No new data was scraped to save to CSV.")
    else:
        print("\nℹ️ No data was scraped in this run.")

    print("🏁🏁🏁 Done with all companies. Performing final duplicate check on sheet. 🏁🏁🏁")
    remove_sheet_duplicates(sheet) # Final cleanup of the Google Sheet

if __name__ == "__main__":
    # Example: To run this script, you would typically call it from the command line
    # or set `chosenSource` appropriately.
    # `chosenSource` should be the path to your input CSV file.
    
    # Ensure `chosenSource` (input CSV file path) and `finalOutput` (base for output CSV) are correctly set.
    # The `sponsors` list and `chosenSponsor` logic at the top determine these.
    
    # Make sure 'credentials.json' is present for Google Sheets API access.
    # Make sure 'sponsor1__vars.py' contains necessary variables like 'SheetID', 'sponsorList1', etc.
    
    print(f"🚀 Starting sponsorship information gathering script...")
    print(f"Input CSV: {chosenSource}")
    print(f"Output CSV base name: {finalOutput}")
    print(f"Google Sheet ID: {SHEET_ID}")

    # Run the main asynchronous function
    # The `deepen` parameter can be set to True or False
    asyncio.run(main(csv_file_path=chosenSource, deepen_search=False))
    
    print("\n✅ Script finished.")