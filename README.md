# mpe-plugin-registry

Static plugin marketplace registry for MPE — a `plugins` JSON file served by
GitHub Pages that implements the host's marketplace contract
([`docs/plugin-marketplace.md`](https://github.com/multi-protocol-flow/multi-protocol-flow-executor/blob/main/docs/plugin-marketplace.md)).

## How it works

The host's `mpe plugin install` calls `GET {base}/plugins` and parses
`{"plugins": [...]}`. GitHub Pages maps the repository-root `plugins` file to
that exact URL path:

```
https://multi-protocol-flow.github.io/mpe-plugin-registry/plugins
```

Each plugin entry's `platforms.<os-arch>.url` points at the corresponding
release asset (zip) in the plugin's own repository, with its sha256 digest
(from the release's `.sha256` file) for host-side verification.

## Install a plugin

```bash
# effective plugins directory: MPE_PLUGIN_DIR > config.toml [storage].plugins_dir
# > data dir plugins > ./plugins (see `mpe plugin dir`)
mpe plugin install redis --registry https://multi-protocol-flow.github.io/mpe-plugin-registry

# or via env var
export MPE_PLUGIN_REGISTRY=https://multi-protocol-flow.github.io/mpe-plugin-registry
mpe plugin install redis

# verify
mpe plugin list
mpe run-node '{"type":"redis:connect","host":"127.0.0.1","port":6379}'
```

## Add a new plugin or version

1. Append/update the entry in `plugins` (each plugin maintains only its
   latest release version; new releases replace the existing entry).
2. `platforms` keys are `<os>-<arch>`: `windows-x64 | windows-arm64 |
   linux-x64 | linux-arm64 | macos-x64 | macos-arm64`.
3. `url` must be an absolute zip URL (e.g. a GitHub release asset), `sha256`
   the hex digest of the zip bytes (required — the host enforces it), `size`
   the byte size (display only).
4. Commit and push; GitHub Pages publishes the updated file automatically.
