#!/usr/bin/env python3
"""Audit IPTV-org worldwide playlist coverage and discover additional guide sources.
Read-only: does not modify the published XMLTV file.
"""
import csv
import gzip
import json
import logging
import re
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

PLAYLIST = 'https://iptv-org.github.io/iptv/index.country.m3u'
GUIDES = 'https://iptv-org.github.io/api/guides.json'
EPG = Path('site/epg.xml.gz')
REPORTS = Path('coverage-reports')
ID_RE = re.compile(r'tvg-id="([^"]*)"')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'WorldwideEPGAudit/1.0'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def base_id(value):
    return value.split('@', 1)[0]


def read_playlist():
    lines = get(PLAYLIST).decode('utf-8-sig', errors='replace').splitlines()
    entries = []
    for line in lines:
        if line.startswith('#EXTINF:'):
            match = ID_RE.search(line)
            if match and match.group(1):
                entries.append(match.group(1))
    return entries


def read_epg():
    channels, with_programmes = set(), set()
    with gzip.open(EPG, 'rb') as stream:
        for _, element in ET.iterparse(stream, events=('end',)):
            if element.tag == 'channel':
                if element.get('id'):
                    channels.add(element.get('id'))
            elif element.tag == 'programme':
                if element.get('channel'):
                    with_programmes.add(element.get('channel'))
            element.clear()
    return channels, with_programmes


def main():
    if not EPG.exists():
        raise SystemExit(f'Missing {EPG}; run merge.py and add_playlist_aliases.py first')
    REPORTS.mkdir(exist_ok=True)
    playlist = read_playlist()
    guides = json.loads(get(GUIDES))
    epg_channels, programme_ids = read_epg()
    mapping = defaultdict(list)
    for guide in guides:
        channel = guide.get('channel')
        if channel:
            mapping[(channel, guide.get('feed') or '')].append(guide)
    results = []
    for tvg_id in sorted(set(playlist)):
        base, sep, feed = tvg_id.partition('@')
        has_programmes = tvg_id in programme_ids
        candidates = mapping.get((base, feed), [])
        if not candidates:
            candidates = mapping.get((base, ''), [])
        # Fallback to any feed: candidate only, never automatically assign.
        if not candidates:
            candidates = [g for (ch, _), gs in mapping.items() if ch == base for g in gs]
        sources = sorted({s.get('url', '') for g in candidates for s in (g.get('sources') or []) if isinstance(s, dict) and s.get('url')})
        sites = sorted({g.get('site', '') for g in candidates if g.get('site')})
        if has_programmes:
            status = 'covered'
        elif candidates:
            status = 'guide_mapping_found'
        else:
            status = 'no_guide_mapping'
        results.append({
            'playlist_tvg_id': tvg_id,
            'base_channel_id': base,
            'feed': feed,
            'status': status,
            'epg_channel_exists': str(tvg_id in epg_channels).lower(),
            'candidate_guide_sites': ';'.join(sites),
            'candidate_source_urls': ';'.join(sources),
        })
    report_file = REPORTS / 'channel_coverage.csv'
    with report_file.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]) if results else [
            'playlist_tvg_id', 'base_channel_id', 'feed', 'status',
            'epg_channel_exists', 'candidate_guide_sites', 'candidate_source_urls'])
        writer.writeheader()
        writer.writerows(results)
    counts = Counter(r['status'] for r in results)
    summary = {
        'playlist_entries': len(playlist),
        'unique_playlist_ids': len(results),
        'epg_channel_ids': len(epg_channels),
        'epg_ids_with_programmes': len(programme_ids),
        'covered_unique_ids': counts['covered'],
        'uncovered_with_guide_mapping': counts['guide_mapping_found'],
        'uncovered_without_guide_mapping': counts['no_guide_mapping'],
        'note': 'A guide mapping is a lead, not proof that programme data can be downloaded or redistributed.',
    }
    (REPORTS / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    for key, value in summary.items():
        logging.info('%s: %s', key, value)
    logging.info('Wrote %s and %s', report_file, REPORTS / 'summary.json')


if __name__ == '__main__':
    main()
