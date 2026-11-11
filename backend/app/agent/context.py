"""Resolve an unresolved ordinal query without embedding the whole history."""
import re

from app.agent.privacy import redact
from app.schemas.error import ApiException

ORDINALS = {word: i for i, word in enumerate(
    ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"), 1)}
REFERENCE = re.compile(r"\b(?:the|your|our)?\s*(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|[1-9]\d?(?:st|nd|rd|th)?)\s+(?:one|point|topic|item|takeaway)\b", re.I)
ITEM = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?(\d{1,2})[.)]\s+(.+)$")


def resolve_search_query(query, history):
    if re.search(r"\b(?:in|of|from)\s+(?:this|the)\s+(?:video|transcript)\b", query, re.I):
        return query  # Explicit video-relative topic, not a conversation ordinal.
    match = REFERENCE.search(query)
    if match is None:
        return query
    ordinal = match.group(1).lower()
    number = ORDINALS.get(ordinal)
    if number is None:
        number = int(re.match(r"\d+", ordinal).group())
    # Only explicit numbered items establish an unambiguous server-side referent.
    # The native model can still produce an already-resolved query for other
    # conversation forms. Never guess a topic from an arbitrary paragraph.
    for row in reversed(history[-40:]):
        if row.get("role") != "assistant" or not isinstance(row.get("content"), str):
            continue
        numbered = [m for line in row["content"].splitlines() if (m := ITEM.match(line))]
        if not numbered:
            continue
        items = [m for m in numbered if int(m.group(1)) == number]
        if len(items) == 1:
            hint = redact(items[0].group(2)).strip(" *`\t")[:600]
            # Reserve space for one bounded context hint, preserving the intent.
            resolved = f"{query[:1000]}\nReferenced topic (context only, not evidence): {hint}"
            if len(resolved.encode("utf-8")) <= 8000:
                return resolved
        break  # Never substitute an older list for a missing/ambiguous recent item.
    raise ApiException(422, "FOLLOWUP_CONTEXT_REQUIRED", "Please name the topic to explain; the available conversation does not identify that numbered point clearly.")
