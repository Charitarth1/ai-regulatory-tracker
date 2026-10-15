# Security policy

Please report vulnerabilities privately through GitHub's **Report a vulnerability** button (Security tab), not in a public issue. I'll acknowledge within a week.

Design notes that matter for security:

- The tracker treats every feed as untrusted. Only `https://` links are kept, titles are stripped of markup and length-capped, and feeds that declare XML entities are refused.
- The consuming page must render items as text (for example with `textContent`), never as HTML.
- The upload credential should be scoped to the one bucket that serves the feed.
