import json
import re
from typing import Dict, List, Any, Optional, Tuple
import time
import requests # Added for direct GET requests

# Attempt to import duckduckgo_search
try:
    from duckduckgo_search import DDGS
except ImportError:
    print("--------------------------------------------------------------------")
    print("IMPORTANT: duckduckgo-search library not found.")
    print("Please install it by running: pip install duckduckgo-search")
    print("The script will attempt direct GET requests, but DDGS fallback will not be available.")
    print("--------------------------------------------------------------------")
    # Define a dummy DDGS class if the import fails
    class DDGS:
        def __init__(self, *args, **kwargs):
            self._is_dummy = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def text(self, *args, **kwargs) -> List[Dict[str, str]]:
            if hasattr(self, '_is_dummy') and self._is_dummy:
                print("Warning: Using dummy DDGS.text(). No actual search performed as library is missing.")
            return []

# --- Configuration & Constants ---

POSITIVE_CSR_KEYWORDS = [
    "stem", "education", "youth", "students", "robotics", "community",
    "innovation", "technology", "scholarship", "mentorship", "workforce development",
    "first robotics", "frc", "vrc", "robotics competition", "foundation", "nonprofit",
    "charitable", "giving", "social responsibility", "sustainability", "impact"
]

KNOWN_MAJOR_SPONSORS_NATIONAL = {
    "Rockwell Automation": {"frc_history": True, "industry": "Automation", "notes": "Major FRC sponsor nationally and often locally."},
    "BAE Systems": {"frc_history": True, "industry": "Aerospace/Defense", "notes": "Known for defense and aerospace, often supports STEM."},
    "Google": {"frc_history": True, "industry": "Technology", "notes": "Supports various STEM initiatives."},
    "Microsoft": {"frc_history": True, "industry": "Technology", "notes": "Supports various STEM initiatives."},
    "Amazon": {"frc_history": True, "industry": "E-commerce/Cloud", "notes": "Growing involvement in STEM education."},
    "Boeing": {"frc_history": True, "industry": "Aerospace", "notes": "Aerospace, strong STEM focus."},
    "Lockheed Martin": {"frc_history": True, "industry": "Aerospace/Defense", "notes": "Aerospace/Defense, STEM outreach."},
    "Ford": {"frc_history": True, "industry": "Automotive", "notes": "Automotive, supports STEM and FRC."},
    "General Motors": {"frc_history": True, "industry": "Automotive", "notes": "Automotive, supports STEM and FRC."},
    "NASA": {"frc_history": True, "industry": "Government/Aerospace", "notes": "Government agency, key FRC partner."},
    "Apple": {"frc_history": False, "industry": "Technology", "notes": "Supports education, less direct FRC typically."},
    "Salesforce": {"frc_history": False, "industry": "Software", "notes": "Focus on various social good, education."},
}

KNOWN_LOCAL_SPONSORS_WI = {
    "SC Johnson": {"frc_history": True, "industry": "Consumer Goods", "location_specific": "Racine, WI", "notes": "Major local employer, historical FRC support."},
    "Kohler Co.": {"frc_history": True, "industry": "Manufacturing", "location_specific": "Kohler, WI", "notes": "Major WI company, FRC sponsor."},
    "GE HealthCare": {"frc_history": True, "industry": "Healthcare Technology", "location_specific": "Wisconsin", "notes": "Known FRC team sponsor in WI."},
    "Oshkosh Corporation": {"frc_history": True, "industry": "Specialty Vehicles", "location_specific": "Oshkosh, WI", "notes": "Industrial, supports WI robotics."},
    "Power/mation": {"frc_history": True, "industry": "Automation Distributor", "location_specific": "Wisconsin/Midwest", "notes": "Distributor, actively sponsors FRC teams."},
    "Advocate Aurora Health": {"frc_history": False, "industry": "Healthcare", "location_specific": "Wisconsin/Illinois", "notes": "Healthcare, potential for community health/youth programs."},
    "CNH Industrial": {"frc_history": False, "industry": "Machinery", "location_specific": "Racine, WI", "notes": "Agricultural/construction, potential STEM alignment."},
    "Foxconn": {"frc_history": False, "industry": "Electronics Manufacturing", "location_specific": "Mount Pleasant, WI", "notes": "Electronics, past commitments to WI investment."},
    "Modine Manufacturing": {"frc_history": False, "industry": "Thermal Management", "location_specific": "Racine, WI", "notes": "Thermal management, manufacturing base."},
    "InSinkErator": {"frc_history": False, "industry": "Manufacturing", "location_specific": "Racine, WI", "notes": "Manufacturing, Emerson subsidiary."},
}

