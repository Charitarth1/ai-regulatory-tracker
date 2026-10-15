# AI regulatory tracker

A small, unattended job that collects AI-policy updates from official sources once a day and publishes them as one JSON file. It powers the live tracker on [safeaiguy.com](https://safeaiguy.com/#tracker).

**Sources (9):** European Commission (digital), European Data Protection Board, UK AI Security Institute, UK Government, NIST, CISA, Innovation, Science and Economic Development Canada, OpenAI, Google DeepMind.

## How it works

```
VPS (systemd timer, daily)                        object storage            your website
tracker.py --> feed.json --> publish.sh --PUT-->  bucket (one file)  <--GET--  page renders items as text
```

- **Filtering:** government sources keep items that mention AI. "AI" is matched case-sensitively, so "said" and "aid" don't count. Lab blogs keep safety, policy and risk posts and drop product marketing. Media advisories ("Minister to announce...") are dropped. Each source is capped.
- **Merging:** each run merges with the previous feed, so items survive after a source rotates them out. Items older than 120 days are pruned.
- **Failure handling:** a broken source is logged and skipped. If every source fails, the previous feed is kept.

`examples/feed.sample.json` shows the output format.

## Security design

The job reads untrusted content from the internet, so it gets nothing else:

- **Outbound only.** The host pushes one file. Nothing connects in, and the website never talks to the host.
- **One narrow credential.** The upload key is scoped to a single bucket, so a compromised host can't touch the website or anything else in the cloud account.
- **Throwaway user.** systemd runs each job as a dynamic user with no home directory access, a read-only system, no capabilities and IPv4/IPv6 only.
- **Untrusted output.** Only `https://` links are kept, markup is stripped, lengths are capped, feeds that declare XML entities are refused, and responses over 15 MB are rejected. The consuming page should render items with `textContent` and restrict `connect-src` to the feed's host.
- **No secrets in the tracker.** `tracker.py` never sees a credential. Only `publish.sh` does, through systemd's `EnvironmentFile`.

## Run it

Requirements: Python 3.9+ (stdlib only) and curl 7.75+ (for `--aws-sigv4`).

```bash
python3 -m unittest discover -s . -v                  # tests, no network
STATE_DIRECTORY=/tmp ./publish.sh --dry-run           # real fetch, no upload
```

### Deploy to a Linux host with an S3-compatible bucket (written for Cloudflare R2)

```bash
sudo install -d -m 755 /opt/regtracker
sudo install -m 755 tracker.py publish.sh /opt/regtracker/
sudo install -m 644 systemd/regtracker.service systemd/regtracker.timer /etc/systemd/system/
sudo install -m 600 /dev/null /etc/regtracker.env     # then add the four lines below
sudo systemctl daemon-reload
sudo systemctl start regtracker && journalctl -u regtracker -n 25
sudo systemctl enable --now regtracker.timer
```

`/etc/regtracker.env`:
```
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=...
```

Serve the bucket on its own subdomain, and allow GET only from your site's origin in the bucket's CORS policy.

## Adding a source

Add an entry to `SOURCES` in `tracker.py` with a filter: `"ai"` keeps items that mention AI, `"lab"` keeps safety and policy posts, and `None` keeps everything. Add a test if the source needs new filtering rules.

## Limits

- Keyword filtering misses AI items that never use AI vocabulary, and keeps a few that only mention it in passing.
- Some official sites block data-centre IP addresses. Check the per-source counts in the job log.
- Source coverage is my choice and is not comprehensive. It is weighted to the jurisdictions I work in.

## License

MIT. See [LICENSE](LICENSE).

---

Built by [Charitarth Bharti](https://safeaiguy.com/), who works on AI governance and agentic AI risk.
