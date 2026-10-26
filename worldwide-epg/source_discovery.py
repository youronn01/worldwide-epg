#!/usr/bin/env python3
"""Rank IPTV-org EPG provider mappings for currently uncovered channels.
Read-only: this is discovery, not a programme downloader or EPG merger.
Run after coverage_audit.py from the repository root.
"""
import csv
import json
import logging
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

GUIDES_URL = 'https://iptv-org.github.io/api/guides.json'
INPUT = Path('coverage-reports/channel_coverage.csv')
OUTPUT = Path('coverage-reports')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def fetch_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'WorldwideEPGSourceDiscovery/1.0'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def main():
    if not INPUT.is_file():
        raise SystemExit(f'Missing {INPUT}; run coverage_audit.py first')
    guides = fetch_json(GUIDES_URL)
    by_channel = defaultdict(list)
    for item in guides:
        if isinstance(item, dict) and item.get('channel') and item.get('site'):
            by_channel[item['channel']].append(item)

    site_channels = defaultdict(set)
    site_exact = Counter()
    rows = []
    with INPUT.open(newline='', encoding='utf-8') as file:
        for row in csv.DictReader(file):
            if row['status'] == 'covered':
                continue
            base = row['base_channel_id']
            feed = row['feed']
            matches = by_channel.get(base, [])
            for item in matches:
                provider_feed = item.get('feed') or ''
                match_type = 'exact_feed' if provider_feed == feed else ('default_feed' if not provider_feed else 'other_feed_review_required')
                site = item['site']
                site_channels[site].add(row['playlist_tvg_id'])
                if match_type == 'exact_feed':
                    site_exact[site] += 1
                rows.append({
                    'playlist_tvg_id': row['playlist_tvg_id'],
                    'site': site,
                    'provider_channel_id': item.get('site_id') or '',
                    'provider_feed': provider_feed,
                    'match_type': match_type,
                    'lang': item.get('lang') or '',
                    'note': 'Provider mapping only; actual listings, accessibility, and usage rights unverified',
                })

    OUTPUT.mkdir(exist_ok=True)
    with (OUTPUT / 'provider_candidates.csv').open('w', newline='', encoding='utf-8') as file:
        fields = ['playlist_tvg_id', 'site', 'provider_channel_id', 'provider_feed', 'match_type', 'lang', 'note']
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    rankings = sorted(site_channels, key=lambda s: (-len(site_channels[s]), s))
    with (OUTPUT / 'provider_priority.csv').open('w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['provider_site', 'unique_uncovered_ids_with_mapping', 'exact_feed_mapping_rows', 'status'])
        for site in rankings:
            writer.writerow([site, len(site_channels[site]), site_exact[site], 'NOT VALIDATED: check guide grabber and permissions'])
    summary = {
        'uncovered_ids_with_at_least_one_provider_mapping': len(set().union(*site_channels.values())) if site_channels else 0,
        'provider_sites': len(site_channels),
        'candidate_mapping_rows': len(rows),
        'warning': 'These are guide mappings, not validated downloadable XMLTV sources. Counts overlap across providers.',
    }
    (OUTPUT / 'source_discovery_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    logging.info('Found %s providers and %s candidate mappings', len(site_channels), len(rows))
    for site in rankings[:15]:
        logging.info('%s: %s uncovered IDs', site, len(site_channels[site]))
    logging.info('Wrote provider_priority.csv, provider_candidates.csv, source_discovery_summary.json')


if __name__ == '__main__':
    main()
