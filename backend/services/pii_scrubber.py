import re

def scrub_pii(text: str) -> str:
    """
    Automated PII masking. Replaces emails, phone numbers, and SSN/Credit Card patterns with [REDACTED].
    """
    if not text:
        return text

    original_text = text

    # Email pattern
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    text = re.sub(email_pattern, '[REDACTED_EMAIL]', text)

    # Phone pattern (simplistic US/International)
    phone_pattern = r'(\+?\d{1,2}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
    text = re.sub(phone_pattern, '[REDACTED_PHONE]', text)

    # Basic SSN pattern
    ssn_pattern = r'\b\d{3}-\d{2}-\d{4}\b'
    text = re.sub(ssn_pattern, '[REDACTED_SSN]', text)

    # Basic Credit Card pattern
    cc_pattern = r'\b(?:\d[ -]*?){13,16}\b'
    text = re.sub(cc_pattern, '[REDACTED_CC]', text)

    if original_text != text:
        print("\n" + "="*40)
        print("🛡️  PII SCRUBBER ACTIVATED")
        print("="*40)
        print(f"[ORIGINAL PROMPT]: {original_text}")
        print(f"[MASKED PROMPT]  : {text}")
        print("="*40 + "\n")

    return text
