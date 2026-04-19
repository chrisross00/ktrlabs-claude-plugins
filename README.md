# ktrlabs-claude-plugins

A Claude Code plugin marketplace authored by Chris Ross (ktrlabs).

## Install

Add the marketplace, then install any plugin by name:

```
/plugin marketplace add https://github.com/<your-org-or-handle>/ktrlabs-claude-plugins
/plugin install claude-code-recorder@ktrlabs-claude-plugins
```

## Plugins

| Name | Description |
|---|---|
| [claude-code-recorder](./plugins/claude-code-recorder/) | Record a narrated screen demo; get transcript + relevant screenshots dropped back into Claude Code as a prompt. |

## Repo layout

```
.claude-plugin/
  marketplace.json          # lists the plugins
plugins/
  claude-code-recorder/     # individual plugin
    .claude-plugin/
      plugin.json           # plugin manifest
    bin/                    # Python implementation
    commands/               # slash command definitions
    hooks/                  # lifecycle hooks
    tests/                  # unit + e2e tests
    pyproject.toml
    README.md               # plugin-specific docs
.github/workflows/ci.yml    # CI for all plugins
```

New plugins go under `plugins/<name>/` and are registered in `.claude-plugin/marketplace.json`.
