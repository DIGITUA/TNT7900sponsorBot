import re # For regular expression operations

# --- Keyword Configuration ---

# Keywords that suggest an email address might be relevant for grants, sponsorships, STEM, youth outreach, etc.
# These should be lowercase for case-insensitive matching.
RELEVANT_KEYWORDS = [
    "grant", "grants", "funding", "sponsor", "sponsorships", "youth", "stem", 
    "education", "robotics", "student", "students", "nonprofit", "community",
    "outreach", "school", "scholarship", "foundation", "giving", "socialimpact",
    "csr", # Corporate Social Responsibility
    "philanthropy" 
]

# Keywords that suggest an email address might be for general inquiries, customer service, sales, media, etc.,
# and thus less directly relevant for initial sponsorship applications.
IRRELEVANT_KEYWORDS = [
    "support", "help", "service", "customer", "orders", "vendor", "supplier", 
    "media", "press", "investor", "investors", "ir", # Investor Relations
    "returns", "billing", "invoice", "ads", "advertising", "info", "contact", # "info@" and "contact@" are often generic
    "sales", "marketing", "careers", "jobs", "hr", "hello", "admin", "webmaster",
    "privacy", "legal", "partnership" # "partnership" can be ambiguous; could be sales partnerships
]


def classify_email_address(email_address: str) -> tuple[str, int, int]:
    """
    Classifies an email address based on keywords found in its username and domain parts.

    Args:
        email_address: The email address string to classify.

    Returns:
        A tuple containing:
            - classification_label (str): A human-readable classification.
            - relevant_score (int): Count of relevant keywords found.
            - irrelevant_score (int): Count of irrelevant keywords found.
    """
    if not email_address or "@" not in email_address:
        return "Invalid Email Format", 0, 0

    email_lower = email_address.lower()

    # Split email into username and domain parts
    try:
        username_part, domain_part = email_lower.split("@", 1)
    except ValueError:
        return "Invalid Email Format (no @)", 0, 0

    # Further split domain to get the main domain name (e.g., "company" from "company.com")
    domain_name_only = domain_part.split(".")[0]

    # Combine username and main domain name for keyword searching.
    # Replace common separators like '.', '_', '-' with spaces to treat words individually.
    text_to_search = re.sub(r"[._-]", " ", f"{username_part} {domain_name_only}")
    
    # Tokenize the text_to_search for more accurate word boundary matching
    search_tokens = set(text_to_search.split()) # Use a set for unique tokens

    relevant_score = 0
    irrelevant_score = 0

    # Count matches for relevant keywords using word boundaries
    for r_keyword in RELEVANT_KEYWORDS:
        # Simpler check: if the keyword (which is a single word itself usually) is in the tokens
        if r_keyword in search_tokens:
            relevant_score += 1
            # print(f"  + Relevant keyword found: {r_keyword}") # Debug

    # Count matches for irrelevant keywords
    for ir_keyword in IRRELEVANT_KEYWORDS:
        if ir_keyword in search_tokens:
            irrelevant_score += 1
            # print(f"  - Irrelevant keyword found: {ir_keyword}") # Debug


    # --- Classification Logic ---
    # This logic can be adjusted based on desired sensitivity/specificity.
    
    # Handle generic usernames like "info", "contact" with more nuance if domain is specific
    # For example, "info@nonprofitfoundation.org" might still be relevant.
    # Current logic relies purely on keyword counts in username+domain_name.

    if relevant_score > 0 and irrelevant_score == 0:
        # Strong positive signal, especially if multiple relevant keywords
        if relevant_score > 1:
            return "Highly Relevant (Specific Focus: e.g., Grants, STEM, Youth)", relevant_score, irrelevant_score
        return "Relevant (Potential: e.g., Foundation, Community)", relevant_score, irrelevant_score
    
    elif irrelevant_score > 0 and relevant_score == 0:
        # Strong negative signal
        if "careers" in search_tokens or "jobs" in search_tokens:
             return "Irrelevant (Likely HR/Careers)", relevant_score, irrelevant_score
        if "investor" in search_tokens or "ir" == username_part: # common for investor relations
             return "Irrelevant (Likely Investor Relations)", relevant_score, irrelevant_score
        return "Likely Irrelevant (General: e.g., Sales, Support, Media)", relevant_score, irrelevant_score
        
    elif relevant_score > irrelevant_score:
        # More relevant than irrelevant keywords
        return "Potentially Relevant (Mixed Signals, Leans Relevant)", relevant_score, irrelevant_score
        
    elif irrelevant_score > relevant_score:
        # More irrelevant than relevant keywords
        return "Likely Irrelevant (Mixed Signals, Leans Irrelevant)", relevant_score, irrelevant_score
        
    elif relevant_score > 0 and relevant_score == irrelevant_score:
        # Ambiguous case, equal number of conflicting signals
        return "Ambiguous (Conflicting Keywords)", relevant_score, irrelevant_score
        
    else: # relevant_score == 0 and irrelevant_score == 0
        # No specific keywords found, could be a generic personal or departmental email
        # Consider the domain itself - if domain contains e.g. "foundation", it might hint relevance
        # For now, classify as Unclear/Generic
        if any(r_keyword in domain_name_only for r_keyword in ["foundation", "nonprofit", "charity", "trust"]):
             return "Possibly Relevant (Generic Username, but Relevant Domain)", relevant_score, irrelevant_score
        return "Unclear (Generic or No Keywords)", relevant_score, irrelevant_score


# --- Example Usage ---
if __name__ == "__main__":
    test_emails = [
        'investorinfo@vrtx.com',          # Expected: Likely Irrelevant (Investor)
        'vertex_grants@vrtx.com',         # Expected: Highly Relevant (Grants)
        'mediainfo@vrtx.com',             # Expected: Likely Irrelevant (Media)
        'contact@example.com',            # Expected: Unclear (Generic)
        'info@charityfoundation.org',     # Expected: Possibly Relevant (Relevant Domain)
        'hr@company.com',                 # Expected: Irrelevant (HR/Careers)
        'roboticsclub@school.edu',        # Expected: Relevant (Robotics, School)
        'sponsorships@bigcorp.com',       # Expected: Highly Relevant (Sponsorships)
        'community_outreach@bigcorp.com', # Expected: Highly Relevant (Community, Outreach)
        'sales.info@tech.co',             # Expected: Likely Irrelevant (Sales, Info)
        'education-fund@nonprofit.org',   # Expected: Highly Relevant (Education, Fund, Nonprofit)
        'support_youth_initiatives@ngo.org',# Expected: Highly Relevant
        'john.doe@genericmail.com',       # Expected: Unclear (Generic)
        'csr-team@globalenterprise.net',  # Expected: Relevant (CSR)
        'givingback@charitabletrust.org'  # Expected: Highly Relevant (Giving, Charitable Trust)
    ]

    print("--- Email Classification Test ---")
    for email in test_emails:
        classification, rel_score, irr_score = classify_email_address(email)
        print(f"Email: {email:<40} -> Classification: {classification} (Rel: {rel_score}, Irr: {irr_score})")