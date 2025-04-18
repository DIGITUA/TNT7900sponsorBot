import re

# Define keyword categories
relevant_keywords = [
    "grant", "fund", "sponsor", "youth", "stem", "education", "robotics",
    "student", "nonprofit", "outreach", "school", "scholarship"
]

irrelevant_keywords = [
    "support", "help", "service", "order", "vendor", "supplier", "media",
    "press", "investor", "invest", "returns", "billing", "invoice", "ads",
    "info", "sales", "marketing"
]

def classify_email_address(email_address: str) -> str:
    email_address = email_address.lower()

    # Split email into parts
    username1, domain = email_address.split("@")
    domain_name = domain.split(".")[0]  # Remove TLD (.com, .org, etc.)

    username = username1.split("_")

    # Combine all parts to check
    combined = f"{username}.{domain_name}"

    # Count matches
    relevant_count = sum(bool(re.search(rf"\b{re.escape(keyword)}\b", combined)) for keyword in relevant_keywords)
    irrelevant_count = sum(bool(re.search(rf"\b{re.escape(keyword)}\b", combined)) for keyword in irrelevant_keywords)

    print("relevant count: " + str(relevant_count), "irrelecant count:  "+ str(irrelevant_count))

    if relevant_count > 0 and irrelevant_count == 0:
        return "Relevant (grant/sponsor/STEM/youth)"
    elif irrelevant_count > 0 and relevant_count == 0:
        return "Irrelevant (customer service/supplier/media/investor)"
    elif relevant_count > irrelevant_count:
        return "Mostly Relevant"
    elif irrelevant_count > relevant_count:
        return "Mostly Irrelevant"
    else:
        return "Unclear"


# Example usage
if __name__ == "__main__":
    test_emails = [
        'investorinfo@vrtx.com', 'vertex_grants@vrtx.com', 'mediainfo@vrtx.com'
    ]

    for email in test_emails:
        result = classify_email_address(email)
        print(f"{email}: {result}")