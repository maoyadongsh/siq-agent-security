#!/usr/bin/env python3
"""Check repository navigation and immutable evidence without network or services."""
import argparse
import hashlib
import html
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
MAP = 'docs/development/repository-map.json'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def files(root):
    return [p for p in git(root, 'ls-files', '-z').decode().split('\0') if p]


def safe_path(root, name):
    require(bool(name) and not Path(name).is_absolute() and '\\' not in name,
            f'invalid relative path: {name}')
    path = root / name
    require(path.resolve().is_relative_to(root.resolve()), f'path escapes repository: {name}')
    # Check spelling even on case-insensitive filesystems; reject symlink traversal.
    current = root
    for part in Path(name).parts:
        if part in ('.', '..'):
            current = current / part
            continue
        require(current.is_dir() and part in {p.name for p in current.iterdir()},
                f'missing or wrong-case path: {name}')
        current = current / part
        require(not current.is_symlink(), f'symlink navigation is not portable: {name}')
    return path


def without_code(text):
    result, fence = [], None
    for line in text.splitlines():
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            result.append('')
        else:
            result.append('' if fence else line)
    return '\n'.join(result)


def anchors(text):
    text = without_code(text)
    result = set(re.findall(r'\b(?:id|name)=["\']([^"\']+)["\']', text))
    counts = {}
    for heading in re.findall(r'^\s{0,3}#{1,6}\s+(.+?)\s*#*$', text, re.M):
        heading = re.sub(r'!?\[([^]]*)\]\([^)]*\)', r'\1', heading)
        heading = html.unescape(re.sub(r'<[^>]*>', '', heading)).replace('`', '')
        slug = ''.join(c for c in heading.lower()
                       if c in '-_ ' or unicodedata.category(c)[0] in 'LN').replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug if count == 0 else f'{slug}-{count}')
    return result


def link_targets(text):
    """Inline/angle destinations, reference links and HTML href/src, outside fences."""
    text = without_code(text)
    # Retain inline code in labels/headings, remove it for link extraction.
    text = re.sub(r'(`+).*?\1', '', text)
    definitions = {m.group(1).strip().casefold(): m.group(2) or m.group(3)
                   for m in re.finditer(r'^\s{0,3}\[([^]]+)\]:\s*(?:<([^>]+)>|(\S+))', text, re.M)}
    result = list(definitions.values())
    result.extend(html.unescape(x[1]) for x in re.findall(r'\b(?:href|src)=(["\'])(.*?)\1', text))
    for match in re.finditer(r'!?\[([^]\n]+)\](\(|\[([^]\n]*)\])', text):
        if match.group(2).startswith('['):
            key = (match.group(3) or match.group(1)).strip().casefold()
            require(key in definitions, f'undefined reference link: {key}')
            result.append(definitions[key])
            continue
        start = match.end()
        if text[start:start + 1] == '<':
            end = text.find('>', start + 1)
            require(end >= 0, 'unterminated angle link')
            result.append(text[start + 1:end])
            continue
        depth, end = 1, start
        while end < len(text):
            ch = text[end]
            if ch == '\\':
                end += 2
                continue
            if ch == '(':
                depth += 1
            if ch == ')':
                depth -= 1
                if not depth:
                    break
            end += 1
        require(depth == 0, 'unterminated Markdown link')
        target = text[start:end].strip()
        target = re.sub(r'\s+["\'].*["\']$', '', target)
        result.append(re.sub(r'\\([()])', r'\1', target))
    return result


def check_document(root, name):
    path = safe_path(root, name)
    count = 0
    for target in link_targets(path.read_text()):
        parsed = urlsplit(target)
        if parsed.scheme in ('https', 'http', 'mailto'):
            continue
        require(not parsed.scheme and not parsed.netloc, f'unsupported link: {name}: {target}')
        local = unquote(parsed.path)
        require(not local.startswith('/'), f'absolute local link: {name}: {target}')
        destination = path if not local else safe_path(root, (path.parent / local).relative_to(root).as_posix())
        if parsed.fragment and destination.suffix == '.md':
            require(unquote(parsed.fragment) in anchors(destination.read_text()),
                    f'unknown anchor: {name}: {target}')
        count += 1
    return count


