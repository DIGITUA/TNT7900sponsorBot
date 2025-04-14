import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin
from datetime import datetime
import difflib
import sponsor1__vars

# Background and keyword data
SPONSORSHIP_KEYWORDS = ['sponsorship', 'support', 'funding', 'application', 'organization', 'group', 'grant',"contact", "sponsor", "partner", "apply", "Nonprofit", "501(c)(3)", "grant", "foundation", "youth", "FIRST FRC"]
SEARCH_KEYWORDS = SPONSORSHIP_KEYWORDS

# Replace with real answers
APPLICANT_DATA = sponsor1__vars.APPLICANT_DATA

# Map of standard keys to possible variants (lowercase for matching)
FIELD_VARIANTS = {
    'name': ['first_name', 'last_name', 'full_name', 'full name', 'name', 'your_name'],
    'email': ['email', 'mail', 'email_address'],
    'phone': ['phone', 'tel', 'telephone', 'cell', 'mobile', 'phonenumber'],
    'group': ['group', 'team', 'club'],
    'organization': ['organization', 'company', 'org', 'orgname'],
    'city': ['city', 'town'],
    'state': ['state', 'province', 'region'],
    'zip': ['zip', 'postal', 'zipcode'],
    'country': ['country', 'nation'],
    'website': ['website', 'url', 'webpage'],
    'Form of address': ['Form of address',],
}

BACKGROUND_INFO_FILE = sponsor1__vars.BACKGROUND_INFO_FILE

# Fuzzy keys to attempt matching
FUZZY_KEYS = list(APPLICANT_DATA.keys())

def load_background_info(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as file:
            return file.read()
    return ''

def get_form_fields(form):
    return form.find_all(['input', 'textarea', 'select'])

def is_sponsorship_form(form):
    fields = get_form_fields(form)
    field_names = ' '.join([f.get('name', '') + ' ' + f.get('placeholder', '') for f in fields])
    for keyword in SPONSORSHIP_KEYWORDS:
        if keyword.lower() in field_names.lower():
            return True
    return False

def is_search_form(form):
    fields = get_form_fields(form)
    for f in fields:
        if f.get('type') == 'search' or 'search' in f.get('name', '').lower():
            return True
    return False

def fuzzy_match_key(field_name, threshold=0.6):
    matches = difflib.get_close_matches(field_name.lower(), FUZZY_KEYS, n=1, cutoff=threshold)
    return matches[0] if matches else None

def get_applicant_value(field_name):
    name = field_name.lower()
    for key, variants in FIELD_VARIANTS.items():
        if any(variant in name for variant in variants):
            return APPLICANT_DATA.get(key, ''), f"fuzzy match to '{key}'"
    return '', 'no match'

def match_select_option(options, target_value):
    """Use difflib to find the closest option value."""
    option_values = [opt.get('value', '').strip() for opt in options if opt.get('value')]
    matches = difflib.get_close_matches(target_value.lower(), [v.lower() for v in option_values], n=1, cutoff=0.6)
    print('matches: '+ str(matches))
    if matches:
        for opt in option_values:
            if opt.lower() == matches[0]:
                return opt
    return option_values[0] if option_values else ''

def fill_form_data(fields, background_info):
    form_data = {}
    full_name = APPLICANT_DATA.get('name', '')
    first_name = full_name.split()[0] if ' ' in full_name else full_name
    last_name = full_name.split()[1] if ' ' in full_name else ''

    for field in fields:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        name = field.get('name') or field.get('id') or ''
        if not name:
            print(" → Field with no name or id. Skipping.")
            continue

        input_type = field.get('type', 'text')
        tag_name = field.name.lower()

        if input_type in ['submit', 'button', 'file', 'hidden']:
            continue

        value = ''
        reason = ''

        # Special handling for name split
        lowered_name = name.lower()
        if 'first' in lowered_name and 'name' in lowered_name:
            value = first_name
            reason = "matched as first name"
        elif 'last' in lowered_name and 'name' in lowered_name:
            value = last_name
            reason = "matched as last name"
        else:
            # Try fuzzy match
            value, reason = get_applicant_value(name)

            # Fallbacks
            if not value:
                if 'background' in lowered_name:
                    value = background_info
                    reason = 'matched as background info'
                elif 'date' in lowered_name:
                    value = timestamp
                    reason = 'matched as timestamp'
                elif input_type == 'checkbox':
                    value = 'on'
                    reason = 'checkbox default'
                elif input_type == 'radio':
                    value = field.get('value', 'on')
                    reason = 'radio default'
                elif tag_name == 'select':
                    options = field.find_all('option')
                    print("checking for dropdown input ability. " +str(options))
                    if options and value:
                        value = match_select_option(options, value)
                        reason = 'dropdown match with difflib'
                    elif options:
                        value = options[0].get('value', '')
                        reason = 'dropdown default first option'
                    else:
                        reason = 'dropdown but no options'
                else:
                    reason = 'no match, left blank'

        form_data[name] = value
        print(f" → Field '{name}' ({input_type}): '{value}' ({reason})")

    return form_data

def submit_form(session, action_url, method, data):
    session = requests.Session()
    for k, v in data.items():
        print(f"  {k}: {v}")
    if method.lower() == 'post':
        response = session.post(action_url, data=data)
    else:
        response = session.get(action_url, params=data)
    return response

def scrape_and_submit(url):
    session = requests.Session()
    response = session.get(url)
    soup = BeautifulSoup(response.content, 'lxml')

    forms = soup.find_all('form')
    if not forms:
        print("No forms found.")
        return

    background_info = load_background_info(BACKGROUND_INFO_FILE)

    for form in forms:
        form_action = urljoin(url, form.get('action', ''))
        form_method = form.get('method', 'get')
        fields = get_form_fields(form)

        if is_sponsorship_form(form):
            print("Sponsorship form detected.")
            data = fill_form_data(fields, background_info)

            print("\nFilled form data preview:")
            for k, v in data.items():
                print(f"  {k}: {v}")

            data ={}

            result = submit_form(session, form_action, form_method, data)
            print("Form submitted. Status:", result.status_code)
            if (result.status_code == 200):
                print("Form submitted successfully")
            else:
                print("Form was not submitted or subitted successfully")

            print("data sent: "+ str(data))
            return
        elif is_search_form(form):
            print("Search form detected. Trying keywords.")
            for keyword in SEARCH_KEYWORDS:
                data = {f.get('name'): keyword for f in fields if f.get('name')}
                result = submit_form(session, form_action, form_method, data)
                print(f"Search for '{keyword}' returned status {result.status_code}")
                print(f"Search for '{keyword}' returned")
                # You can parse result.content with BeautifulSoup here
            return

    print("No relevant form found.")

if __name__ == "__main__":
    test_url = input("Enter a URL to check for forms: ").strip()
    scrape_and_submit(test_url)