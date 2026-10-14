# Repository release discipline

For every completed code change in this repository:

1. Keep credentials, customer exports, downloaded emails, reports, databases, build output, and release binaries out of Git.
2. Run the relevant automated tests and the GUI smoke test before committing.
3. Review the exact staged file list and staged diff.
4. Create a Git commit that describes the verified change.
5. Push the current branch to `origin` after the commit succeeds.
6. For a numbered release, update the version, create an annotated `vX.Y.Z` tag, and push that tag to `origin`.

Do not reuse or move an existing version tag. If a released version changes, increment the version number first.