MAX_SEARCH_RESULTS_PER_QUERY = 5
DDG_REQUEST_DELAY = 2.5 # Seconds to wait between DDG requests to be polite
DDG_DIRECT_JSON_API_URL = "https://api.duckduckgo.com/" # Base URL for the JSON API

# --- Helper: Perform DDG Search with Error Handling & Delay ---
def perform_ddg_search(query: str, max_results: int = MAX_SEARCH_RESULTS_PER_QUERY) -> List[Dict[str, str]]:
    """
    Performs a DuckDuckGo search.
    Attempts direct JSON API call first, then falls back to duckduckgo-search library.
    """
    print(f"  DDG Search Attempt: \"{query}\" (max_results={max_results})")
    time.sleep(DDG_REQUEST_DELAY) 

    formatted_results: List[Dict[str, str]] = []
    
    # Attempt 1: Direct GET request to unofficial JSON endpoint
    try:
        params = {
            'q': query,
            'format': 'json',    # Request JSON format
            'no_html': 1,         # Disable HTML in results, if possible
            'skip_disambig': 1    # Skip disambiguation pages
        }
        headers = { # Mimic a browser user-agent
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        print(f"    Attempting direct JSON API call to: {DDG_DIRECT_JSON_API_URL}")
        response = requests.get(DDG_DIRECT_JSON_API_URL, params=params, headers=headers, timeout=15)
        response.raise_for_status() 
        
        data = response.json()
        # print(f"    Direct API JSON Response (sample): {str(data)[:300]}") # For debugging

        # Parse the JSON response. Structure can vary.
        # 'Results' for web results, 'RelatedTopics' for instant answers/topics.
        # 'AbstractText' and 'AbstractURL' for definitions or !bang redirects.
        
        api_results_raw = []
        if 'Results' in data and data['Results']: # Organic web results
            api_results_raw = data['Results']
        elif 'RelatedTopics' in data and data['RelatedTopics']: # Topic-based results
            # Filter out category headers if 'Name' field exists
            api_results_raw = [topic for topic in data['RelatedTopics'] if not topic.get('Name')]


        count = 0
        for item in api_results_raw:
            if count >= max_results:
                break
            
            title = ""
            body = ""
            href = ""

            # Try to extract from common fields in RelatedTopics items
            if 'Text' in item: # Often the main descriptive text or title
                title = item['Text']
            if 'FirstURL' in item: # Usually the primary link
                href = item['FirstURL']
            
            # If 'Result' field exists (often contains HTML for sub-topics)
            if 'Result' in item and item['Result']:
                # Try to parse the HTML snippet in 'Result'
                html_snippet = item['Result']
                href_match = re.search(r'<a href="([^"]+)">', html_snippet)
                title_match = re.search(r'<a href="[^"]+">([^<]+)</a>', html_snippet)
                
                if href_match and not href: href = href_match.group(1) # Prioritize FirstURL if available
                if title_match and not title: title = title_match.group(1).strip()
                
                # Simple body extraction by stripping HTML tags from the snippet
                body_candidate = re.sub(r'<[^>]+>', '', html_snippet).strip()
                if body_candidate and len(body_candidate) > len(title): # If there's more than just the title
                    body = body_candidate.replace(title, '').strip() # Try to remove title if it's part of body

            # Fallbacks or alternative fields from the API structure
            if not title and data.get('Heading'): title = data.get('Heading') # Overall heading for some !bangs
            if not body and data.get('AbstractText'): body = data.get('AbstractText')
            if not href and data.get('AbstractURL'): href = data.get('AbstractURL')


            if title and href: # Require at least title and href
                # Clean up title if it's just the URL again
                if title == href or title.startswith(href.split("://")[1]):
                    # Try to find a better title from the URL path or domain
                    parsed_url_path = href.split("://")[1].split("/")
                    if len(parsed_url_path) > 1 and parsed_url_path[-1]:
                        title_candidate = parsed_url_path[-1].replace('_', ' ').replace('-', ' ').title()
                        if len(title_candidate) > 3: title = title_candidate
                    elif parsed_url_path[0]: # Use domain
                         title = parsed_url_path[0]


                formatted_results.append({'title': title.strip(), 'body': body.strip(), 'href': href.strip()})
                count += 1
        
        if formatted_results:
            print(f"    Successfully fetched {len(formatted_results)} results via direct JSON API.")
            return formatted_results
        else:
            print("    Direct JSON API call did not yield usable, formatted results or was empty.")

    except requests.exceptions.RequestException as e:
        print(f"    Direct JSON API call failed: {e}")
    except json.JSONDecodeError:
        print("    Direct JSON API call did not return valid JSON.")
    except Exception as e:
        print(f"    Unexpected error during direct JSON API processing: {e}")


    # Attempt 2: Fallback to duckduckgo-search library
    print("    Falling back to duckduckgo-search library...")
    try:
        with DDGS(timeout=20) as ddgs:
            if hasattr(ddgs, '_is_dummy') and ddgs._is_dummy: # Check if it's the dummy instance
                print("    Skipping duckduckgo-search library call as it's not installed/available.")
                return []
            # The library's text() method returns list of dicts with 'title', 'href', 'body'
            results = ddgs.text(keywords=query, max_results=max_results)
            if results:
                 print(f"    Successfully fetched {len(results)} results via duckduckgo-search library.")
            else:
                 print(f"    duckduckgo-search library returned no results for '{query}'.")
            return results if results else []
    except Exception as e:
        print(f"    Error using duckduckgo-search library for '{query}': {e}")
        return []


# --- Data Fetching Functions --- (get_coordinates_for_location remains the same)
def get_coordinates_for_location(location_name: str) -> Optional[Tuple[float, float]]:
    """
    Simulates fetching geographic coordinates for a location name.
    In a real app, use a geocoding service like geopy with Nominatim or Google Geocoding API.
    """
    print(f"Simulating geocoding for: {location_name}")
    if "mount pleasant" in location_name.lower() and "wisconsin" in location_name.lower():
        return (42.7172, -87.8967)
    elif "madison" in location_name.lower() and "wisconsin" in location_name.lower():
        return (43.0731, -89.4012)
    elif "california" in location_name.lower(): 
        return (36.7783, -119.4179)
    print(f"Warning: Could not geocode '{location_name}'. Some location-specific searches might be less accurate.")
    return None

def fetch_largest_companies_in_area(location_name: str, coordinates: Optional[Tuple[float, float]]) -> List[Dict[str, Any]]:
    """
    Fetches a list of largest companies for a given location using DuckDuckGo search
    and supplements with simulated/known data.
    """
    print(f"Fetching largest companies for: {location_name} using DDG and known data...")
    companies_found_data: Dict[str, Dict[str, Any]] = {} 

    search_queries = [
        f"largest companies in {location_name}",
        f"major employers in {location_name}",
        f"top businesses in {location_name} headquarters"
    ]

    for query in search_queries:
        results = perform_ddg_search(query, max_results=MAX_SEARCH_RESULTS_PER_QUERY + 2)
        for res in results:
            title = res.get('title', '')
            snippet = res.get('body', '') # 'body' is the key from ddg_search library
            url = res.get('href', '')

            cleaned_title = re.sub(r"(?i)(list of|top \d+|best|leading|major|\d+ companies in)", "", title).strip()
            cleaned_title = re.sub(r"(?i)(companies in .*|employers in .*|businesses in .*)", "", cleaned_title).strip()
            
            parts = re.split(r'\s*[:|-]\s*|\s+-\s+', cleaned_title)
            company_name_candidate = parts[0].strip()

            if company_name_candidate and len(company_name_candidate) > 2 and len(company_name_candidate) < 70 \
               and not any(phrase in company_name_candidate.lower() for phrase in ["...", "website", ".com", ".org", location_name.lower().split(',')[0].strip().lower()]) \
               and company_name_candidate.lower() not in ["news", "careers", "contact", "about us", "home", "sign in", "log in", "duckduckgo", "search results"]: # Added more filters
                
                if company_name_candidate not in companies_found_data:
                    companies_found_data[company_name_candidate] = {
                        "name": company_name_candidate,
                        "industry": "Unknown (via DDG)", 
                        "size_indicator": "Unknown (via DDG)", 
                        "hq_location": location_name, 
                        "notes": f"Found via DDG snippet: '{snippet[:100]}...'",
                        "source_url_ddg": url,
                        "search_title_ddg": title
                    }
                else: 
                    companies_found_data[company_name_candidate]["notes"] += f"; Also in '{title}'"

    print(f"  Found {len(companies_found_data)} potential company mentions via DDG.")

    # Merge with known/simulated data
    for name, data in {**KNOWN_MAJOR_SPONSORS_NATIONAL, **KNOWN_LOCAL_SPONSORS_WI}.items():
        if name not in companies_found_data:
            companies_found_data[name] = {
                "name": name, "industry": data.get("industry", "Unknown"),
                "size_indicator": data.get("size_indicator", "Varies"),
                "hq_location": data.get("location_specific", "National/Global"),
                "notes": data.get("notes", ""),
                "is_known_sponsor_list": True
            }
        else: 
            companies_found_data[name].update({
                "industry": data.get("industry", companies_found_data[name]["industry"]),
                "size_indicator": data.get("size_indicator", "Varies"),
                "hq_location": data.get("location_specific", companies_found_data[name]["hq_location"]),
                "notes": companies_found_data[name]["notes"] + "; " + data.get("notes", ""),
                "is_known_sponsor_list": True
            })

    if coordinates and 42.70 < coordinates[0] < 42.73 and -87.90 < coordinates[1] < -87.88: # Mt Pleasant Sim
        sim_companies_mt_pleasant = [
            {"name": "Foxconn", "industry": "Electronics Manufacturing", "size_indicator": "Very Large", "hq_location": "Mount Pleasant, WI (planned/actual)", "notes": "Large investment in the area."},
            {"name": "Advocate Aurora Health", "industry": "Healthcare", "size_indicator": "Very Large", "hq_location": "Downers Grove, IL & Milwaukee, WI", "notes": "Major regional healthcare provider."},
            {"name": "Ascension All Saints Hospital", "industry": "Healthcare", "size_indicator": "Large", "hq_location": "Racine, WI", "notes": "Part of Ascension network."},
            {"name": "InSinkErator (Emerson)", "industry": "Manufacturing", "size_indicator": "Large", "hq_location": "Racine, WI", "notes": "Food waste disposers."},
            {"name": "Modine Manufacturing", "industry": "Thermal Management", "size_indicator": "Medium-Large", "hq_location": "Racine, WI", "notes": "Thermal management."},
            {"name": "Twin Disc", "industry": "Manufacturing", "size_indicator": "Medium", "hq_location": "Racine, WI", "notes": "Power transmission equipment."},
            {"name": "Cree Lighting (Ideal Industries)", "industry": "Lighting Manufacturing", "size_indicator": "Medium-Large", "hq_location": "Racine, WI (major facility)", "notes": "LED lighting solutions."}
        ]
        for company_data in sim_companies_mt_pleasant:
            if company_data["name"] not in companies_found_data:
                companies_found_data[company_data["name"]] = company_data
    return list(companies_found_data.values())


def check_sponsorship_history(company_name: str, location_context: str) -> Dict[str, Any]:
    """Checks sponsorship history using DDG and known lists."""
    print(f"Checking sponsorship history for: {company_name}...")
    history = {"frc_sponsor": False, "other_stem_event_sponsor": False, "details": [], "ddg_evidence_urls": []}

    combined_known_sponsors = {**KNOWN_MAJOR_SPONSORS_NATIONAL, **KNOWN_LOCAL_SPONSORS_WI}
    if company_name in combined_known_sponsors and combined_known_sponsors[company_name].get("frc_history"):
        history["frc_sponsor"] = True
        history["details"].append(f"Source: Known Sponsor List - {combined_known_sponsors[company_name].get('notes','')}")
    
    queries_frc = [
        f'"{company_name}" FIRST Robotics Competition sponsor',
        f'"{company_name}" FRC team "{location_context.split(",")[0]}" sponsor', # Use first part of location
        f'"{company_name}" supports FRC team'
    ]
    found_frc_via_ddg = False
    for query in queries_frc:
        if found_frc_via_ddg: break
        results_frc = perform_ddg_search(query, max_results=2)
        for res in results_frc:
            snippet_text = f"{res.get('title','')} {res.get('body','')}".lower()
            if "frc" in snippet_text or "first robotics" in snippet_text:
                if any(kw in snippet_text for kw in ["sponsor", "support", "partner", "donation", "grant"]):
                    history["frc_sponsor"] = True
                    detail_text = f"DDG Hint (FRC): '{res.get('title')}' (URL: {res.get('href')})"
                    if detail_text not in history["details"]: history["details"].append(detail_text)
                    if res.get('href') not in history["ddg_evidence_urls"]: history["ddg_evidence_urls"].append(res.get('href'))
                    found_frc_via_ddg = True
                    break
    
    # Only search for general STEM if not already confirmed FRC sponsor from a reliable source (known list)
    # or if DDG FRC search was inconclusive.
    if not (history["frc_sponsor"] and any("Known Sponsor List" in d for d in history["details"])):
        queries_stem = [
            f'"{company_name}" STEM education sponsor "{location_context}"',
            f'"{company_name}" youth robotics grant',
            f'"{company_name}" science fair sponsor'
        ]
        found_stem_via_ddg = False
        for query in queries_stem:
            if found_stem_via_ddg: break
            results_stem = perform_ddg_search(query, max_results=2)
            for res in results_stem:
                snippet_text = f"{res.get('title','')} {res.get('body','')}".lower()
                if any(kw in snippet_text for kw in POSITIVE_CSR_KEYWORDS) and \
                   any(kw_action in snippet_text for kw_action in ["sponsor", "support", "grant", "fund", "partner"]):
                    history["other_stem_event_sponsor"] = True
                    detail_text = f"DDG Hint (STEM): '{res.get('title')}' (URL: {res.get('href')})"
                    if detail_text not in history["details"]: history["details"].append(detail_text)
                    if res.get('href') not in history["ddg_evidence_urls"]: history["ddg_evidence_urls"].append(res.get('href'))
                    found_stem_via_ddg = True
                    break
    
    if not history["details"]:
        history["details"].append("No specific sponsorship history indications found from DDG or known lists.")
    return history

def get_company_csr_info(company_name: str) -> Dict[str, Any]:
    """Fetches CSR information using DDG and supplements with known data."""
    print(f"Checking CSR info for: {company_name}...")
    csr = {"has_csr_program": False, "focus_areas": [], "mentions_positive_keywords": False, "notes": "", "ddg_evidence_urls": []}

    # Check known data first
    if company_name in ["SC Johnson", "Kohler Co.", "Microsoft", "Google", "Salesforce", "Rockwell Automation"]:
        csr["has_csr_program"] = True
        csr["notes"] = "Source: Known Company - Assumed to have significant CSR programs."
        if company_name == "SC Johnson": csr["focus_areas"].extend(["Community Development", "Environment", "Education"])
        if company_name == "Microsoft": csr["focus_areas"].extend(["Education", "Digital Skills", "Sustainability", "AI for Good"])
        if company_name == "Google": csr["focus_areas"].extend(["Education", "Digital Inclusion", "Sustainability"])
        if csr["focus_areas"]: csr["mentions_positive_keywords"] = True # If we know focus areas, likely positive
    
    queries_csr = [
        f'"{company_name}" corporate social responsibility',
        f'"{company_name}" community impact',
        f'"{company_name}" foundation grants',
        f'"{company_name}" sustainability report highlights'
    ]
    
    found_csr_mention_ddg = False
    for query in queries_csr:
        # If we already have strong signals, we might not need all queries
        if found_csr_mention_ddg and csr["mentions_positive_keywords"] and len(csr["focus_areas"]) > 1: break 
        
        results = perform_ddg_search(query, max_results=2)
        for res in results:
            snippet_text = f"{res.get('title','')} {res.get('body','')}".lower()
            url = res.get('href','')

            # Check for keywords indicating a CSR/Community page
            if any(page_kw in snippet_text for page_kw in ["csr", "social responsibility", "community", "sustainability", "foundation", "giving", "impact report"]):
                csr["has_csr_program"] = True # Mark true if such page is found
                note_text = f"DDG Hint: Potential CSR page/mention: '{res.get('title')}' (URL: {url})"
                if note_text not in csr["notes"]: csr["notes"] += ("; " if csr["notes"] else "") + note_text
                if url and url not in csr["ddg_evidence_urls"]: csr["ddg_evidence_urls"].append(url)
                found_csr_mention_ddg = True

            # Check for positive keywords in snippet text
            for pk_word in POSITIVE_CSR_KEYWORDS:
                if pk_word in snippet_text:
                    csr["mentions_positive_keywords"] = True
                    # Add keyword to focus areas if it's descriptive and not too generic
                    if pk_word not in csr["focus_areas"] and pk_word not in ["community", "foundation", "giving", "social responsibility", "sustainability", "impact"]: # Avoid very generic terms as specific focus areas
                         csr["focus_areas"].append(pk_word.capitalize())
            
            if found_csr_mention_ddg and csr["mentions_positive_keywords"]: break # Early exit if good signal found
        if found_csr_mention_ddg and csr["mentions_positive_keywords"]: break


    if not csr["notes"] and not csr["has_csr_program"]: # Check if it was set by known data
        csr["notes"] = "No strong CSR program indications found from DDG search."
    
    csr["focus_areas"] = sorted(list(set(csr["focus_areas"]))) # Unique focus areas
    return csr

# --- Prioritization Logic ---
def calculate_priority_score(company_info: Dict[str, Any]) -> int:
    score = 0
    sponsorship_history = company_info.get("sponsorship_history", {})
    if sponsorship_history.get("frc_sponsor"):
        score += 60 
    elif sponsorship_history.get("other_stem_event_sponsor"):
        score += 30 

    csr_info = company_info.get("csr_info", {})
    if csr_info.get("has_csr_program"):
        score += 15 
    if csr_info.get("mentions_positive_keywords"):
        score += 20 
        focus_areas_text = " ".join(csr_info.get("focus_areas", [])).lower()
        if any(frc_kw in focus_areas_text for frc_kw in ["frc", "first robotics", "robotics competition", "robotics education"]):
            score += 25 

    size_indicator = company_info.get("size_indicator", "").lower()
    if "very large" in size_indicator: score += 20
    elif "large" in size_indicator: score += 15
    elif "medium-large" in size_indicator: score += 10
    elif "medium" in size_indicator: score += 5

    industry = company_info.get("industry", "").lower()
    if any(ind_kw in industry for ind_kw in ["technology", "software", "engineering", "manufacturing", "machinery", "automation", "aerospace", "energy", "science"]):
        score += 15 
    
    if company_info.get("is_known_sponsor_list"): # Bonus if it appeared in our curated lists
        score += 10

    return score

# --- Main Function ---
def find_potential_sponsors(location_name: str):
    """Main function to find and prioritize potential sponsors for a given location."""
    print(f"\n--- Starting Sponsorship Prospecting for: {location_name} ---")
    coordinates = get_coordinates_for_location(location_name)
    companies_initial_list = fetch_largest_companies_in_area(location_name, coordinates)

    if not companies_initial_list:
        print("No company candidates found for this location after initial search and known lists.")
        return
    print(f"\nIdentified {len(companies_initial_list)} initial company candidates. Now processing details for each...")

    prospected_companies = []
    for company_data in companies_initial_list:
        company_name = company_data.get("name", "").strip()
        if not company_name or len(company_name) < 2 : 
            print(f"Skipping entry with invalid or missing company name: {company_data}")
            continue
            
        print(f"\nProcessing Details for: {company_name}...")
        sponsorship_info = check_sponsorship_history(company_name, location_name)
        csr_details = get_company_csr_info(company_name)
        
        company_profile = {
            **company_data, 
            "sponsorship_history": sponsorship_info,
            "csr_info": csr_details,
            "calculated_priority_score": 0 
        }
        company_profile["calculated_priority_score"] = calculate_priority_score(company_profile)
        prospected_companies.append(company_profile)

    sorted_companies = sorted(prospected_companies, key=lambda c: c["calculated_priority_score"], reverse=True)

    print(f"\n\n--- Potential Sponsor List for {location_name} (Prioritized) ---")
    if not sorted_companies:
        print("No companies were processed and scored.")
        return

    for i, company in enumerate(sorted_companies):
        print(f"\n{i+1}. {company['name']} (Score: {company['calculated_priority_score']})")
        print(f"   Industry: {company.get('industry', 'N/A')}, Size: {company.get('size_indicator', 'N/A')}")
        print(f"   Location Info: {company.get('hq_location', 'N/A')}")
        if company.get('notes'): print(f"   Notes: {company.get('notes')}")
        if company.get('source_url_ddg'): print(f"   Example DDG Source (Company ID): {company.get('source_url_ddg')}")

        s_hist = company.get('sponsorship_history', {})
        print(f"   FRC Sponsor History: {'YES' if s_hist.get('frc_sponsor') else 'No/Unknown'}")
        print(f"   Other STEM Sponsor History: {'YES' if s_hist.get('other_stem_event_sponsor') else 'No/Unknown'}")
        if s_hist.get('details'):
            for detail_idx, detail in enumerate(s_hist.get('details', [])): print(f"     - {detail}")

        csr_d = company.get('csr_info', {})
        print(f"   Has CSR Program: {'YES' if csr_d.get('has_csr_program') else 'No/Unknown'}")
        if csr_d.get('has_csr_program') or csr_d.get('focus_areas'):
            print(f"     CSR Focus Areas: {', '.join(csr_d.get('focus_areas')) if csr_d.get('focus_areas') else 'Not specified'}")
            print(f"     CSR Mentions STEM/Youth Keywords: {'YES' if csr_d.get('mentions_positive_keywords') else 'No'}")
        if csr_d.get('notes'): print(f"     CSR Notes: {csr_d.get('notes')}")
        print("-" * 40)

    output_filename_json = f"potential_sponsors_ddg_{location_name.lower().replace(' ', '_').replace(',', '')}.json"
    try:
        with open(output_filename_json, 'w') as f:
            json.dump(sorted_companies, f, indent=4)
        print(f"\nResults also saved to: {output_filename_json}")
    except IOError as e:
        print(f"\nError saving results to JSON: {e}")

if __name__ == "__main__":
    location_input = "Mount Pleasant, Wisconsin"
    # location_input = "Wisconsin" 
    # location_input = "Madison, Wisconsin"

    if location_input:
        find_potential_sponsors(location_input)
    else:
        print("No location entered. Exiting.")
