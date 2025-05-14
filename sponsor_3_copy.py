import requests # For making HTTP requests
from bs4 import BeautifulSoup # For parsing HTML
import os # For interacting with the operating system (e.g., file paths)
from urllib.parse import urljoin # For constructing absolute URLs from relative paths
from datetime import datetime # For timestamping (though not actively used for submission data here)
import difflib # For finding close matches between strings (fuzzy matching)
import sponsor1__vars # Assuming this is a custom module for storing variables

# --- Configuration & Data ---

# Keywords to identify potential sponsorship forms or relevant sections on a page
SPONSORSHIP_KEYWORDS = [
    'sponsorship', 'support', 'funding', 'application', 'organization', 'group', 
    'grant', "contact", "sponsor", "partner", "apply", "nonprofit", "501(c)(3)", 
    "foundation", "youth", "first frc", "community", "giving", "donation" # Added more keywords
]
# Keywords to identify search forms (to potentially use them to find sponsorship pages)
SEARCH_KEYWORDS = SPONSORSHIP_KEYWORDS # Using the same list, but could be different

# Applicant data (pre-filled information for forms)
# This should be loaded from sponsor1__vars or defined securely
APPLICANT_DATA = sponsor1__vars.APPLICANT_DATA 

# Mapping of standard form field keys to common variations found in HTML forms
# Keys are lowercase for consistent matching.
FIELD_VARIANTS = {
    'name': ['first_name', 'last_name', 'full_name', 'full name', 'name', 'your_name', 'contact_name'],
    'email': ['email', 'mail', 'email_address', 'contact_email'],
    'phone': ['phone', 'tel', 'telephone', 'cell', 'mobile', 'phonenumber', 'contact_phone'],
    'group': ['group', 'team', 'club', 'team_name', 'group_name'],
    'organization': ['organization', 'company', 'org', 'orgname', 'organization_name'],
    'city': ['city', 'town', 'address_city'],
    'state': ['state', 'province', 'region', 'address_state'],
    'zip': ['zip', 'postal', 'zipcode', 'postal_code', 'address_zip'],
    'country': ['country', 'nation', 'address_country'],
    'website': ['website', 'url', 'webpage', 'org_website'],
    'form_of_address': ['form_of_address', 'salutation', 'title'], # 'Form of address' was oddly capitalized
    'message': ['message', 'comments', 'details', 'description', 'inquiry', 'question', 'reason_for_contact'] # Added message/details
}

# Path to a file containing background information or a general message for text areas
BACKGROUND_INFO_FILE = sponsor1__vars.BACKGROUND_INFO_FILE

# Keys from APPLICANT_DATA that we might try to fuzzy match against form field names
FUZZY_KEYS = list(APPLICANT_DATA.keys())

# --- Helper Functions ---

def load_background_info(file_path: str) -> str:
    """Loads text content from a specified file path."""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read().strip()
        except Exception as e:
            print(f"[!] Error loading background info from {file_path}: {e}")
    return ''

def get_form_fields(form_soup: BeautifulSoup) -> list:
    """Extracts all input, textarea, and select elements from a form BeautifulSoup object."""
    return form_soup.find_all(['input', 'textarea', 'select'])

def is_sponsorship_form(form_soup: BeautifulSoup) -> bool:
    """
    Determines if a form is likely related to sponsorships based on keywords
    in its field names, placeholders, or surrounding text.
    """
    form_text_content = form_soup.get_text(" ", strip=True).lower() # Get all text within the form
    fields = get_form_fields(form_soup)
    # Combine field names, placeholders, and IDs for keyword searching
    field_attributes_text = ' '.join([
        field.get('name', '').lower() + ' ' + 
        field.get('placeholder', '').lower() + ' ' +
        field.get('id', '').lower()
        for field in fields
    ])
    
    combined_text_to_search = form_text_content + " " + field_attributes_text
    for keyword in SPONSORSHIP_KEYWORDS:
        if keyword.lower() in combined_text_to_search:
            return True
    return False

def is_search_form(form_soup: BeautifulSoup) -> bool:
    """Determines if a form is primarily a search form."""
    fields = get_form_fields(form_soup)
    for f in fields:
        # Check input type, name, id, or placeholder for "search"
        if f.get('type') == 'search' \
           or 'search' in f.get('name', '').lower() \
           or 'query' in f.get('name', '').lower() \
           or 'q' == f.get('name', '').lower() \
           or 'search' in f.get('id', '').lower() \
           or 'search' in f.get('placeholder', '').lower():
            return True
    return False

