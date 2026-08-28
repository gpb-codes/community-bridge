import re
import unicodedata


def normalize_channel_name(name: str) -> str:
    """Convert a human name to a Discord-safe channel slug.

    "Inteligencia Artificial" -> "inteligencia-artificial"
    "Ciberseguridad Chile"   -> "ciberseguridad-chile"
    "Programación 💻"        -> "programacion"
    """
    # strip emojis / symbols
    name = "".join(ch for ch in name if not unicodedata.category(ch).startswith(("So", "Sk", "Sm")))
    # normalize accents
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    # lowercase
    name = name.lower()
    # replace anything not alphanumeric or hyphen/space with space
    name = re.sub(r"[^a-z0-9]+", " ", name)
    # collapse spaces to single hyphen, strip
    name = re.sub(r"\s+", "-", name).strip("-")
    # Discord channel name constraints: lowercase, 1-100 chars, alnum + -_
    name = name[:100] or "channel"
    return name


_DISCORD_FORBIDDEN = set()


def is_valid_discord_channel_name(name: str) -> bool:
    if not name or len(name) > 100:
        return False
    return bool(re.fullmatch(r"[a-z0-9\-_]+", name))
