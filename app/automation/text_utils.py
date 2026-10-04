import re

def normalize_survey_identifier(text: str) -> str:
    """
    Robust normalization for Survey/Gat/Hissa identifiers.
    Safely handles leading/trailing whitespace and repeated internal whitespace.
    Does NOT perform fuzzy matching (like removing punctuation or changing characters)
    because survey selection must remain exact and deterministic.
    """
    if not text:
        return ""
    # Strip and collapse internal whitespace
    return re.sub(r'\s+', ' ', text.strip())
