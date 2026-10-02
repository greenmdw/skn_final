# Private review seed bundle

`setup_all.py` requires this directory to contain the finalized, authorized review bundle:

- `bundle_manifest.json`
- `documents.json`
- `rules.json`
- `canonical_results.json`
- `consolidated_observation_drafts.json`

These files contain real review text and derived analysis. They are intentionally excluded
from Git. Build the bundle in the curated workspace with:

```bash
PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run python db/build_review_seed_bundle.py
```

Copy the complete directory through the team's approved private data channel before running
database setup or the required database tests. The build writes counts and SHA-256 hashes to
`bundle_manifest.json`, excludes the two quarantined source identities, and checks the finalized
document/rule/observation totals. Do not manually edit the generated files.

The Docker image already copies `data/`; therefore provide this directory in the Docker build
context before building. The resulting image contains the private review bundle and must be
stored and distributed as a private artifact. For environments where images must not contain
review text, securely mount the complete directory at `/app/data/review_seed` at runtime instead.
A missing or changed bundle causes setup to fail.
