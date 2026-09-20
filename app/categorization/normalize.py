import re
import unicodedata


def normalize_description(text: str) -> str:
    """Mayúsculas, sin tildes, espacios colapsados — para que las reglas de
    categorización sean robustas a variaciones de formato entre bancos."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.upper()
    text = re.sub(r"\s+", " ", text).strip()
    return text
