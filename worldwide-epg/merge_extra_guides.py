
#!/usr/bin/env python3
"""Fill uncovered XMLTV schedules using manually approved external guide mappings.

Run after add_playlist_aliases.py and before coverage_audit.py.
Only approved mappings are used. Existing programmes are never replaced.
Check upstream providers' redistribution terms before publishing their data.
"""
import csv
import gzip
import logging
import os
import tempfile
import urllib.request
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from lxml import etree

GUIDE = Path('site/epg.xml.gz')
MAPPINGS = Path('worldwide-epg/verified_extra_mappings.csv')
SOURCES = {
    'pluto': 'https://i.mjh.nz/PlutoTV/all.xml.gz',
    'plex': 'https://i.mjh.nz/Plex/all.xml.gz',
    'samsung': 'https://i.mjh.nz/SamsungTVPlus/all.xml.gz',
    'roku': 'https://i.mjh.nz/Roku/all.xml.gz',
}
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def elements(stream):
    """Yield fully populated detached XML elements without retaining parsed siblings."""
    context = etree.iterparse(stream, events=('end',), tag=('channel', 'programme'), huge_tree=True)
    for _, node in context:
        yield deepcopy(node)
        parent = node.getparent()
        node.clear()
        if parent is not None:
            while node.getprevious() is not None:
                del parent[0]


def load_mappings():
    selected = defaultdict(lambda: defaultdict(set))
    if not MAPPINGS.exists():
        logging.info('No verified mapping file; leaving EPG unchanged')
        return selected
    target_sources = {}
    with MAPPINGS.open(newline='', encoding='utf-8-sig') as fh:
        for row in csv.DictReader(fh):
            if (row.get('approved') or '').strip().lower() not in ('true', 'yes', '1'):
                continue
            source, upstream, target = [(row.get(k) or '').strip() for k in
                                        ('source', 'source_channel_id', 'playlist_tvg_id')]
            if source not in SOURCES or not upstream or not target:
                raise ValueError(f'Invalid approved mapping: {row}')
            identity = (source, upstream)
            if target in target_sources and target_sources[target] != identity:
                raise ValueError(f'Conflicting approved mappings for {target}: '
                                 f'{target_sources[target]} vs {identity}')
            target_sources[target] = identity
            selected[source][upstream].add(target)
    return selected


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'WorldwideEPG/1.0'})
    with urllib.request.urlopen(request, timeout=180) as response, \
         tempfile.NamedTemporaryFile(delete=False, suffix='.gz') as tmp:
        while chunk := response.read(1024 * 1024):
            tmp.write(chunk)
        return tmp.name


def main():
    mapping = load_mappings()
    if not mapping:
        logging.info('No approved mappings; leaving EPG unchanged')
        return
    if not GUIDE.exists():
        raise FileNotFoundError(GUIDE)

    existing_channels, covered = set(), set()
    with gzip.open(GUIDE, 'rb') as stream:
        for node in elements(stream):
            if node.tag == 'channel':
                existing_channels.add(node.get('id'))
            elif node.tag == 'programme':
                covered.add(node.get('channel'))

    # A channel definition without programmes is eligible for schedule filling.
    desired = {
        src: {sid: sorted(t for t in targets if t not in covered)
              for sid, targets in sources.items()}
        for src, sources in mapping.items()
    }
    if not any(targets for sources in desired.values() for targets in sources.values()):
        logging.info('All approved targets already have programmes; no changes')
        return

    new_channels = []
    new_programmes = []
    filled_existing = set()
    for source, source_map in desired.items():
        source_map = {sid: targets for sid, targets in source_map.items() if targets}
        if not source_map:
            continue
        path = download(SOURCES[source])
        try:
            found_channels = {}
            programmes = defaultdict(list)
            with gzip.open(path, 'rb') as stream:
                for node in elements(stream):
                    sid = node.get('id') if node.tag == 'channel' else node.get('channel')
                    if sid not in source_map:
                        continue
                    if node.tag == 'channel':
                        found_channels[sid] = node
                    elif node.get('start') and node.get('stop'):
                        programmes[sid].append(node)

            for sid, targets in source_map.items():
                if sid not in found_channels or not programmes[sid]:
                    logging.warning('No complete schedule for %s/%s', source, sid)
                    continue
                for target in targets:
                    if target not in existing_channels:
                        channel = deepcopy(found_channels[sid])
                        channel.set('id', target)
                        new_channels.append(channel)
                        existing_channels.add(target)
                    else:
                        filled_existing.add(target)
                    for programme in programmes[sid]:
                        entry = deepcopy(programme)
                        entry.set('channel', target)
                        new_programmes.append(entry)
        finally:
            os.unlink(path)

    if not new_programmes:
        logging.info('No verified new programme listings; leaving EPG unchanged')
        return

    fd, temp_path = tempfile.mkstemp(prefix='extra-', suffix='.xml.gz', dir=GUIDE.parent)
    os.close(fd)
    try:
        with gzip.open(temp_path, 'wb', compresslevel=6) as dst:
            with etree.xmlfile(dst, encoding='utf-8') as writer:
                writer.write_declaration()
                with writer.element('tv', attrib={
                    'generator-info-name': 'Worldwide EPG + verified external sources'
                }):
                    with gzip.open(GUIDE, 'rb') as src:
                        for node in elements(src):
                            if node.tag == 'channel':
                                writer.write(node)
                    for node in new_channels:
                        writer.write(node)
                    with gzip.open(GUIDE, 'rb') as src:
                        for node in elements(src):
                            if node.tag == 'programme':
                                writer.write(node)
                    for node in new_programmes:
                        writer.write(node)
        os.replace(temp_path, GUIDE)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    logging.info('Added %d channel definitions, filled %d existing channels, '
                 'and added %d programmes', len(new_channels), len(filled_existing),
                 len(new_programmes))


if __name__ == '__main__':
    main()
