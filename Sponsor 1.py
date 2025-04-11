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
import sponsor1__vars

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

write_counter = 0
recent_entries = set()
dedup_counter = 0

def remove_sheet_duplicates(sheet):
    print("🧹 Scanning for and removing duplicates...")
    try:
        all_rows = sheet.get_all_values()
        header = all_rows[0]
        data = all_rows[1:]

        seen = set()
        duplicates_indices = []

        for i, row in enumerate(data):
            key = tuple(row[:4])  # Unique key from first 4 columns
            if key in seen:
                # Record row index for deletion (offset by +2: header + 1-indexed)
                duplicates_indices.append(i + 2)
            else:
                seen.add(key)

        if duplicates_indices:
            print(f"🗑 Removing {len(duplicates_indices)} duplicates...")
            # Delete from bottom to top to avoid shifting
            for i in sorted(duplicates_indices, reverse=True):
                sheet.delete_rows(i)
        else:
            print("✅ No duplicates found.")

    except Exception as e:
        print(f"[!] Failed during duplicate removal: {e}")


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
    
# --------- DUCKDUCKGO SEARCH ---------
def duckduckgo_search(query, max_results=10):
    print("DDG search init")
    url = "https://html.duckduckgo.com/html/"
    headers = {'User-Agent': 'Mozilla/5.0'}
    data = {'q': query}
    res = requests.post(url, headers=headers, data=data, timeout=5)
    soup = BeautifulSoup(res.text, "html.parser")
    print("init done")

    results = []
    print("starting loop over results")
    for result in soup.find_all("a", href=True):
        print("progress:", result)
        href = result["href"]
        print("get link and check if link starts with http")
        if href.startswith("http"):# and "duckduckgo.com/y.js" not in href:
            results.append(href)
            print("match found and adding to results")
            print("checking if we have more than or equal to the num of max results")
            if len(results) >= max_results:
                break
    return results

# --------- ASYNC SCRAPER ---------
business_keywords = ["Inc", "LLC", "Ltd", "Corp", "Company", "Co", "Incorporated", "Corporation"]
business_pattern = re.compile(r"\b(?:[A-Z][a-zA-Z&,\.\-\s]+)\s+(?:" + "|".join(business_keywords) + r")\b")

seen_companies = set()

#---------------------
async def load_existing_companies(sheet):
    print("🔁 Loading existing companies from sheet...")
    try:
        all_rows = sheet.get_all_values()
        for row in all_rows[1:]:  # Skip header
            if len(row) > 0:
                seen_companies.add(row[0].strip())
        print(f"✅ Loaded {len(seen_companies)} existing companies.")
    except Exception as e:
        print(f"[!] Failed to load existing data: {e}")

seen_lock = asyncio.Lock()

def find_sitemap(base_url):
    sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap", "/sitemap.php"]
    for path in sitemap_paths:
	 
        sitemap_url = urljoin(base_url, path)
        try:
            res = requests.get(sitemap_url, timeout=5)
            if res.ok and ("</urlset>" in res.text or "<sitemapindex" in res.text):
                return sitemap_url
        except:
            continue
    return None


