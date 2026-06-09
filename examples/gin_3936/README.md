# Fixture: gin#3936 (illustrative)

Drop-in offline fixture that exercises the full agent pipeline without
hitting the GitHub API. The issue body describes a small, plausible binding
bug; the agent will clone `gin-gonic/gin`, index it, and try to produce a
minimal patch.

```bash
python -m go_contributor run --fixture examples/gin_3936
```

The `issue.json` schema matches what `tools/github_api.fetch_issue` returns,
so swapping a real issue for this fixture is just `--repo / --issue` flags.
