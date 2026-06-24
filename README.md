# Archiposition RSS

Auto-scrapes [archiposition.com (有方)](https://www.archiposition.com/) for the latest 100 articles and serves them as a standard RSS 2.0 feed, hosted on GitHub Pages. Works with Inoreader, Feedly, NetNewsWire, etc.

## Feed URL

Once deployed:

```
https://ting2465.github.io/archiposition-rss/archiposition.xml
```

## Deploy

### 1. Create an empty GitHub repo

- Open https://github.com/new
- Repository name: `archiposition-rss`
- Visibility: `Public` (required for free GitHub Pages)
- Do NOT check "Add a README file" / "Add .gitignore" / "Choose a license"
- Click `Create repository`

### 2. Push the code

From the project root, in a terminal:

```bash
git init
git add .
git commit -m "init: archiposition RSS"
git branch -M main
git remote add origin https://github.com/ting2465/archiposition-rss.git
git push -u origin main
```

Note: This site uses WordPress with no public RSS. If you are in China and `git push` times out, configure your proxy first:

```powershell
git config --global http.proxy http://127.0.0.1:7897
git config --global https.proxy http://127.0.0.1:7897
```

(Replace 7897 with your actual proxy port.)

If HTTPS still fails, edit the workflow file directly on GitHub instead.

### 3. Enable GitHub Pages

Open `https://github.com/ting2465/archiposition-rss/settings/pages`

- Source: `GitHub Actions`
- Wait 1-2 minutes for the first deploy

### 4. Verify

Open in browser:

```
https://ting2465.github.io/archiposition-rss/archiposition.xml
```

You should see 100 `<item>` entries in RSS XML.

### 5. Add to Inoreader

- Open https://www.inoreader.com/
- Click `+ Add a subscription` -> `Feed URL`
- Paste the feed URL above -> `Add`
- Done.

## Update frequency

GitHub Actions runs every day at UTC 17:00 (Beijing 01:00).

Manual trigger:
- Open repo -> `Actions` tab -> select `Build Archiposition RSS` -> `Run workflow`

## Data source

archiposition.com (有方) has no public RSS feed. This generator:

1. Fetches `https://www.archiposition.com/sitemap.xml` (sitemap index)
2. Reads the last few monthly sub-sitemaps (`sitemap-pt-items-2026-06.xml`, etc.)
3. Sorts all article URLs by `<lastmod>`, takes the latest 100+20
4. Fetches each article page, extracts:
   - title from `<title>` (stripping " - 有方" suffix)
   - cover from the first large `image.archiposition.com` image
   - date from the article byline
5. Emits standard RSS 2.0 XML

## Run locally

```bash
pip install -r requirements.txt   # no external deps currently
python build_rss.py               # generates archiposition.xml
```

## Files

```
.
├── .github/workflows/build.yml   # GitHub Actions: daily cron + manual trigger
├── build_rss.py                  # RSS generator (Python 3.10+, stdlib only)
├── archiposition.xml             # output (auto-maintained by Actions)
├── index.html                    # friendly landing page
├── requirements.txt              # Python deps
└── README.md
```

## License

MIT
