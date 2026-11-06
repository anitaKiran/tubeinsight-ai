"""Validate Pinecone metadata while retaining exact Supabase timestamps."""

import math


def metadata_matches(actual: dict, expected: dict) -> bool:
    for key, value in expected.items():
        stored = actual.get(key)
        if key in {"start_seconds", "end_seconds"}:
            if isinstance(stored, bool) or not isinstance(stored, (int, float)):
                return False
            # Pinecone can round numeric metadata to float32. Never return this
            # rounded value: all API sources are built from the Supabase plan.
            if not math.isfinite(stored) or not math.isclose(stored, value, rel_tol=1e-7, abs_tol=1e-6):
                return False
        elif stored != value:
            return False
    return True
