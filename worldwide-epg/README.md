# Worldwide EPG merger

Downloads and merges all 77 currently listed country XMLTV guides from https://iptv-epg.org/guides into a single compressed XMLTV guide daily using GitHub Actions and GitHub Pages.

## Installation

1. Create a **public** GitHub repository named `worldwide-epg`.
2. Upload `merge.py`, `requirements.txt`, and `.github/workflows/publish.yml` to the repository, preserving the `.github/workflows/` directory. GitHub's web interface can create these files using **Add file → Create new file**, with the full relative path.
3. In **Settings → Pages → Build and deployment**, choose **Source: GitHub Actions**.
4. In **Actions → Update Worldwide EPG → Run workflow**, start the first build. Allow time for downloads, merging, and publishing.
5. Your guide URL will be `https://YOUR-USERNAME.github.io/worldwide-epg/epg.xml.gz`. Use it as the EPG URL in your player. Your playlist remains `https://iptv-org.github.io/iptv/index.country.m3u`.

## Notes

- The output is **gzip-compressed XMLTV**, not plain XML. Most IPTV apps support `.xml.gz`; verify support in yours.
- The script deduplicates channels by XMLTV ID and programmes by `(channel, start, stop)`. It retains the first duplicate. This is a merge, **not** an ID-mapping solution: not every playlist channel will have a matching guide ID.
- If fewer than 60 country feeds are available, the build fails instead of publishing a severely incomplete guide.
- GitHub Pages and Actions have size, time, and usage limits. A large guide may exceed them. The first build may take a long time. Schedules can be delayed.
- Data source: https://iptv-epg.org/guides. Check the provider's terms and redistribution permissions before publicly republishing guide data.
- For failure diagnostics, open **Actions → Update Worldwide EPG → failed run → publish**.
