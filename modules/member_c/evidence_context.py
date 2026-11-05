
import json
from pathlib import Path
from functools import lru_cache
from bisect import bisect_right
from datetime import date


@lru_cache(maxsize=1)
def load_evidence():
    return json.loads(
        Path("data/evidence_index.json").read_text(
            encoding="utf-8"
        )
    )


def expand_reference(ref, context_lines=6, as_of_date=None):
    """Expand evidence without crossing meeting or date boundaries."""

    records = load_evidence()
    document = ref["document_id"]

    start = max(1, ref["line_start"] - context_lines)
    end = ref["line_end"] + context_lines

    meeting_data = json.loads(
        Path("data/meeting_dates.json").read_text(
            encoding="utf-8"
        )
    )

    if document == meeting_data["document_id"]:
        meetings = sorted(
            meeting_data["meetings"],
            key=lambda x: x["start_line"]
        )
        starts = [m["start_line"] for m in meetings]

        index = bisect_right(starts, ref["line_start"]) - 1
        end_index = bisect_right(starts, ref["line_end"]) - 1

        if index < 0 or index != end_index:
            raise ValueError("Citation crosses meeting boundaries.")

        meeting = meetings[index]

        if as_of_date is not None:
            if date.fromisoformat(
                meeting["meeting_date"]
            ) > date.fromisoformat(as_of_date):
                raise ValueError("Future meeting evidence blocked.")

        start = max(start, meeting["start_line"])

        if index + 1 < len(meetings):
            end = min(end, meetings[index + 1]["start_line"] - 1)

    elif as_of_date is not None:
        source_dates = json.loads(
            Path("data/source_dates.json").read_text(
                encoding="utf-8"
            )
        )
        issued = source_dates.get(document)

        if issued is None:
            raise ValueError("Source date is unknown.")

        if date.fromisoformat(issued) > date.fromisoformat(as_of_date):
            raise ValueError("Future evidence blocked.")

    matching = [
        r for r in records
        if r["document_id"] == document
        and r["document_version"] == ref["document_version"]
        and r["page"] == ref["page"]
        and start <= r["line_start"] <= end
    ]

    matching.sort(key=lambda r: r["line_start"])

    if not matching:
        raise ValueError("Evidence source not found.")

    expanded = dict(ref)
    expanded["line_start"] = matching[0]["line_start"]
    expanded["line_end"] = matching[-1]["line_end"]
    expanded["quote"] = "\n".join(
        r["quote"] for r in matching
    )
    expanded["chunk_id"] = (
        f"{document}:P{ref['page']}:"
        f"L{expanded['line_start']}-{expanded['line_end']}"
    )

    return expanded
