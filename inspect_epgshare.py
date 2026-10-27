
import gzip
import urllib.request
from collections import Counter
from lxml import etree

URL = "https://epgshare01.online/epgshare01/epg_ripper_ALL_SOURCES1.xml.gz"

def main():
    print("Downloading EPGShare01 worldwide guide...", flush=True)

    request = urllib.request.Request(
        URL, headers={"User-Agent": "Mozilla/5.0"}
    )

    channels = {}
    programmes = Counter()

    with urllib.request.urlopen(request, timeout=180) as response:
        with gzip.GzipFile(fileobj=response) as stream:
            context = etree.iterparse(
                stream,
                events=("end",),
                tag=("channel", "programme"),
                huge_tree=True,
            )

            for _, element in context:
                if element.tag == "channel":
                    cid = element.get("id")
                    if cid:
                        channels[cid] = element.findtext("display-name", "")
                else:
                    cid = element.get("channel")
                    if cid:
                        programmes[cid] += 1

                element.clear()
                parent = element.getparent()
                if parent is not None:
                    while element.getprevious() is not None:
                        del parent[0]

    print("\n=== EPGSHARE01 WORLDWIDE REPORT ===")
    print("Total channels:", len(channels))
    print("Channels with schedules:", len(programmes))
    print("Total programme entries:", sum(programmes.values()))

    print("\nSample channel IDs:")
    for cid, name in list(channels.items())[:30]:
        print(f"{cid} | {name} | programmes={programmes[cid]}")

if __name__ == "__main__":
    main()
