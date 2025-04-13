import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime
import re
import sponsor1__vars
import asyncio
import aiohttp
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import requests
import pandas as pd
from bs4 import BeautifulSoup
import re
import tldextract
from urllib.parse import urljoin, urlparse
import os
from datetime import datetime

sponsors = [sponsor1__vars.sponsorList1, sponsor1__vars.sponsorList2]
chosenSponsor = 1
outputFileName = "sponsorship_info_auto"
finalOutput = ""
chosenSource = ""
if chosenSponsor >= len(sponsors):
    finalOutput = outputFileName
    chosenSource = sponsors[0]
else:
    finalOutput = outputFileName+sponsors[chosenSponsor]
    chosenSource = sponsors[chosenSponsor]
print("chosenSource: ",chosenSource, "finalOutput: ", finalOutput)

recent_entries = set()

def populate_recent_entries_from_sheet(sheet):
    print("⏳ Preloading previous entries into memory...")
    try:
        all_rows = sheet.get_all_values()
        for row in all_rows[1:]:  # Skip header
            key = tuple(cell.strip().lower() for cell in row[:4])
            recent_entries.add(key)
        print(f"✅ Loaded {len(recent_entries)} recent entries.")
    except Exception as e:
        print(f"[!] Could not preload recent entries: {e}")

# --------- GOOGLE SHEETS SETUP ---------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = sponsor1__vars.SheetID  # <- Replace this
SHEET_NAME = 'Sheet1'  # Tab name
SHEET_HEADER = ['Company Name', 'URLs', 'Phones', 'Emails', 'Timestamp']

SHEET = None
def init_sheet_client():
    global SHEET
    if SHEET:
        return SHEET
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    #sheet.clear()
    sheet.append_row(SHEET_HEADER)

    SHEET = sheet
    return sheet

sheet = init_sheet_client()
populate_recent_entries_from_sheet(sheet)

# --- GLOBAL WRITE RATE LIMITER ---
WRITE_LIMIT = 60  # per minute per user
SECONDS_BETWEEN_WRITES = 60 / WRITE_LIMIT
write_lock = asyncio.Semaphore(1)  # 1 write at a time

async def safe_append_row(sheet, row, retries=2, delay=1.5):
    key = tuple(row[:4])  # Check Company Name, URL, Phones, Emails

    if key in recent_entries:
        print(f"⚠️ Duplicate detected (immediate): {key}")
        return False

    for attempt in range(retries):
        try:
            async with write_lock:
                sheet.append_row(row, value_input_option='RAW')
                recent_entries.add(key)
                if len(recent_entries) > 1000:
                    # avoid memory bloat
                    recent_entries.pop()

                await asyncio.sleep(SECONDS_BETWEEN_WRITES)
            return True
        except Exception as e:
            print(f"[!] Google Sheets write failed (attempt {attempt+1}): {e}")
            await asyncio.sleep(delay)
    return False

# ----------------------
# User Info Configuration
# ----------------------
applicant_name = "Kaitlyn Chao"
applicant_email = "frc7900@gmail.com"
applicant_phone = "(262) 822-9274"
applicant_group = "TNT 7900 / Racine Robotics Booster Club"
bio_file_path = "bio.txt"
applicant_city = "Racine"
applicant_state = "Wisconsin"
applicant_country = "US"
applicant_ZIP = "53406"

# ----------------------
# Known field types (HTML5 + standard)
# ----------------------
KNOWN_FIELD_TYPES = {
    "text", "email", "tel", "textarea", "select", "url", "checkbox", "radio",
    "password", "date", "number", "hidden", "file", "submit", "button"
}

# ----------------------
# Load the text content from the .txt file
# ----------------------
def load_applicant_info(txt_path):
    if os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        return "[Bio file not found]"