def find_contact_pages(base_url):
    try:
        res = requests.get(base_url, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")

        contact_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text().lower()
            if any(kw in href or kw in text for kw in ["contact", "sponsor", "partner", "apply", "Nonprofit", "501(c)(3)", "grant", "foundation", "youth", "FIRST FRC"]):
                full_url = urljoin(base_url, a["href"])
                contact_links.append(full_url)

        return list(set(contact_links))
    except:
        return []


def extract_info_from_page(url):
    try:
        res = requests.get(url, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        text = soup.get_text()

        emails = list(set(re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)))
        phones = list(set(re.findall(r"\+?\(?\d{1,4}\)?[-.\s]?\d{2,5}[-.\s]?\d{2,5}[-.\s]?\d{2,5}", text)))

        return {
            "url": url,
            "emails": emails,
            "phones": phones,
            "scraped_at": datetime.now().isoformat()
        }
    except:
        return {
            "url": url,
            "emails": [],
            "phones": [],
            "scraped_at": datetime.now().isoformat()
        }


def get_main_domain(url):
    ext = tldextract.extract(url)
    return f"https://{ext.domain}.{ext.suffix}"


def generate_queries(company_name):
    return [
        f"{company_name} official site",
        f"{company_name} contact",
        f"{company_name} sponsor request",
        f"{company_name} become a partner",
        f"{company_name} apply for sponsorship",
        f"{company_name} email phone contact page",
    ]

MAX_RETRIES = 2
failed_pages = {}

async def process_company(name, previous_url=None): 
    async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'}) as session:
        if previous_url:
            base_url = get_main_domain(previous_url)
        else:
            base_url = None
            for query in generate_queries(name):
                search_results = duckduckgo_search(query)
                for result in search_results:
                    base_url = get_main_domain(result)
                    if base_url:
                        break
                if base_url:
                    break

        if not base_url:
            print(f"❌ Could not determine official site for {name}")
            return None

        print(f"🌐 Found site: {base_url}")
        sitemap = find_sitemap(base_url)
        print(f"📄 Sitemap: {sitemap or 'Not found'}")

        contact_pages = find_contact_pages(base_url)
        print(f"🔗 Possible pages: {contact_pages[:2]}...")

        collected = []
        for page in contact_pages:
            if failed_pages.get(page, 0) >= MAX_RETRIES:
                print(f"   ⚠️ Skipping {page} — too many failures.")
                continue

            try:
                async with session.get(page, timeout=5) as response:
                    text = await response.text()
                    soup = BeautifulSoup(text, "html.parser")

                    info = extract_info_from_page(page)
                    info["company"] = name
                    url = info["url"]
                    phones = info["phones"]
                    emails = info["emails"]
                    collected.append(info)

                    candidates = contact_pages
                    uploaded = 0

                    async with seen_lock:
                        new_names = [n for n in candidates]
                        for new_name in new_names:
                            global dedup_counter
                            dedup_counter += 1
                            if dedup_counter >= 10:
                                dedup_counter = 0
                                remove_sheet_duplicates(sheet)
                            timestamp = datetime.now().isoformat()
                            if await safe_append_row(sheet, [
                                name,
                                url,
                                ", ".join(phones),
                                ", ".join(emails),
                                timestamp
                            ]):
                                seen_companies.add(new_name)
                                uploaded += 1

                    print(f"   ✅ Scraped — {uploaded} new entries.")

            except Exception as e:
                failed_pages[page] = failed_pages.get(page, 0) + 1
                print(f"   ❌ Error scraping {page} ({failed_pages[page]}/{MAX_RETRIES}): {e}")
                continue

        return collected
    tasks =[]
    await asyncio.gather(*tasks)
        
# --------- ENTRY POINT ---------
async def main(csv_file, deepen = False):
    sheet = init_sheet_client()

    await load_existing_companies(sheet)  # Load deduped list before scraping
    
    df = pd.read_csv(csv_file)
    company_names = df.iloc[:, 0].dropna().tolist()

    #print(duckduckgo_search("Monster Energy official site"))

    all_data = []

    print(f"📂 Loading CSV: {chosenSource}")
    try:
        df = pd.read_csv(chosenSource)
    except Exception as e:
        print(f"[!] Failed to load CSV: {e}")
        return

    total_rows = len(df)
    print(f"✅ Loaded {total_rows} companies from CSV.")
    
    for i, row in df.iterrows():
        company_name = str(row[0]).strip()
        if not company_name:
            continue

        if company_name in seen_companies:
            print(f"[{i+1}/{total_rows}] ⏭ Already seen: {company_name}")
            continue

        print(f"[{i+1}/{total_rows}] 🔍 Processing: {company_name}")
        await process_company(company_name)

    if deepen and os.path.exists("sponsorship_info_auto.csv"):
        print("🔁 Running deeper dive into previous results...")
        df = pd.read_csv("sponsorship_info_auto.csv")
        grouped = df.groupby("company")
        for name, group in grouped:
            known_urls = group["url"].tolist()
            best_url = known_urls[0] if known_urls else None
            print(f"\n🔍 Deep-dive: {name}")
            info_list = await process_company(name, previous_url=best_url)
            if info_list:
                all_data.extend(info_list)
    else:
        df = pd.read_csv(csv_file)
        company_names = df.iloc[:, 0].dropna().tolist()
        for name in company_names:
            print(f"\n🔍 Processing: {name}")
            info_list = await process_company(name)
            if info_list:
                all_data.extend(info_list)

    result_df = pd.DataFrame(all_data)
    result_df.to_csv(finalOutput+".csv", index=False)
    print("\n✅ Results saved to "+finalOutput+".csv")
    print("🏁 Done with all companies.")
    remove_sheet_duplicates(sheet)

if __name__ == "__main__":
    import requests
    print("\n✅ Results saved to "+finalOutput+".csv")
    asyncio.run(main(chosenSource))  # change filename if needed