def fuzzy_match_key(field_name: str, known_keys: list, threshold: float = 0.7) -> Optional[str]: # Increased threshold
    """
    Finds the best fuzzy match for a field_name from a list of known_keys.
    """
    if not field_name: return None
    matches = difflib.get_close_matches(field_name.lower(), known_keys, n=1, cutoff=threshold)
    return matches[0] if matches else None

def get_applicant_value(field_name_raw: str, applicant_data: dict, field_variants_map: dict):
    """
    Retrieves the appropriate value from applicant_data for a given form field name.
    It uses exact matches against variants and then tries fuzzy matching.
    """
    if not field_name_raw:
        return '', 'field name missing'
        
    field_name_lower = field_name_raw.lower()
    
    # Try exact matches using the FIELD_VARIANTS map
    for standard_key, variants in field_variants_map.items():
        if field_name_lower in variants: # Direct match to a known variant
             if standard_key in applicant_data:
                return applicant_data[standard_key], f"direct match to '{standard_key}' via variant '{field_name_lower}'"
             else: # Variant matched, but no corresponding key in APPLICANT_DATA
                return '', f"variant '{field_name_lower}' matched standard key '{standard_key}', but key not in APPLICANT_DATA"

    # If no direct variant match, try fuzzy matching the field_name_lower against the standard keys
    # The standard keys are the keys in APPLICANT_DATA or FIELD_VARIANTS
    fuzzy_standard_key = fuzzy_match_key(field_name_lower, list(applicant_data.keys()))
    if fuzzy_standard_key and fuzzy_standard_key in applicant_data:
        return applicant_data[fuzzy_standard_key], f"fuzzy match to APPLICANT_DATA key '{fuzzy_standard_key}'"

    return '', 'no match found'


def match_select_option(select_element: BeautifulSoup, target_value: str) -> str:
    """
    Finds the best matching <option> value within a <select> element for a target_value.
    It prioritizes exact matches of option text or value, then fuzzy matches of option text.
    """
    options = select_element.find_all('option')
    if not options:
        return '' # No options to select

    option_texts = [opt.get_text(strip=True) for opt in options]
    option_values = [opt.get('value', opt.get_text(strip=True)) for opt in options] # Fallback to text if value missing

    target_lower = target_value.lower()

    # 1. Exact match on option value attribute (case-insensitive)
    for i, val in enumerate(option_values):
        if val and val.lower() == target_lower:
            print(f"   Matched select option by exact value: '{options[i].get_text(strip=True)}' (value: '{val}')")
            return val
            
    # 2. Exact match on option display text (case-insensitive)
    for i, text in enumerate(option_texts):
        if text and text.lower() == target_lower:
            actual_value = options[i].get('value', text) # Get the actual value attribute
            print(f"   Matched select option by exact text: '{text}' (value: '{actual_value}')")
            return actual_value

    # 3. Fuzzy match on option display text (if target_value is reasonably long)
    if len(target_value) > 3: # Avoid fuzzy matching very short strings like "Mr"
        # Use (text, original_value) tuples for difflib
        text_value_pairs = [(text, val) for text, val in zip(option_texts, option_values) if text] # Only non-empty texts
        fuzzy_matches = difflib.get_close_matches(target_value, [pair[0] for pair in text_value_pairs], n=1, cutoff=0.65) # cutoff 0.65
        if fuzzy_matches:
            matched_text = fuzzy_matches[0]
            for text, val in text_value_pairs: # Find the original value for the matched text
                if text == matched_text:
                    print(f"   Matched select option by fuzzy text: '{text}' (value: '{val}') for target '{target_value}'")
                    return val
    
    # 4. Fallback: if there's a default selected option, use it. Otherwise, first valid option or empty.
    for opt in options:
        if opt.has_attr('selected'):
            selected_val = opt.get('value', opt.get_text(strip=True))
            print(f"   Using default selected option: '{opt.get_text(strip=True)}' (value: '{selected_val}')")
            return selected_val
            
    if option_values and option_values[0] is not None : # First option if it has a value
         print(f"   Defaulting to first select option: '{options[0].get_text(strip=True)}' (value: '{option_values[0]}')")
         return option_values[0]

    print(f"   Could not find a suitable match for select option with target '{target_value}'.")
    return '' # No suitable match