# ----------------------
# Save HTML for future analysis
# ----------------------
def save_html_snapshot(html, url, unknown_template_notes=""):
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.find_all("form")

    if not forms:
        print("❌ No form found to save.")
        return

    form = forms[0]  # You can change this if you want to handle multiple forms
    clean_form_html = form.prettify()

    if unknown_template_notes:
        clean_form_html += "\n\n<!-- Developer Notes: Suggested Handlers for Unknown Fields -->\n"
        clean_form_html += unknown_template_notes

    # Sanitize filename based on URL and timestamp
    safe_url = re.sub(r"[^\w]+", "_", url)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"form_snapshot_{safe_url}_{timestamp}.html"
    filepath = os.path.join("unhandled_forms", filename)

    os.makedirs("unhandled_forms", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(clean_form_html)

    print(f"📂 Saved cleaned form HTML to: {filepath}")


# ----------------------
# Generate suggestion templates for unknown fields
# ----------------------
def generate_suggestion_template(field):
    return f"""
# TODO: Handle input field '{field['name']}' of type '{field['type']}'
# Example HTML element: <{field['type']} name="{field['name']}" placeholder="{field['placeholder']}">
# Suggested Implementation:
# if field_type == "{field['type']}":
#     # e.g., Create a custom handler (slider, dropdown, date picker, etc.)
#     payload['{field['name']}'] = 'YOUR_VALUE_HERE'
"""

# ----------------------
# Scrape HTML content from a URL
# ----------------------
def get_html(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"[!] Error fetching HTML: {e}")
        return None

# ----------------------
# Parse and extract form details
# ----------------------
def parse_form_fields(html):
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.find_all("form")

    if not forms:
        print("❌ No form found on the page.")
        return [], []

    print(f"✅ Found {len(forms)} form(s). Extracting fields from the first one...\n")
    form = forms[0]
    inputs = form.find_all(["input", "textarea", "select"])

    fields = []
    unknowns = []

    for field in inputs:
        name = field.get("name") or field.get("id") or "[unnamed]"
        field_type = field.get("type") or field.name
        placeholder = field.get("placeholder", "")
        field_info = {
            "name": name,
            "type": field_type,
            "placeholder": placeholder
        }
        fields.append(field_info)

        if field_type not in KNOWN_FIELD_TYPES:
            unknowns.append(field_info)

    return fields, unknowns

# ----------------------
# Main Logic
# ----------------------

async def process_url(url, company_name=None):
    print(f"\n🌐 Processing: {url}")
    html = get_html(url)
    if not html:
        print(f"⚠️ Could not fetch HTML for: {url}")
        return

    form_fields, unknown_fields = parse_form_fields(html)
    if not form_fields:
        print(f"🚫 No form fields found on: {url}")
        return

    print("📝 Form Fields Found:")
    for field in form_fields:
        print(f" - {field['name']} ({field['type']}), placeholder: '{field['placeholder']}'")

    if unknown_fields:
        print("\n⚠️ Unknown or uncommon field types detected!")
        for field in unknown_fields:
            print(f" - {field['name']} ({field['type']})")
        notes = "\n".join([generate_suggestion_template(f) for f in unknown_fields])
        save_html_snapshot(html, url, notes)

        print("\n🛠 Suggested Template(s) for Handling Unknown Fields:")
        for field in unknown_fields:
            print(generate_suggestion_template(field))

    print("\n📄 Applicant Info:")
    print(f"Name: {applicant_name}")
    print(f"Email: {applicant_email}")
    print(f"Phone: {applicant_phone}")
    print(f"Group: {applicant_group}")
    print("\n📘 Bio or Proposal:")
    print(load_applicant_info(bio_file_path))

    # Example of storing result in sheet (can be expanded with parsed phones/emails etc.)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await safe_append_row(sheet, [
        company_name or "[Unknown]",
        url,
        "",  # Placeholder for phones
        "",  # Placeholder for emails
        timestamp
    ])

async def run_all():
    print("\n🔁 Starting form search across sheet URLs...")
    all_rows = sheet.get_all_values()[1:]  # Skip header
    tasks = []
    for row in all_rows:
        if len(row) >= 2:
            company = row[0]
            url = row[1]
            tasks.append(process_url(url, company))
        else:
            print("⚠️ Skipping row with missing data:", row)

    await asyncio.gather(*tasks)
    print("\n✅ All URLs processed.")

if __name__ == "__main__":
    asyncio.run(run_all())

"""
def main():
    url = input("Enter the URL to check: ").strip()
    html = get_html(url)
    if not html:
        return

    form_fields, unknown_fields = parse_form_fields(html)
    if not form_fields:
        return

    print("📝 Form Fields Found:")
    for field in form_fields:
        print(f" - {field['name']} ({field['type']}), placeholder: '{field['placeholder']}'")

    if unknown_fields:
        print("\n⚠️ Unknown or uncommon field types detected!")
        for field in unknown_fields:
            print(f" - {field['name']} ({field['type']})")

        save_html_snapshot(html, url)

        print("\n🛠 Suggested Template(s) for Handling Unknown Fields:")
        for field in unknown_fields:
            print(generate_suggestion_template(field))

    print("\n📄 Applicant Info:")
    print(f"Name: {applicant_name}")
    print(f"Email: {applicant_email}")
    print(f"Phone: {applicant_phone}")
    print(f"Group: {applicant_group}")
    print("\n📘 Bio or Proposal:")
    print(load_applicant_info(bio_file_path))

if __name__ == "__main__":
    main()
"""