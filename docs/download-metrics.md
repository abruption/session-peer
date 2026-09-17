# Download metrics

The README's PyPI monthly-download badge is served directly by
[Pepy](https://pepy.tech/pepy-api). Click it to open
[session-peer's statistics](https://pepy.tech/projects/session-peer).
The public monthly badge counts the last 30 days, not a calendar month or a
live counter. Pepy's API documentation states that public badge endpoints need
no API key, have no rate limit and are cached for 12 hours. GitHub image caching
can further delay visible updates; the badge is still an external dependency.

Monthly: `https://api.pepy.tech/badge/session-peer/month`.
Weekly: `https://api.pepy.tech/badge/session-peer/week` (last 7 days).

## Interpretation

- Downloads are not unique installations, active users or successful deliveries.
  CI and repeated downloads can contribute, while client caches reduce counts.
- These are Pepy aggregates. The public badge documentation does not establish
  the same mirror/CI filtering as PyPI Stats; do not mix the two providers or
  claim excluded CI traffic. See the [PyPA guide](https://packaging.python.org/en/latest/guides/analyzing-pypi-package-downloads/)
  for download measurement limitations.
- These counts cover the `session-peer` PyPI package, not legacy `cc-peer`, GitHub
  clones, raw-script installation or all package sources.
- An unavailable, rate-limited or unknown badge is not zero downloads. Follow the
  source link for context; the README does not substitute a hardcoded count.

The badge is a remote image like the existing README badges. It introduces no
CLI telemetry or repository-owned collector, database or scheduled workflow.
The version remains unchanged; documentation updates do not require a release.

## Separate landing implementation

The ontology session owns the landing page. Use the same Pepy public weekly and
monthly badges for its separately labeled recent 7-day and recent 30-day PyPI
metrics, keeping source and provider-error states clear. This avoids a JSON API
key or a separate collector. Do not expose a Pepy JSON API key in public code;
JSON API access has authentication, plan and rate-limit conditions that differ
from the public badges. Existing site analytics stay unchanged; no CLI or
visitor-event telemetry is added by this work.

## Provider change validation (2026-09-18)

The original Shields.io badge used PyPI Stats. Direct PyPI Stats returned HTTP429
and the original badge previously displayed an upstream-rate-limit error; an
extra image-cache parameter does not remove the upstream dependency.
Using curl, both Pepy public endpoints returned HTTP200 and SVG numeric badges
for session-peer (rounded labels `2k` monthly and `1k` weekly at observation time).
These observed values are not hardcoded into the README and do not establish
unique users, exact integer counts or long-term service availability. Initial
Python urllib requests returned403, so curl results must not be generalized to
every client. Browser and GitHub image-proxy reachability remain distinct checks.

## GitHub follow-up

[GitHub release APIs](https://docs.github.com/en/rest/releases/releases) expose
cumulative `download_count` for uploaded release assets. Weekly/monthly values
require dated snapshots and differences by stable asset ID. Missing baselines,
removed or replaced assets and counter decreases need explicit unknown or
continuity states; historical periods cannot be recovered from one cumulative
reading. Keep GitHub asset downloads separate from PyPI and do not label them
as clone or raw standalone-installer traffic. Snapshot automation is not
implemented in this first README change.
