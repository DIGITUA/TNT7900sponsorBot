import asyncio
import aiohttp
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
import done.sponsor1__vars as sponsor1__vars
from urllib.parse import urljoin

# --------- SHEET CONFIG ---------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = sponsor1__vars.SheetID
SHEET_NAME = "Sheet1"
startline = 2

# --------- KEYWORDS & MATCHING LOGIC ---------
SPONSORSHIP_KEYWORDS = sponsor1__vars.SPONSORSHIP_KEYWORDS

def get_form_fields(form):
    return form.find_all(['input', 'textarea', 'select'])

def is_sponsorship_form(form):
    fields = get_form_fields(form)
    field_names = ' '.join([f.get('name', '') + ' ' + f.get('placeholder', '') for f in fields])
    return any(keyword.lower() in field_names.lower() for keyword in SPONSORSHIP_KEYWORDS)

def is_search_form(form):
    return any(
        f.get('type') == 'search' or 'search' in f.get('name', '').lower()
        for f in get_form_fields(form)
    )

def form_is_relevant(form):
    return bool(form) and is_sponsorship_form(form) and not is_search_form(form)

# --------- INIT SHEET ---------
def init_sheet_client():
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

sheet = init_sheet_client()
all_rows = sheet.get_all_values()

# --------- FORM DETECTION ---------
async def check_for_form(session, url):
    try:
        async with session.get(url, timeout=10) as response:
            if response.status != 200:
                return False
            soup = BeautifulSoup(await response.text(), "html.parser")
            return any(form_is_relevant(form) for form in soup.find_all("form"))
    except Exception as e:
        print(f"[!] Failed to fetch {url}: {e}")
        return False

async def check_for_form2(session, url):
    try:
        async with session.get(url, timeout=10) as response:
            if response.status != 200:
                return False
            soup = BeautifulSoup(await response.text(), "html.parser")
            return soup.find("form") is not None
    except Exception as e:
        print(f"[!] Failed to fetch {url}: {e}")
        return False

# --------- MAIN TASK ---------
async def main():
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        updates = []

        for i, row in enumerate(all_rows[1:], start=startline):
            if len(row) < 2:
                continue

            url = row[1].strip()
            row_num = i + 1  # 1-based indexing for Google Sheets

            if not url or not url.startswith("http"):
                print(f"❌ Skipping invalid URL at row {row_num}: {url}")
                updates.append({
                    'range': f'H{row_num}',
                    'values': [["❌"]],
                })
                continue

            print(f"🔍 Checking row {row_num} - {url}")
            basic_form = await check_for_form2(session, url)
            detailed_form = await check_for_form(session, url)

            updates.append({
                'range': f'G{row_num}:H{row_num}',
                'values': [[
                    "✅" if basic_form else "❌",
                    "✅" if detailed_form else "❌",
                    
                ]]
            })

            # To stay under quota limits
            await asyncio.sleep(1)

            # Perform update right after each row
            if updates:
                sheet.batch_update([{
                    "range": u['range'],
                    "values": u['values'],
                    #"priority": u['priority']
                } for u in updates])
                updates.clear()

# --------- RUN ---------
if __name__ == "__main__":
    asyncio.run(main())