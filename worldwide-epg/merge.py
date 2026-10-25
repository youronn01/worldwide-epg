import gzip
import logging
import os
import tempfile
import urllib.request
from pathlib import Path
from lxml import etree

CODES = '''al ar am au at bs by be bo ba br bg ca cl co cr hr cw cz dk do ec sv fi fr ge de gh gr gt hn hk hu is in id il it jm jp lv lt lu my mt mx me nl nz ni ng no pa py pe pl pt ro ru rs sg za kr es se ch tw th tt tr ug ua gb us uy ve zw'''.split()
BASE = 'https://iptv-epg.org/files/epg-{}.xml.gz'
OUT = Path('site')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

def download(code):
    req = urllib.request.Request(BASE.format(code), headers={'User-Agent': 'WorldwideEPGMerger/1.0', 'Accept-Encoding': 'identity'})
    with urllib.request.urlopen(req, timeout=180) as response, tempfile.NamedTemporaryFile(delete=False) as tmp:
        while True:
            data = response.read(1024 * 1024)
            if not data: break
            tmp.write(data)
        return tmp.name

def entries(path):
    with gzip.open(path, 'rb') as stream:
        context = etree.iterparse(stream, events=('end',), tag=('channel', 'programme'), recover=False, huge_tree=True)
        for _, node in context:
            yield node
            # Clear parsed siblings to bound memory usage.
            node.clear(keep_tail=True) if False else None
            parent = node.getparent()
            if parent is not None:
                while node.getprevious() is not None:
                    del parent[0]

def main():
    OUT.mkdir(exist_ok=True)
    paths = []
    for code in CODES:
        try:
            path = download(code)
            # Check that gzip is valid and XML parses before merging.
            with gzip.open(path, 'rb') as f:
                for _ in etree.iterparse(f, events=('end',), tag=('channel', 'programme'), recover=False, huge_tree=True):
                    pass
            paths.append((code, path))
            logging.info('Downloaded %s', code)
        except Exception as exc:
            logging.warning('Skipping %s: %s', code, exc)
            if 'path' in locals() and os.path.exists(path): os.unlink(path)
    if len(paths) < 60:
        raise RuntimeError(f'Only {len(paths)} guides available; refusing to publish incomplete EPG')
    seen_channels = set()
    seen_programmes = set()
    count = [0, 0]
    try:
        with gzip.open(OUT / 'epg.xml.gz', 'wb', compresslevel=6) as compressed:
            with etree.xmlfile(compressed, encoding='utf-8') as writer:
                writer.write_declaration()
                with writer.element('tv', attrib={'generator-info-name': 'Worldwide EPG Merge'}):
                    for kind in ('channel', 'programme'):
                        for code, path in paths:
                            for node in entries(path):
                                if node.tag != kind: continue
                                if kind == 'channel':
                                    key = node.get('id')
                                    if not key or key in seen_channels: continue
                                    seen_channels.add(key)
                                    count[0] += 1
                                else:
                                    key = (node.get('channel'), node.get('start'), node.get('stop'))
                                    if not all(key) or key in seen_programmes: continue
                                    seen_programmes.add(key)
                                    count[1] += 1
                                writer.write(node)
    finally:
        for _, path in paths: os.unlink(path)
    logging.info('Merged %d countries, %d channels, %d programmes', len(paths), *count)
    (OUT / 'index.html').write_text('<h1>Worldwide EPG</h1><p>Use <a href="epg.xml.gz">epg.xml.gz</a> in your IPTV player.</p>', encoding='utf-8')
    (OUT / '.nojekyll').touch()

if __name__ == '__main__': main()
