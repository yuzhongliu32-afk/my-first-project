
import json
from pathlib import Path
from datetime import date
from bisect import bisect_right


def filter_chunks_by_date(chunks, as_of_date):
    """Filter evidence using document or meeting dates."""

    if as_of_date is None:
        return chunks

    cutoff = date.fromisoformat(as_of_date)

    source_dates = json.loads(
        Path("data/source_dates.json").read_text(
            encoding="utf-8"
        )
    )

    meeting_data = json.loads(
        Path("data/meeting_dates.json").read_text(
            encoding="utf-8"
        )
    )

    meeting_doc = meeting_data["document_id"]

    meetings = sorted(
        meeting_data["meetings"],
        key=lambda m: m["start_line"]
    )

    meeting_starts = [
        m["start_line"] for m in meetings
    ]

    allowed = []
    excluded_unknown = set()
    excluded_future = set()
    excluded_boundary = 0
    edc_included = 0

    for chunk in chunks:
        source = chunk["source"]
        document = source["document_id"]

        # Special handling for the six EDC meetings.
        if document == meeting_doc:
            start = source["line_start"]
            end = source["line_end"]

            first = bisect_right(meeting_starts, start) - 1
            last = bisect_right(meeting_starts, end) - 1

            # Exclude undated introductory text.
            if first < 0 or last < 0:
                excluded_boundary += 1
                continue

            # Exclude chunks spanning two meetings.
            # They must not mix different meeting dates.
            if first != last:
                excluded_boundary += 1
                continue

            meeting = meetings[first]
            meeting_date = date.fromisoformat(
                meeting["meeting_date"]
            )

            if meeting_date > cutoff:
                excluded_future.add(meeting["meeting_id"])
                continue

            allowed.append(chunk)
            edc_included += 1
            continue

        # Other files use their registered source dates.
        issued = source_dates.get(document)

        if issued is None:
            excluded_unknown.add(document)
            continue

        if date.fromisoformat(issued) > cutoff:
            excluded_future.add(document)
            continue

        allowed.append(chunk)

    print("\nEvidence cut-off:", as_of_date)
    print("Eligible chunks:", len(allowed))
    print("EDC meeting chunks included:", edc_included)
    print("Cross-meeting/header chunks excluded:",
          excluded_boundary)
    print("Unknown-date sources excluded:",
          sorted(excluded_unknown))
    print("Future sources excluded:",
          sorted(excluded_future))

    if not allowed:
        raise ValueError(
            "No eligible evidence for the selected date."
        )

    return allowed
