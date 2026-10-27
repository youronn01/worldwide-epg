
#!/usr/bin/env python3
"""Read-only EPGShare01 schedule comparison."""

import csv
import gzip
import re
import unicodedata
import urllib.request
from bisect import bisect_left, bisect_right
from collections import defaultdict, Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from lxml import etree

SOURCE = "https://epgshare01.online/epgshare01/epg_ripper_ALL_SOURCES1.xml.gz"
REFERENCE = "https://youronn01.github.io/worldwide-epg/epg.xml.gz"
MAPPINGS = Path("worldwide-epg/epgshare_mapping_verification_review.csv")
OUT = Path("schedule-validation-reports")


def normalize(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def parse_time(value):
    match = re.match(r"^(\d{12}|\d{14})(?:\s*([+-]\d{4}))?", value or "")
    if not match:
        return None
    digits, offset = match.groups()
    if len(digits) == 12:
        digits += "00"
    try:
        if offset:
            return datetime.strptime(
                digits + offset, "%Y%m%d%H%M%S%z"
            ).timestamp()
        return datetime.strptime(
            digits, "%Y%m%d%H%M%S"
        ).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def extract(url, wanted):
    result = defaultdict(list)
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        with gzip.GzipFile(fileobj=response) as stream:
            context = etree.iterparse(
                stream, events=("end",),
                tag="programme", huge_tree=True
            )
            for _, node in context:
                cid = node.get("channel")
                if cid in wanted:
                    start = parse_time(node.get("start"))
                    title = normalize(node.findtext("title"))
                    if start is not None and title:
                        result[cid].append((start, title))
                node.clear()
                parent = node.getparent()
                if parent is not None:
                    while node.getprevious() is not None:
                        del parent[0]
    for cid in result:
        result[cid].sort()
    return result


def compare(source, reference):
    times = [t for t, _ in reference]
    comparable = matching = 0

    for start, title in source:
        left = bisect_left(times, start - 900)
        right = bisect_right(times, start + 900)
        if left == right:
            continue
        comparable += 1
        if any(
            SequenceMatcher(None, title, other).ratio() >= 0.85
            for _, other in reference[left:right]
        ):
            matching += 1

    return comparable, matching


def main():
    OUT.mkdir(exist_ok=True)

    with MAPPINGS.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    source_ids = {r["source_id"] for r in rows}
    playlist_ids = {r["playlist_id"] for r in rows}

    print("Reading worldwide EPGShare01...", flush=True)
    source = extract(SOURCE, source_ids)

    print("Reading existing published EPG...", flush=True)
    try:
        reference = extract(REFERENCE, playlist_ids)
        reference_error = ""
    except Exception as exc:
        reference = {}
        reference_error = str(exc)
        print("Reference unavailable:", reference_error, flush=True)

    report = []
    summary = Counter()

    for row in rows:
        sid = row["source_id"]
        pid = row["playlist_id"]
        a = source.get(sid, [])
        b = reference.get(pid, [])

        comparable, matching = (
            compare(a, b) if a and b else (0, 0)
        )

        if reference_error:
            status = "REFERENCE_UNAVAILABLE"
        elif not a:
            status = "NO_SOURCE_PROGRAMMES"
        elif not b:
            status = "NO_REFERENCE_PROGRAMMES"
        elif comparable < 5:
            status = "INSUFFICIENT_COMPARABLE_LISTINGS"
        elif matching / comparable >= 0.8:
            status = "GUIDES_AGREE_NOT_STREAM_VERIFIED"
        else:
            status = "GUIDES_DISAGREE_OR_DIFFERENT_VARIANT"

        summary[status] += 1

        report.append({
            "playlist_id": pid,
            "source_id": sid,
            "priority": row.get("priority", ""),
            "source_programmes": len(a),
            "reference_programmes": len(b),
            "comparable": comparable,
            "matching": matching,
            "agreement_ratio": (
                round(matching / comparable, 3)
                if comparable else ""
            ),
            "status": status,
            "approved": "NO",
        })

    with (OUT / "schedule_comparison.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=report[0].keys())
        writer.writeheader()
        writer.writerows(report)

    print("\n=== VERIFICATION SUMMARY ===")
    print("Total candidate rows:", len(rows))
    for status, count in summary.most_common():
        print(f"{status}: {count}")
    print("Reports saved to:", OUT, flush=True)


if __name__ == "__main__":
    main()
