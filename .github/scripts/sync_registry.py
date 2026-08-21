#!/usr/bin/env python3
"""Sync the registry `plugins` file from the plugin repos' latest releases.

For every entry in `plugins`:
  1. derive the source repo from the first platform asset URL
     (https://github.com/{owner}/{repo}/releases/download/{tag}/{file});
  2. query the latest non-draft/non-prerelease GitHub release of that repo;
  3. rebuild the platform map (url / sha256 / size) from the release assets,
     reading each `.zip`'s sibling `.sha256` asset for the digest;
  4. compare with the entry's current version (semver):
       - release version == current  -> refresh platforms + updatedAt if changed
       - release version >  current  -> update the entry to the new version
       - release version <  current  -> leave untouched
  5. retain ONLY the single latest version for each plugin (deduplicate any
     historical versions).

Writes `plugins` back in the canonical compact format (byte-identical when
nothing changed). Requires `gh` (GH_TOKEN) and `curl`. Exit code is always 0;
the caller decides whether anything changed via `git diff`.
"""

import json
import os
import re
import subprocess
import sys
from datetime import date

REGISTRY_FILE = "plugins"
PLATFORM_KEYS = [
    "windows-x64",
    "windows-arm64",
    "linux-x64",
    "linux-arm64",
    "macos-x64",
    "macos-arm64",
]
# Platform keys render as `        "windows-x64":` (8-space indent + key +
# colon). Longest key is 13 chars -> 8 + 15 + 1 = 24; existing entries align
# the `{` at column 23 (8 + 14 for windows-x64, +1 space). Pad the label part
# to 22 so the `{` lands on column 23 for the common keys; longer keys
# (windows-arm64) simply get no padding (still valid JSON).
ALIGN = 22
ASSET_URL_RE = re.compile(
    r"https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/(.+)"
)


