"""The vocabulary of the data files (see docs/DESIGN.md)."""

# Databases a production can be keyed by.
NAMESPACES = ("demozoo", "csdb")

# How an entry was found, least trusted first.
SOURCES = ("script", "ai", "verified")

RESULTS = ("broken", "crashes-later", "unknown")

KINDS = ("collection", "standalone", "separate-disks", "menu", "boot_fresh")

# What the production is started from, when it is not the first thing its
# download offers.
BOOTS = ("floppy", "hd")

# The shape of the area a production draws into, when it is not the
# screen's.
ASPECT_16_9 = "16:9"
ASPECTS = (ASPECT_16_9,)


def bucket(title):
    """The file a production is kept in: the first character of its title."""
    c = title[:1].lower()
    if "a" <= c <= "z":
        return c
    if "0" <= c <= "9":
        return "0-9"
    return "misc"
