"""Best-effort credential masking before model use and durable chat storage."""
import os
import re


def redact(text: str) -> str:
    for name in ("OPENAI_API_KEY", "PINECONE_API_KEY", "SUPABASE_SECRET_KEY", "LANGSMITH_API_KEY", "SUPABASE_ACCESS_TOKEN", "SUPABASE_DB_PASSWORD"):
        secret = os.getenv(name, "")
        if len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"\b(?:sk-|pcsk_|sb_secret_|lsv2_|ls__)[A-Za-z0-9_-]{12,}", "[REDACTED]", text)
    return re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._-]{12,}", "Bearer [REDACTED]", text)
