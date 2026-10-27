
#!/usr/bin/env python3
"""Inspect EPGShare01 worldwide channel compatibility.

Reports candidates only. Never modifies or republishes EPG data.
"""

import csv
import gzip
import re
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from lxml import etree

SOURCE = (
    "https://epgshare01.online/epgshare01/"
    "epg_ripper_ALL_SOURCES1.xml.gz"
)
PLAYLIST = "https://iptv-org.github.io/iptv/index.country.m3u"
PUBLISHED = (
    "https://youronn01.github.io/worldwide-epg/epg.xml.gz"
)
OUT = Path("epgshare-reports")


def open_url(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    return urllib.request.urlopen(req, timeout=180)


def normalize(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(
        c for c in value if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]", "", value.lower())


def country(channel_id):
    base = channel_id.split("@", 1)[0]
    parts = base.rsplit(".", 1)
    if len(parts) == 2:
        suffix = parts[1].lower()
        if re.fullmatch(r"[a-z]{2}", suffix):
            return suffix
    return ""


def read_playlist():
    with open_url(PLAYLIST) as response:
        lines = response.read().decode(
            "utf-8-sig", errors="replace"
        ).splitlines()

    channels = {}
    for line in lines:
        if not line.startswith("#EXTINF:"):
            continue
        match = re.search(r'tvg-id="([^"]+)"', line)
        if not match:
            continue
        cid = match.group(1)
        name_match = re.search(r'tvg-name="([^"]+)"', line)
        name = (
            name_match.group(1)
            if name_match else line.rsplit(",", 1)[-1]
        )
        channels.setdefault(cid, name)
    return channels


def read_covered():
    covered = set()
    try:
        with open_url(PUBLISHED) as response:
            with gzip.GzipFile(fileobj=response) as stream:
                context = etree.iterparse(
                    stream, events=("end",),
                    tag=("channel", "programme"),
                    huge_tree=True,
                )
                for _, node in context:
                    if node.tag == "programme":
                        cid = node.get("channel")
                        if cid:
                            covered.add(cid)
                    node.clear()
                    parent = node.getparent()
                    if parent is not None:
                        while node.getprevious() is not None:
                            del parent[0]
    except Exception as exc:
        print("Could not inspect published EPG:", exc)
        print("Existing coverage will be marked unknown.")
        return None
    return covered


def read_epgshare():
    channels = {}
    programmes = Counter()

    with open_url(SOURCE) as response:
        with gzip.GzipFile(fileobj=response) as stream:
            context = etree.iterparse(
                stream, events=("end",),
                tag=("channel", "programme"),
                huge_tree=True,
            )
            for _, node in context:
                if node.tag == "channel":
                    cid = node.get("id")
                    if cid:
                        channels[cid] = (
                            node.findtext("display-name") or cid
                        )
                elif node.tag == "programme":
                    cid = node.get("channel")
                    if cid:
                        programmes[cid] += 1

                node.clear()
                parent = node.getparent()
                if parent is not None:
                    while node.getprevious() is not None:
                        del parent[0]

    return channels, programmes


def save_csv(filename, fields, rows):
    with (OUT / filename).open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(exist_ok=True)

    print("Reading IPTV-org playlist...", flush=True)
    playlist = read_playlist()

    print("Reading published EPG coverage...", flush=True)
    covered = read_covered()

    print("Reading EPGShare01 worldwide...", flush=True)
    source, programmes = read_epgshare()

    exact = []
    candidates = []

    # Only suggest matches in the same two-letter country.
    # Matching names do NOT prove identical regional feeds.
    index = defaultdict(list)
    for sid, name in source.items():
        if programmes[sid] == 0:
            continue
        key = (country(sid), normalize(name))
        if key[0] and key[1]:
            index[key].append(sid)

    for pid, name in playlist.items():
        status = (
            "unknown" if covered is None
            else "covered" if pid in covered
            else "uncovered"
        )

        if programmes[pid] > 0:
            exact.append({
                "playlist_id": pid,
                "playlist_name": name,
                "programme_count": programmes[pid],
                "coverage_status": status,
            })
            continue

        key = (country(pid), normalize(name))
        for sid in index.get(key, []):
            candidates.append({
                "playlist_id": pid,
                "playlist_name": name,
                "epgshare_id": sid,
                "epgshare_name": source[sid],
                "programme_count": programmes[sid],
                "coverage_status": status,
                "match_type": "same_country_exact_name",
                "approved": "NO",
            })

    save_csv(
        "exact_matches.csv",
        ["playlist_id", "playlist_name",
         "programme_count", "coverage_status"],
        exact,
    )
    save_csv(
        "review_candidates.csv",
        ["playlist_id", "playlist_name",
         "epgshare_id", "epgshare_name",
         "programme_count", "coverage_status",
         "match_type", "approved"],
        candidates,
    )

    print("\n=== WORLDWIDE MATCHING REPORT ===")
    print("Playlist unique IDs:", len(playlist))
    print("EPGShare01 channel IDs:", len(source))
    print("EPGShare01 channels with programmes:",
          sum(v > 0 for v in programmes.values()))
    print("Exact matches with programmes:", len(exact))
    print("Name-based candidates for review:",
          len(candidates))
    print("Uncovered exact matches:",
          sum(r["coverage_status"] == "uncovered"
              for r in exact))
    print("Uncovered candidate rows:",
          sum(r["coverage_status"] == "uncovered"
              for r in candidates))
    print("Reports saved in:", OUT)


if __name__ == "__main__":
    main()