def fill_form_data(form_fields: list, applicant_data: dict, field_variants: dict, background_text: str) -> dict:
    """
    Prepares a dictionary of form data to be submitted by matching form fields
    to applicant data.
    """
    form_data_payload = {}
    # Prepare split names from APPLICANT_DATA if 'name' exists
    full_name = applicant_data.get('name', '')
    first_name, last_name = ('', '')
    if ' ' in full_name:
        name_parts = full_name.split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1]
    else:
        first_name = full_name # If no space, assume it's just a first name or single name

    for field in form_fields:
        field_name = field.get('name') # The 'name' attribute is crucial for form submission
        if not field_name:
            # print(f" → Field (tag: {field.name}, id: {field.get('id')}) has no 'name' attribute. Skipping.")
            continue # Fields without a 'name' are not typically part of the submission

        input_type = field.get('type', 'text').lower() # Default to 'text' if type is not specified
        tag_name = field.name.lower() # 'input', 'textarea', 'select'

        # Skip fields that are not meant for user input or are problematic to auto-fill
        if input_type in ['submit', 'button', 'reset', 'file', 'hidden', 'image', 'password']:
            # print(f" → Skipping field '{field_name}' (type: {input_type}).")
            continue

        value_to_fill = ''
        fill_reason = ''

        # 1. Special handling for first/last name based on common patterns in field_name
        # This overrides the generic get_applicant_value for these specific cases.
        fn_lower = field_name.lower()
        if ('firstname' in fn_lower or 'first_name' in fn_lower or (fn_lower == 'fname')) and first_name:
            value_to_fill = first_name
            fill_reason = "matched as first name"
        elif ('lastname' in fn_lower or 'last_name' in fn_lower or (fn_lower == 'lname')) and last_name:
            value_to_fill = last_name
            fill_reason = "matched as last name"
        else:
            # 2. General matching using `get_applicant_value`
            value_to_fill, fill_reason = get_applicant_value(field_name, applicant_data, field_variants)

        # 3. Fallbacks or specific type handling if no value found yet
        if not value_to_fill and not fill_reason.startswith("direct match"): # Only if primary matching failed
            if tag_name == 'textarea' and ('message' in fn_lower or 'comment' in fn_lower or 'detail' in fn_lower or 'background' in fn_lower or 'project_description' in fn_lower):
                if background_text:
                    value_to_fill = background_text
                    fill_reason = 'filled with background_info file content'
            elif input_type == 'email' and not value_to_fill and applicant_data.get('email'): # Specific type fallback
                 value_to_fill = applicant_data.get('email')
                 fill_reason = "fallback to applicant email for type 'email'"
            elif input_type == 'url' and not value_to_fill and applicant_data.get('website'):
                 value_to_fill = applicant_data.get('website')
                 fill_reason = "fallback to applicant website for type 'url'"
            elif input_type == 'tel' and not value_to_fill and applicant_data.get('phone'):
                 value_to_fill = applicant_data.get('phone')
                 fill_reason = "fallback to applicant phone for type 'tel'"
            elif 'date' in fn_lower and input_type != 'hidden': # Don't fill hidden date fields unless sure
                value_to_fill = datetime.now().strftime("%Y-%m-%d") # Basic date format
                fill_reason = 'filled as current date'
            elif input_type == 'checkbox':
                # For checkboxes, often 'on' is default or value is its own name.
                # If required and no other logic, check it. Here, assume 'on' if a value is needed.
                # More complex logic might involve checking if 'required' or looking for labels.
                # For now, if we need to fill it based on a keyword, we set it to its 'value' or 'on'.
                checkbox_value = field.get('value', 'on') # HTML default is 'on' if value attr is missing
                # This part is tricky: when should a checkbox be checked?
                # If 'terms' or 'agree' is in the name, and it's the only option, maybe check it.
                if any(kw in fn_lower for kw in ['agree', 'terms', 'consent', 'confirm']):
                    value_to_fill = checkbox_value
                    fill_reason = f'checkbox default for {fn_lower}'
                else:
                    fill_reason = 'checkbox skipped (logic needed)' # Avoid auto-checking all checkboxes
            elif input_type == 'radio':
                # Radio buttons are grouped by 'name'. Need to choose one.
                # This is complex to automate correctly without understanding the options.
                # For now, skip direct filling unless a very clear match.
                fill_reason = 'radio button skipped (complex to auto-select)'
            elif tag_name == 'select':
                # Try to match an option in the select dropdown.
                # `value_to_fill` might have a suggestion from `get_applicant_value`.
                # If `value_to_fill` is still empty, try to find a default or a common value from applicant data.
                target_select_value = value_to_fill # Use previously matched value if any
                if not target_select_value: # If no specific value was determined for this select field name yet
                    # Try to guess a good value based on the field name and applicant_data
                    # e.g. if field name is 'country', use applicant_data['country']
                    standard_key_for_select = fuzzy_match_key(field_name, list(applicant_data.keys()), 0.8)
                    if standard_key_for_select:
                        target_select_value = applicant_data.get(standard_key_for_select, '')
                        fill_reason = f"derived target for select from key '{standard_key_for_select}'"
                
                if target_select_value: # If we have a target value (either from direct match or guess)
                    selected_option_value = match_select_option(field, target_select_value)
                    if selected_option_value:
                        value_to_fill = selected_option_value
                        fill_reason += f"; select matched option '{selected_option_value}'"
                    else:
                        fill_reason += f"; select: no option matched '{target_select_value}'"
                else:
                    fill_reason += '; select: no target value to match option'
            
            if not value_to_fill and not fill_reason: # If truly no match after all attempts
                 fill_reason = 'no match, left blank'


        # Add to form_data_payload if a value was determined (even if empty string for some fields)
        # Only add if value_to_fill is not None (it's usually string, but good practice)
        if value_to_fill is not None: # We want to submit even empty strings if a field was processed
            form_data_payload[field_name] = value_to_fill
            print(f" → Field '{field_name}' (type: {input_type}, tag: {tag_name}): Attempting to fill with '{value_to_fill}' ({fill_reason})")
        else:
            print(f" → Field '{field_name}' (type: {input_type}, tag: {tag_name}): Skipped or no value determined ({fill_reason})")


    return form_data_payload

