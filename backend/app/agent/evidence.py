"""Original sources are registered server-side; models select IDs, never quotes."""
from app.schemas.chat import SourceSegment
from app.schemas.error import ApiException


class Evidence:
    def __init__(self, video_id):
        self.video_id = video_id
        self.rows = {}
        self.keys = {}

    def add(self, text, start, end, **metadata):
        key = (text, start, end)
        if key not in self.keys:
            ident = len(self.rows)
            self.keys[key] = ident
            self.rows[ident] = dict(metadata, evidence_id=ident, video_id=self.video_id,
                text=text, start_seconds=start, end_seconds=end)
        return self.rows[self.keys[key]]

    def sources(self, ids):
        ids = list(dict.fromkeys(ids))
        if not ids or any(isinstance(i, bool) or i not in self.rows for i in ids):
            raise ApiException(502, "RAG_RESPONSE_INVALID", "The model did not return verifiable video sources. Please try again.")
        return [SourceSegment(**{k: self.rows[i][k] for k in ("text", "start_seconds", "end_seconds")}) for i in ids]