def covered(name, prefix):
    return name.startswith(prefix) if prefix.endswith('/') else name == prefix


def validate_map(root, data):
    require(data['schema_version'] == 'siq-repository-map/v1', 'unsupported map schema')
    entries = data['assets']
    ids = [e['id'] for e in entries]
    require(len(ids) == len(set(ids)), 'duplicate asset ID')
    for entry in entries:
        for key in ('paths', 'kind', 'owner_role', 'strategy', 'consumers', 'license', 'validation'):
            require(entry.get(key), f'missing asset field {key}: {entry["id"]}')
    for name in files(root):
        parts = Path(name).parts
        if parts[0] in ('research', 'platforms', 'evaluations'):
            require(not any(part.endswith('-private') or part in ('state', 'secrets') for part in parts)
                    and Path(name).suffix not in ('.seed', '.db', '.sqlite', '.sqlite3')
                    and Path(name).name not in ('.env', 'token'), f'private output in public index: {name}')
        require(any(covered(name, prefix) for e in entries for prefix in e['paths']),
                f'unclassified tracked path: {name}')
    for item in data['changes']:
        require(item['action'] in ('edit', 'add', 'retain', 'defer'), 'invalid migration action')
        require(item.get('reason') and item.get('consumers') and item.get('validation'),
                'incomplete change record')
        if item['action'] != 'add' or (root / item['path']).exists():
            safe_path(root, item['path'])
    return len(entries)


def check_frozen(root, policy, base):
    require(re.fullmatch(r'[0-9a-f]{40}', policy['baseline']), 'full baseline SHA required')
    roots, paths = policy['prefixes'], policy['paths']
    for name in roots + paths:
        require(not name.startswith('/') and '..' not in Path(name).parts, 'unsafe frozen path')
    refs = [policy['baseline']]
    if base:
        git(root, 'rev-parse', '--verify', base + '^{commit}')
        refs.append(base)
        previous = subprocess.run(['git', '-C', str(root), 'show', f'{base}:{MAP}'], capture_output=True)
        if previous.returncode == 0:
            prior = json.loads(previous.stdout)['frozen']
            require(policy['baseline'] == prior['baseline'], 'frozen baseline cannot be replaced')
            require(set(prior['prefixes']) <= set(roots) and set(prior['paths']) <= set(paths),
                    'cannot remove frozen protection from base')
    for ref in set(refs):
        changes = git(root, 'diff', '--name-only', '-z', '--no-renames', '--diff-filter=MDTR',
                      ref, '--', *roots, *paths).decode().split('\0')
        require(not any(changes), f'frozen content changed relative to {ref}: {list(filter(None, changes))[:5]}')
    # Separate cross-reference hash check catches manifest consumers outside the frozen directories.
    claims = json.loads((root / 'docs/research/claims-evidence.json').read_text())['claims']
    for claim in claims:
        path = safe_path(root, claim['evidence'])
        require(hashlib.sha256(path.read_bytes()).hexdigest() == claim['evidence_sha256'],
                f'claim evidence changed: {claim["id"]}')


def check(root, base=None):
    data = json.loads((root / MAP).read_text())
    count = validate_map(root, data)
    check_frozen(root, data['frozen'], base)
    documents = set(data['navigation_files'])
    for pattern in data['navigation_globs']:
        documents.update(p.relative_to(root).as_posix() for p in root.glob(pattern))
    links = sum(check_document(root, name) for name in sorted(documents))
    return {'result': 'passed', 'asset_groups': count, 'documents': len(documents), 'local_links': links}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--base', help='PR base or push-before commit; available in full-history CI checkout')
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.root.resolve(), args.base)))
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'repository check failed: {exc}\n')


if __name__ == '__main__':
    main()
