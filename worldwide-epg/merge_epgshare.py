
#!/usr/bin/env python3
"""Fill missing worldwide EPG schedules from EPGShare01.

Uses exact IPTV-org playlist IDs only. Does not replace existing schedules.
Verify source redistribution permissions before enabling publication.
"""

import gzip
import logging
import os
import re
import tempfile
import urllib.request
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

from lxml import etree

GUIDE = Path("site/epg.xml.gz")
PLAYLIST_URL = "https://iptv-org.github.io/iptv/index.country.m3u"

SOURCES = [
    "https://epgshare01.online/epgshare01/epg_ripper_US2.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz",
]

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def request(url):
    return urllib.request.Request(
        url, headers={"User-Agent": "WorldwideEPG/1.0"}
    )


def playlist_ids():
    with urllib.request.urlopen(request(PLAYLIST_URL), timeout=120) as response:
        text = response.read().decode("utf-8-sig", errors="replace")
    return set(re.findall(r'tvg-id="([^"]+)"', text))


def elements(stream):
    context = etree.iterparse(
        stream,
        events=("end",),
        tag=("channel", "programme"),
        huge_tree=True,
    )
    for _, node in context:
        yield deepcopy(node)
        parent = node.getparent()
        node.clear()
        if parent is not None:
            while node.getprevious() is not None:
                del parent[0]


def download(url):
    fd, path = tempfile.mkstemp(suffix=".xml.gz")
    os.close(fd)
    try:
        with urllib.request.urlopen(request(url), timeout=180) as response:
            with open(path, "wb") as output:
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise ValueError("Source exceeds 100 MB compressed limit")
                    output.write(chunk)
        return path
    except Exception:
        os.unlink(path)
        raise


def main():
    if not GUIDE.exists():
        raise SystemExit(f"Missing existing EPG: {GUIDE}")

    allowed = playlist_ids()
    known = set()
    covered = set()

    with gzip.open(GUIDE, "rb") as stream:
        for node in elements(stream):
            if node.tag == "channel":
                known.add(node.get("id"))
            elif node.tag == "programme":
                covered.add(node.get("channel"))

    new_channels = {}
    new_programmes = []
    filled = set()

    for url in SOURCES:
        logging.info("Reading %s", url)
        path = None
        try:
            path = download(url)
            definitions = {}
            programmes = defaultdict(list)

            with gzip.open(path, "rb") as stream:
                for node in elements(stream):
                    if node.tag == "channel":
                        cid = node.get("id")
                        if cid in allowed and cid not in covered:
                            definitions[cid] = node
                    else:
                        cid = node.get("channel")
                        if (
                            cid in allowed
                            and cid not in covered
                            and node.get("start")
                            and node.get("stop")
                        ):
                            programmes[cid].append(node)

            for cid, entries in programmes.items():
                if not entries or cid in filled:
                    continue

                if cid not in known and cid not in definitions:
                    continue

                if cid not in known:
                    new_channels[cid] = definitions[cid]
                    known.add(cid)

                new_programmes.extend(entries)
                filled.add(cid)

            logging.info(
                "Completed source; total filled IDs so far: %d", len(filled)
            )
        except Exception as exc:
            logging.warning("Could not process %s: %s", url, exc)
        finally:
            if path and os.path.exists(path):
                os.unlink(path)

    if not new_programmes:
        logging.info("No additional programmes; existing guide unchanged")
        return

    fd, output_path = tempfile.mkstemp(
        prefix="epgshare-", suffix=".xml.gz", dir=GUIDE.parent
    )
    os.close(fd)

    try:
        with gzip.open(output_path, "wb", compresslevel=6) as output:
            with etree.xmlfile(output, encoding="utf-8") as writer:
                writer.write_declaration()
                with writer.element(
                    "tv", attrib={"generator-info-name": "Worldwide EPG"}
                ):
                    with gzip.open(GUIDE, "rb") as source:
                        for node in elements(source):
                            if node.tag == "channel":
                                writer.write(node)

                    for node in new_channels.values():
                        writer.write(node)

                    with gzip.open(GUIDE, "rb") as source:
                        for node in elements(source):
                            if node.tag == "programme":
                                writer.write(node)

                    for node in new_programmes:
                        writer.write(node)

        os.replace(output_path, GUIDE)
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)

    logging.info(
        "EPGShare01 added %d new channel definitions, "
        "filled %d channel schedules, and added %d programmes",
        len(new_channels),
        len(filled),
        len(new_programmes),
    )


if __name__ == "__main__":
    main()
