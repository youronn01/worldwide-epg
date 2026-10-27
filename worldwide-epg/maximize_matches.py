
#!/usr/bin/env python3
"""Worldwide EPG candidate discovery only. Does not publish or approve mappings."""
import csv, gzip, io, json, re, unicodedata, urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from difflib import SequenceMatcher
from lxml import etree

PLAYLIST='https://iptv-org.github.io/iptv/index.country.m3u'
CHANNELS='https://iptv-org.github.io/api/channels.json'
SOURCE='https://epgshare01.online/epgshare01/epg_ripper_ALL_SOURCES1.xml.gz'
OUT=Path('max-match-reports'); OUT.mkdir(exist_ok=True)

def get(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=180)

def norm(s):
    s=unicodedata.normalize('NFKD',s or '')
    return re.sub(r'[^a-z0-9]','', ''.join(x for x in s if not unicodedata.combining(x)).lower())

def country(cid):
    # Treat source-specific suffixes (e.g. .us2) as candidates for US, never as verified.
    base=cid.split('@')[0]
    match=re.search(r'\.([a-z]{2})(?:\d+)?$',base,re.I)
    return match.group(1).lower() if match else ''

def parse_playlist():
    with get(PLAYLIST) as r: lines=r.read().decode('utf-8-sig','replace').splitlines()
    d={}
    for line in lines:
        if not line.startswith('#EXTINF:'): continue
        m=re.search(r'tvg-id="([^"]+)"',line)
        if not m or not m.group(1):continue
        cid=m.group(1)
        name=(re.search(r'tvg-name="([^"]+)"',line) or [None])[0]
        name=name.group(1) if name else line.rsplit(',',1)[-1]
        d.setdefault(cid,set()).add(name)
    return d

def read_source():
    names=defaultdict(set); count=Counter()
    with get(SOURCE) as r, gzip.GzipFile(fileobj=r) as stream:
        for _,node in etree.iterparse(stream,events=('end',),tag=('channel','programme'),huge_tree=True):
            cid=node.get('id') if node.tag=='channel' else node.get('channel')
            if cid:
                if node.tag=='channel':
                    names[cid].update(x.text.strip() for x in node.findall('display-name') if x.text and x.text.strip())
                else:count[cid]+=1
            node.clear()
            parent=node.getparent()
            if parent is not None:
                while node.getprevious() is not None:del parent[0]
    return names,count

def main():
    print('Downloading playlist and IPTV-org metadata...',flush=True)
    playlist=parse_playlist()
    with get(CHANNELS) as r: metadata=json.load(r)
    aliases=defaultdict(set)
    for obj in metadata:
        cid=obj.get('id')
        if not cid:continue
        for val in [obj.get('name'),*(obj.get('alt_names') or [])]:
            if val:aliases[cid].add(val)
    print('Streaming worldwide guide...',flush=True)
    source,counts=read_source()
    # Index only channels with schedules; country bucket prevents expensive global cross product.
    idx=defaultdict(set)
    for sid,names in source.items():
        if not counts[sid]:continue
        c=country(sid)
        if not c:continue
        for n in names|{sid.rsplit('.',1)[0]}:
            key=norm(n)
            if key:idx[(c,key)].add(sid)
    # Prefix-bucket for bounded fuzzy search; candidate only, never auto-approve.
    prefix=defaultdict(set)
    for (c,key),sids in idx.items():
        if len(key)>=4:prefix[(c,key[:4])].update(sids)
    results=[]; summary=Counter()
    for pid,names in playlist.items():
        c=country(pid)
        raw=pid.split('@')[0].rsplit('.',1)[0]
        keys={norm(n) for n in (names|aliases.get(pid,set())|{raw}) if norm(n)}
        exact={pid} if counts[pid] else set()
        matches=set(exact)
        for key in keys:matches.update(idx.get((c,key),set()))
        if not matches and c:
            for key in keys:
                if len(key)>=4:matches.update(prefix.get((c,key[:4]),set()))
        scored=[]
        for sid in matches:
            if not counts[sid]:continue
            snames=source.get(sid,set())|{sid.rsplit('.',1)[0]}
            score=max((SequenceMatcher(None,a,norm(b)).ratio() for a in keys for b in snames if norm(b)),default=0)
            if sid==pid:method='exact_id';score=1.0
            elif score>=0.999:method='normalized_name_or_alias'
            elif score>=0.82:method='fuzzy_name'
            else:continue
            # Never treat regional/quality suffixes as interchangeable by default.
            flags=[]
            if '@' in pid:flags.append('playlist_variant_check')
            if re.search(r'\.[a-z]{2}\d+$',sid,re.I):flags.append('provider_country_suffix_check')
            if any(x in (pid+' '+sid).lower() for x in ['east','west','timeshift','+1','+2']):flags.append('time_shift_region_check')
            scored.append((score,sid,method,';'.join(flags)))
        scored.sort(reverse=True)
        summary['playlist_ids']+=1
        if scored:summary['playlist_ids_with_candidates']+=1
        else:summary['playlist_ids_without_candidates']+=1
        for score,sid,method,flags in scored[:5]:
            results.append({'playlist_id':pid,'playlist_names':' | '.join(sorted(names|aliases.get(pid,set()))),'source_id':sid,'source_names':' | '.join(sorted(source.get(sid,set()))),'programmes':counts[sid],'similarity':f'{score:.3f}','method':method,'flags':flags,'approved':'NO'})
    fields=['playlist_id','playlist_names','source_id','source_names','programmes','similarity','method','flags','approved']
    with (OUT/'all_candidates.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(results)
    with (OUT/'unmatched.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['playlist_id','playlist_names'])
        found={r['playlist_id'] for r in results}
        for pid,names in playlist.items():
            if pid not in found:w.writerow([pid,' | '.join(sorted(names|aliases.get(pid,set())))])
    summary.update({'source_channels':len(source),'source_channels_with_programmes':sum(v>0 for v in counts.values()),'candidate_rows':len(results)})
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))
    print('=== MAXIMUM MATCH DISCOVERY (UNVERIFIED) ===')
    print(json.dumps(summary,indent=2),flush=True)
    print('Reports in',OUT)

if __name__=='__main__':main()
