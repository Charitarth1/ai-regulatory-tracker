#!/usr/bin/env bash
# Build feed.json and upload it to the R2 bucket that serves your feed.
# Outbound only: the VPS pushes one file; nothing connects back to it.
# Needs: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET (from the env file).
set -euo pipefail

STATE="${STATE_DIRECTORY:-/var/lib/regtracker}"
HERE="$(cd "$(dirname "$0")" && pwd)"
FEED="$STATE/feed.json"

python3 -I "$HERE/tracker.py" --out "$FEED"

# Sanity checks before anything goes public.
python3 -I - "$FEED" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["version"] == 1 and isinstance(d["items"], list) and len(d["items"]) > 0
assert all(i["url"].startswith("https://") for i in d["items"])
EOF

if [[ "${1:-}" == "--dry-run" ]]; then
  echo "dry run: not uploading $FEED"
  exit 0
fi

: "${R2_ACCOUNT_ID:?} ${R2_ACCESS_KEY_ID:?} ${R2_SECRET_ACCESS_KEY:?} ${R2_BUCKET:?}"

curl --fail --silent --show-error --max-time 60 \
  --aws-sigv4 "aws:amz:auto:s3" \
  --user "${R2_ACCESS_KEY_ID}:${R2_SECRET_ACCESS_KEY}" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "Cache-Control: public, max-age=1800" \
  -H "x-amz-content-sha256: UNSIGNED-PAYLOAD" \
  --upload-file "$FEED" \
  "https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com/${R2_BUCKET}/feed.json"

echo "uploaded feed.json to bucket ${R2_BUCKET}"
