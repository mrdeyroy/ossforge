"""Optional maintainer-controlled proposal admission, independent of operator approval.

A public repository is readable, but strict mode requires an explicit repository
manifest or issue label before proposing a draft. This never overrides policy.
"""
from __future__ import annotations

import base64
from pathlib import PurePosixPath

import yaml

from . import gh

class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise Denied("duplicate or non-string manifest key")
        result[key] = loader.construct_object(value_node)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


PATH = ".github/ossforge.yml"
PATHS = (".github/ossforge.yml", ".github/ossforge.yaml")
LABEL = "ossforge-approved"


class Denied(ValueError):
    pass


def _read(repo: str) -> dict | None:
    data = None
    source_path = PATH
    for path in PATHS:
        try:
            data = gh.api(f"repos/{repo}/contents/{path}", fresh=True)
            source_path = path
            break
        except gh.GhError as e:
            if e.status == 404:
                continue
            raise Denied(f"cannot verify maintainer manifest: {e}") from e
    if data is None:
        return None
    try:
        if data.get("encoding") != "base64":
            raise ValueError("unsupported content encoding")
        text = base64.b64decode(data["content"], validate=False).decode("utf-8")
        value = yaml.load(text, Loader=_UniqueLoader)
        return parse(value, source=source_path)
    except (ValueError, KeyError, AttributeError, UnicodeError, yaml.YAMLError) as e:
        raise Denied(f"invalid maintainer manifest: {e}") from e


def parse(value: object, source: str = PATH) -> dict:
    if not isinstance(value, dict) or set(value) - {"version", "enabled", "max_files", "max_lines", "allowed_dirs"}:
        raise Denied("manifest must be a mapping with recognized fields only")
    if type(value.get("version")) is not int or value["version"] != 1 or value.get("enabled") is not True:
        raise Denied("manifest must declare version: 1 and enabled: true")
    for key, default in (("max_files", 5), ("max_lines", 250)):
        n = value.get(key, default)
        if type(n) is not int or not 1 <= n <= 10000:
            raise Denied(f"{key} must be a positive bounded integer")
    dirs = value.get("allowed_dirs", [])
    if not isinstance(dirs, list) or not dirs:
        raise Denied("allowed_dirs must be a nonempty list of relative directory prefixes")
    for d in dirs:
        if not isinstance(d, str) or not canonical(d.rstrip('/')) or any(c in d for c in '*?[]'):
            raise Denied("allowed_dirs must contain literal canonical relative directories")
    return {"source": source, "max_files": value.get("max_files", 5), "max_lines": value.get("max_lines", 250),
            "allowed_dirs": [d.rstrip('/') for d in dirs]}


def canonical(path: str) -> bool:
    return bool(path and not path.startswith('/') and '\\' not in path and '\x00' not in path
                and all(p not in ('', '.', '..') for p in path.split('/')))


def inspect(repo: str, issue: int = 0) -> dict:
    # An existing disabled/malformed manifest is a denial, never bypassed by an issue label.
    manifest = _read(repo)
    if manifest is not None:
        return manifest
    if not issue:
        raise Denied("no maintainer manifest; provide an explicitly approved issue")
    try:
        item = gh.api(f"repos/{repo}/issues/{issue}", fresh=True)
    except gh.GhError as e:
        raise Denied(f"cannot verify issue approval: {e}") from e
    labels = {x.get('name', '') if isinstance(x, dict) else x for x in item.get('labels', [])}
    if item.get('state') != 'open' or 'pull_request' in item or LABEL not in labels:
        raise Denied("issue must be open, not a PR, and carry the ossforge-approved maintainer label")
    return {"source": f"issue#{issue}:{LABEL}", "max_files": 5, "max_lines": 250, "allowed_dirs": []}


def check(repo: str, issue: int, paths: list[str], numstat: str) -> dict:
    permit = inspect(repo, issue)
    if not paths or len(paths) > permit['max_files']:
        raise Denied("change exceeds maintainer file budget or is empty")
    for path in paths:
        if not canonical(path) or (PurePosixPath(path).name in ('ossforge.yml', 'ossforge.yaml') and path.startswith('.github/')):
            raise Denied("noncanonical or protected admission path")
        if permit['allowed_dirs'] and not any(path.startswith(d + '/') for d in permit['allowed_dirs']):
            raise Denied(f"path outside maintainer scope: {path}")
    lines = 0
    rows = numstat.splitlines()
    if len(rows) != len(paths):
        raise Denied("cannot establish changed-line scope")
    for row in rows:
        parts = row.split('\t', 2)
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit() or parts[2] not in paths:
            raise Denied("binary/renamed/ambiguous scope cannot be admitted")
        lines += int(parts[0]) + int(parts[1])
    if lines > permit['max_lines']:
        raise Denied("change exceeds maintainer line budget")
    return {**permit, "files": len(paths), "changed_lines": lines, "draft_only": True}
