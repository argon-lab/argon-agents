# SDK release operations

The Python package is released from this repository, independently of the
engine's npm/Homebrew distribution. A successful build or credential probe
does not mean a package is available on PyPI.

## One-time trusted publisher configuration

The owner of the existing `argon-agents` PyPI project must add the following
GitHub Trusted Publisher under the project's Publishing settings:

| Field | Value |
| --- | --- |
| Owner | `argon-lab` |
| Repository | `argon-agents` |
| Workflow filename | `publish.yml` |
| Environment | `pypi` |

Use https://pypi.org/manage/project/argon-agents/settings/publishing/ . The
GitHub job uses the `pypi` environment and requests an OIDC identity; no API
token should be committed to the repository. An `invalid-publisher` response
means the PyPI mapping does not match these fields. An assigned project-scoped
upload credential can also be supplied as an environment secret, but it is
not needed with Trusted Publishing. Never put credentials in logs or issues.

## Release procedure

1. Run integration CI against the supported engine release, with
   `ARGON_REQUIRE_STACK=1` so a missing MongoDB/API stack fails the run.
2. Set the package version, build and check wheel/sdist, and merge the reviewed
   source before creating the stable `vX.Y.Z` tag. Never move an existing tag
   or replace an uploaded PyPI version.
3. Dispatch `Publish Python package` on `main`, using the existing tag and
   `probe_only=false`. The workflow checks that the tag matches the package
   and is an ancestor of `main`, then records its exact commit. The publication
   job checks out that commit, revalidates the tag, rebuilds and checks the
   distributions before uploading to PyPI. It does not use Actions artifact
   storage to transfer distributions between jobs.
4. Require the registry verification step to pass. It waits for the expected
   non-yanked release, downloads a wheel through pip into a fresh virtual
   environment, checks the installed version and imports the client there.
5. Update README/website/core install commands only after the registry check.
   Until then, keep the published GitHub wheel/tag as the explicit fallback.

If an upload succeeded but the final network verification failed, run
`python scripts/verify_publication.py --version X.Y.Z` first. Do not create a
new package version merely to retry a verification step. `probe_only=true`
does not upload and deliberately skips registry verification.
