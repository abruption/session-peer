# Download metrics

The README's PyPI monthly-download badge is supplied by
[Shields.io](https://shields.io/badges/py-pi-downloads), using the
[PyPI Stats recent-download API](https://pypistats.org/api/). Click the badge to
open [session-peer's statistics](https://pypistats.org/packages/session-peer).
It represents the provider's recent-month aggregate, not a calendar-month total
or a live counter. The badge requests a one-day HTTP cache; provider and GitHub
image caches can delay visible updates.

## Interpretation

- Downloads are not unique installations, active users or successful deliveries.
  CI and repeated downloads can contribute, while client caches reduce counts.
- PyPI Stats excludes known mirrors for this API; other measurement limitations
  still apply. See the [PyPA guide](https://packaging.python.org/en/latest/guides/analyzing-pypi-package-downloads/).
- These counts cover the `session-peer` PyPI package, not legacy `cc-peer`, GitHub
  clones, raw-script installation or all package sources.
- An unavailable, rate-limited or unknown badge is not zero downloads. Follow the
  source link for context; the README does not substitute a hardcoded count.

The badge is a remote image like the existing README badges. It introduces no
CLI telemetry or repository-owned collector, database or scheduled workflow.
The version remains unchanged; documentation updates do not require a release.

## Separate landing implementation

The ontology session owns the landing page. Its scoped task is to show separately
labeled recent 7-day and recent 30-day PyPI download counts, keeping provider states
clear. Any API-based implementation should cache each endpoint at most once per
day following PyPI Stats guidance, report its observation time, and retain
unknown/stale states instead of showing failed requests as zero. Existing site
analytics stay unchanged; no CLI or visitor-event telemetry is added by this work.

## GitHub follow-up

[GitHub release APIs](https://docs.github.com/en/rest/releases/releases) expose
cumulative `download_count` for uploaded release assets. Weekly/monthly values
require dated snapshots and differences by stable asset ID. Missing baselines,
removed or replaced assets and counter decreases need explicit unknown or
continuity states; historical periods cannot be recovered from one cumulative
reading. Keep GitHub asset downloads separate from PyPI and do not label them
as clone or raw standalone-installer traffic. Snapshot automation is not
implemented in this first README change.
