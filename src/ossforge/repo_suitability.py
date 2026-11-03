"""Compact source evidence for native code work, never semantic bug proof.

Lists and learning collections may be useful documentation targets. Source and
native test feasibility need explicit evidence for a code-bug session.
"""
from __future__ import annotations

import re
from . import gh

MANIFESTS = {'pyproject.toml', 'setup.py', 'setup.cfg', 'Cargo.toml', 'go.mod',
             'package.json', 'CMakeLists.txt', 'Makefile', 'pom.xml', 'build.gradle'}
SOURCE_DIRS = {'src', 'lib', 'pkg', 'cmd', 'include', 'source'}
TESTS = {'tests', 'test', 'tox.ini', 'noxfile.py', 'pytest.ini'}
COLLECTION = re.compile(r'\b(?:curated|awesome|list of|collection of|free (?:programming )?books|learning resources|project.based learning|system design primer)\b', re.I)


def assess(repo: str, revision: str, policy: dict) -> dict:
    listing = gh.api(f'repos/{repo}/contents', ref=revision, fresh=True)
    if (not isinstance(listing, list) or len(listing) >= 1000 or
            any(not isinstance(x, dict) or not isinstance(x.get('name'), str) for x in listing)):
        raise gh.GhError('source suitability listing incomplete; inspect before code investigation')
    files = {x['name'] for x in listing if x.get('type') == 'file'}
    dirs = {x['name'] for x in listing if x.get('type') == 'dir'}
    manifests = sorted(files & MANIFESTS)
    source = sorted(dirs & SOURCE_DIRS)
    tests = sorted((files | dirs) & TESTS)
    readmes = [d for d in policy.get('docs', []) if d.get('path', '').lower().startswith('readme')]
    collection = any(COLLECTION.search(d.get('text', '')[:8000]) for d in readmes)
    # Missing a conventional layout is uncertainty, not proof that no code exists.
    status = ('collection_review_needed' if collection and not (manifests and (source or tests)) else
              'native_candidate' if manifests and (source or tests) else 'native_feasibility_review_needed')
    return {'status': status, 'revision': revision, 'manifests': manifests,
            'source_directories': source, 'test_entries': tests,
            'collection_signal': collection,
            'sources': [{'path': x.get('path', x['name']), 'url': x.get('html_url')}
                        for x in listing if x['name'] in set(manifests + source + tests)],
            'reason': ('collection/documentation evidence without conventional native-code/test layout; inspect or defer for a code-bug session'
                       if status == 'collection_review_needed' else
                       'inspect native reproduction instructions; layout signals are not permission, runnable-test proof or a confirmed bug')}