def submit_form_requests(session: requests.Session, form_action_url: str, form_method: str, form_data: dict, files_data: Optional[dict] = None):
    """
    Submits form data using the requests library.
    Handles both GET and POST methods.
    Includes a basic User-Agent header.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    print(f"\n📤 Submitting form to: {form_action_url} using method: {form_method.upper()}")
    print("   Form Data Payload:")
    for k, v in form_data.items():
        print(f"     {k}: {v[:70] + '...' if isinstance(v, str) and len(v) > 70 else v}") # Print truncated long values
    if files_data:
         print(f"   Files Data Payload: {files_data.keys()}")


    try:
        if form_method.lower() == 'post':
            response = session.post(form_action_url, data=form_data, files=files_data, headers=headers, timeout=20, allow_redirects=True)
        else: # Default to GET
            response = session.get(form_action_url, params=form_data, headers=headers, timeout=20, allow_redirects=True)
        
        print(f"📄 Response Status Code: {response.status_code}")
        # print(f"📄 Response URL (after potential redirects): {response.url}")
        # print(f"📄 Response Content (first 300 chars): {response.text[:300]}") # For debugging
        return response
    except requests.exceptions.Timeout:
        print("[!] Form submission timed out.")
    except requests.exceptions.ConnectionError:
        print("[!] Form submission connection error.")
    except requests.exceptions.RequestException as e:
        print(f"[!] An error occurred during form submission: {e}")
    return None


def scrape_and_attempt_submit(target_url: str):
    """
    Main function to scrape a URL for forms, identify relevant ones,
    fill them with applicant data, and attempt submission.
    """
    session = requests.Session() # Use a session to persist cookies if needed across redirects
    
    print(f"🔗 Fetching URL: {target_url}")
    try:
        response = session.get(target_url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status() # Raise an exception for bad status codes
    except requests.exceptions.RequestException as e:
        print(f"[!] Failed to fetch URL {target_url}: {e}")
        return

    soup = BeautifulSoup(response.content, 'lxml') # 'lxml' is a fast parser
    forms = soup.find_all('form')

    if not forms:
        print("ℹ️ No <form> elements found on the page.")
        return

    print(f"🔍 Found {len(forms)} form(s) on the page.")
    background_info_text = load_background_info(BACKGROUND_INFO_FILE)
    
    sponsorship_form_found = False
    for i, form_element in enumerate(forms):
        print(f"\n--- Evaluating Form {i+1} ---")
        # Extract form action URL and method
        form_action_relative = form_element.get('action', '')
        # Construct absolute URL for the form action. `response.url` is the final URL after redirects.
        form_action_absolute = urljoin(response.url, form_action_relative) 
        form_method = form_element.get('method', 'get').lower() # Default to GET if not specified

        form_fields_bs = get_form_fields(form_element) # Get BeautifulSoup elements for fields

        if not form_fields_bs:
            print("   Form has no input, textarea, or select fields. Skipping.")
            continue

        # Attempt to determine if it's a sponsorship/contact form
        if is_sponsorship_form(form_element):
            sponsorship_form_found = True
            print(f"✅ Potential sponsorship/contact form detected (Action: {form_action_absolute}, Method: {form_method}).")
            
            # Prepare form data for submission
            # This is where the logic to map APPLICANT_DATA to form_fields_bs occurs
            filled_data = fill_form_data(form_fields_bs, APPLICANT_DATA, FIELD_VARIANTS, background_info_text)
            
            # Check for file inputs - this script version doesn't handle file uploads, but can detect them
            file_inputs = [f for f in form_fields_bs if f.get('type') == 'file']
            if file_inputs:
                print(f"   ⚠️ This form contains {len(file_inputs)} file input(s) ({[f.get('name') for f in file_inputs]}). File uploads are not automatically handled by this script.")
                # Decide if you want to proceed without uploading files or skip
                # For now, we'll proceed, but the server might reject if files are required.

            # Confirm before submission (optional, for interactive use)
            # proceed = input("   Submit this form? (y/N): ").lower()
            # if proceed != 'y':
            #     print("   Submission aborted by user.")
            #     continue

            # Submit the form
            # Note: submission is currently disabled by `data = {}` in original.
            # To enable actual submission, use `filled_data`.
            # For safety in automated runs, it's often better to review `filled_data` first.
            # submission_payload = filled_data # Use the data filled by your logic
            submission_payload = {} # <<< !!! ORIGINAL CODE HAS THIS, MEANING IT SUBMITS EMPTY DATA !!!
                                     # <<< !!! Change to `filled_data` for actual submission attempt !!!
            
            print("\n   [SIMULATING SUBMISSION - To actually submit, change submission_payload]")
            # If you want to actually try submitting, uncomment the next line and comment out the one after
            # result_response = submit_form_requests(session, form_action_absolute, form_method, submission_payload)
            result_response = None # Keep simulation for now

            if result_response:
                if 200 <= result_response.status_code < 300:
                    print(f"   🚀 Form submitted successfully (HTTP {result_response.status_code}). Final URL: {result_response.url}")
                    # Look for success messages on the response page (heuristic)
                    if any(s_msg in result_response.text.lower() for s_msg in ["thank you", "submitted", "received", "success"]):
                        print("   🎉 Possible success message found in response.")
                    else:
                        print("   🤔 No clear success message detected in response. Review manually.")
                else:
                    print(f"   😟 Form submission may have failed (HTTP {result_response.status_code}). Final URL: {result_response.url}")
            else:
                 print(f"   ℹ️ Form submission was not attempted or failed critically for form to {form_action_absolute}.")
            # Only process the first detected sponsorship form for simplicity, then break.
            # Remove 'break' to try submitting all detected sponsorship forms.
            break 
        
        elif is_search_form(form_element):
            print(f"ℹ️ Search form detected (Action: {form_action_absolute}). This script does not auto-submit search forms.")
            # The original code had logic to try keywords in search forms.
            # This can be useful for discovery but is not direct application submission.
            # Example:
            # for keyword in SEARCH_KEYWORDS:
            #     search_data = {f.get('name'): keyword for f in form_fields_bs if f.get('name') and f.get('type') != 'submit'}
            #     if any(search_data.values()): # Ensure there's something to submit
            #         print(f"   Simulating search with keyword '{keyword}' in this form.")
            #         # submit_form_requests(session, form_action_absolute, form_method, search_data)
            # (Skipping actual search submission in this version)
            continue # Move to the next form

    if not sponsorship_form_found:
        print("\nℹ️ No forms identified as sponsorship/contact forms based on current keywords and logic.")

# --- Main Execution Block ---
if __name__ == "__main__":
    # Ensure APPLICANT_DATA and BACKGROUND_INFO_FILE are correctly configured in sponsor1__vars
    if not APPLICANT_DATA or not BACKGROUND_INFO_FILE:
        print("[!!!] Critical Error: APPLICANT_DATA or BACKGROUND_INFO_FILE is not configured in 'sponsor1__vars.py'.")
        print("      Please set them up before running the script.")
    else:
        test_url_input = input("Enter a URL to check for forms: ").strip()
        if test_url_input:
            scrape_and_attempt_submit(test_url_input)
        else:
            print("No URL entered. Exiting.")