def gh(args):
    """Run `gh` and return stdout; raises on non-zero exit."""
    proc = subprocess.run(
        ["gh"] + args, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def fetch_sha256(url):
    """Download a `.sha256` asset and return the hex digest (or None)."""
    try:
        proc = subprocess.run(
            ["curl", "-sL", "--fail", url],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.split()[0]
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def parse_version(v):
    """Parse a semver-ish string into a comparable tuple."""
    core = v.split("-")[0].lstrip("v").split(".")
    parts = []
    for p in core:
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def render(plugins):
    """Serialize in the canonical compact format (matches existing file)."""
    out = ["{", '  "plugins": [']
    for idx, e in enumerate(plugins):
        out.append("    {")
        out.append(f'      "name": "{e["name"]}",')
        out.append(f'      "version": "{e["version"]}",')
        out.append(f'      "description": "{e["description"]}",')
        out.append(f'      "author": "{e["author"]}",')
        out.append(f'      "icon": "{e["icon"]}",')
        out.append(
            '      "categories": ['
            + ", ".join(json.dumps(c) for c in e["categories"])
            + "],"
        )
        out.append(f'      "updatedAt": "{e["updatedAt"]}",')
        out.append('      "platforms": {')
        present = [p for p in PLATFORM_KEYS if p in e["platforms"]]
        max_url_len = max(len(e["platforms"][p]["url"]) for p in present)
        for p in present:
            a = e["platforms"][p]
            label = f'        "{p}":'
            # Align the `"sha256"` column to the longest URL in this entry
            # (existing file convention): `{ "url": "<url>",` + padding.
            pad = " " * (max_url_len - len(a["url"]) + 1)
            comma = "," if p is not present[-1] else ""
            out.append(
                f'{label.ljust(ALIGN)} {{ "url": "{a["url"]}",{pad}'
                f'"sha256": "{a["sha256"]}", "size": {a["size"]} }}{comma}'
            )
        out.append("      }")
        sep = "," if idx < len(plugins) - 1 else ""
        out.append("    }" + sep)
    out.append("  ]")
    out.append("}")
    return "\n".join(out) + "\n"


def collect_platforms(repo, release):
    """Build {platform: {url, sha256, size}} from a release's assets."""
    platforms = {}
    for asset in release["assets"]:
        name = asset["name"]
        if not name.endswith(".zip"):
            continue
        platform = next((p for p in PLATFORM_KEYS if p in name), None)
        if platform is None:
            print(f"  skip asset with unknown platform: {name}", flush=True)
            continue
        sha256 = fetch_sha256(asset["browser_download_url"] + ".sha256")
        if sha256 is None:
            print(f"  skip {name}: could not fetch .sha256 digest", flush=True)
            continue
        platforms[platform] = {
            "url": asset["browser_download_url"],
            "sha256": sha256,
            "size": asset["size"],
        }
    return platforms


def latest_release(repo):
    """Latest non-draft/non-prerelease release of {owner}/{repo}, or None."""
    releases = json.loads(
        gh(["api", f"repos/{repo}/releases?per_page=100"])
    )
    for r in releases:
        if not r["draft"] and not r["prerelease"]:
            return r
    return None


def main():
    with open(REGISTRY_FILE, encoding="utf-8") as f:
        data = json.load(f)

    # Group entries by name, preserving file order.
    by_name = {}
    for e in data["plugins"]:
        by_name.setdefault(e["name"], []).append(e)

    today = date.today().isoformat()
    changed = False

    for name, entries in by_name.items():
        if not entries:
            continue
        # Sort descending by version in case input file had unordered duplicates
        entries.sort(key=lambda e: parse_version(e["version"]), reverse=True)
        current = entries[0]
        had_duplicates = len(entries) > 1

        sample = next(iter(current["platforms"].values()))
        match = ASSET_URL_RE.match(sample["url"])
        if match is None:
            print(f"[{name}] no GitHub release asset URL, skipping", flush=True)
            if had_duplicates:
                by_name[name] = [current]
                changed = True
            continue
        owner, repo, _tag = match.group(1), match.group(2), match.group(3)
        repo_full = f"{owner}/{repo}"
        print(f"[{name}] source repo: {repo_full}", flush=True)

        try:
            release = latest_release(repo_full)
        except RuntimeError as err:
            print(f"[{name}] SKIP (release query failed): {err}", flush=True)
            if had_duplicates:
                by_name[name] = [current]
                changed = True
            continue
        if release is None:
            print(f"[{name}] no non-draft/non-prerelease release, skipping", flush=True)
            if had_duplicates:
                by_name[name] = [current]
                changed = True
            continue

        release_version = release["tag_name"].lstrip("v")
        platforms = collect_platforms(repo_full, release)
        if not platforms:
            print(f"[{name}] no usable zip assets in release, skipping", flush=True)
            if had_duplicates:
                by_name[name] = [current]
                changed = True
            continue

        current_version = current["version"]
        release_v = parse_version(release_version)
        current_v = parse_version(current_version)

        if release_v == current_v:
            by_name[name] = [current]
            if had_duplicates:
                changed = True
                print(f"[{name}] pruned duplicate versions, keeping only latest v{release_version}", flush=True)
            if current["platforms"] == platforms:
                if not had_duplicates:
                    print(
                        f"[{name}] v{release_version} already up to date, no change",
                        flush=True,
                    )
                continue
            current["platforms"] = platforms
            current["updatedAt"] = today
            changed = True
            print(f"[{name}] v{release_version} refreshed (asset digest/size)", flush=True)
        elif release_v > current_v:
            new_entry = {
                "name": name,
                "version": release_version,
                "description": current["description"],
                "author": current["author"],
                "icon": current["icon"],
                "categories": list(current["categories"]),
                "updatedAt": today,
                "platforms": platforms,
            }
            by_name[name] = [new_entry]
            changed = True
            print(f"[{name}] updated to latest version v{release_version}", flush=True)
        else:
            by_name[name] = [current]
            if had_duplicates:
                changed = True
                print(f"[{name}] pruned duplicate versions, keeping only latest v{current_version}", flush=True)
            print(
                f"[{name}] release v{release_version} < current v{current_version}, "
                "leaving untouched",
                flush=True,
            )
    if not changed:
        print("No updates needed.", flush=True)
        return

    data["plugins"] = []
    for entries in by_name.values():
        data["plugins"].extend(entries)

    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        f.write(render(data["plugins"]))

    print("Registry updated.", flush=True)


if __name__ == "__main__":
    main()
