"""Add exact IPTV-org tvg-id aliases to an existing merged XMLTV guide.

Run after merge.py: python worldwide-epg/add_playlist_aliases.py
Reads site/epg.xml.gz and writes it atomically after generating aliases.
"""
import collections
import gzip
import logging
import os
import re
import tempfile
import urllib.request
from pathlib import Path
from lxml import etree

PLAYLIST = 'https://iptv-org.github.io/iptv/index.country.m3u'
GUIDE = Path('site/epg.xml.gz')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def get_playlist_ids():
    req = urllib.request.Request(PLAYLIST, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=90) as resp:
        content = resp.read().decode('utf-8-sig', errors='replace')
    ids = re.findall(r'^#EXTINF:[^\n]*\btvg-id="([^"]+)"', content, flags=re.M)
    by_base = collections.defaultdict(set)
    for identifier in ids:
        if '@' in identifier:
            by_base[identifier.split('@', 1)[0]].add(identifier)
    return ids, by_base


def iter_elements(stream):
    context = etree.iterparse(stream, events=('end',), tag=('channel', 'programme'), huge_tree=True)
    for _, node in context:
        yield node
        node.clear()
        parent = node.getparent()
        while parent is not None and node.getprevious() is not None:
            del parent[0]


def main():
    if not GUIDE.is_file():
        raise FileNotFoundError(f'Missing {GUIDE}; run merge.py first')
    playlist_ids, by_base = get_playlist_ids()
    existing = set()
    with gzip.open(GUIDE, 'rb') as src:
        for node in iter_elements(src):
            if node.tag == 'channel' and node.get('id'):
                existing.add(node.get('id'))
    aliases = {base: sorted(variants - existing) for base, variants in by_base.items()
               if base in existing and (variants - existing)}
    alias_count = sum(len(v) for v in aliases.values())
    logging.info('Playlist entries: %d; unique IDs: %d', len(playlist_ids), len(set(playlist_ids)))
    logging.info('Existing EPG IDs: %d; new alias IDs: %d', len(existing), alias_count)
    fd, temp_name = tempfile.mkstemp(prefix='epg-aliased-', suffix='.xml.gz', dir=GUIDE.parent)
    os.close(fd)
    channel_aliases = programme_aliases = 0
    try:
        with gzip.open(GUIDE, 'rb') as src, gzip.open(temp_name, 'wb', compresslevel=6) as dst:
            with etree.xmlfile(dst, encoding='utf-8') as writer:
                writer.write_declaration()
                with writer.element('tv', attrib={'generator-info-name': 'Worldwide EPG Merge + IPTV-org IDs'}):
                    for node in iter_elements(src):
                        if node.tag == 'channel':
                            key = node.get('id')
                            writer.write(node)
                            for alias in aliases.get(key, ()):
                                # Copy metadata from the source channel.
                                copy = etree.fromstring(etree.tostring(node))
                                copy.set('id', alias)
                                writer.write(copy)
                                channel_aliases += 1
                        else:
                            key = node.get('channel')
                            writer.write(node)
                            for alias in aliases.get(key, ()):
                                copy = etree.fromstring(etree.tostring(node))
                                copy.set('channel', alias)
                                writer.write(copy)
                                programme_aliases += 1
        os.replace(temp_name, GUIDE)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    logging.info('Created %d channel aliases and %d programme aliases', channel_aliases, programme_aliases)
    logging.info('Output: %s (%d bytes)', GUIDE, GUIDE.stat().st_size)


if __name__ == '__main__':
    main()
