"""Static documentation and query-matching evidence audit."""
import argparse
import ast
import fnmatch
import json
import re
from pathlib import Path

__version__ = "0.1.0"
SEARCH = ('full text search', 'fuzzy search', 'semantic search', 'instant search', 'search functionality', 'search feature', 'search support', 'supports searching', 'supports search', 'search results', 'search across', 'search within', 'search through', 'search for', 'search by', 'can search', 'searchable', 'searches', 'searching')
NOSEARCH = ('no search functionality', 'no search feature', 'does not support search', 'does not search', 'not searchable', 'search not supported', 'no full text search', 'without searching', 'without search', 'no search')
QUERY_NAMES = {'query', 'search_query', 'search_term', 'term', 'keyword', 'keywords', 'q', 'needle'}


def pattern(phrases):
    return re.compile(r'\b(?:' + '|'.join(re.escape(p) for p in sorted(phrases, key=len, reverse=True)) + r')\b')


def claims(text):
    lines, fence = [], None
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            lines.append('')
        elif fence is None:
            lines.append(line)
    positive = negative = False
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        normalized = ' '.join(paragraph.lower().replace("n't", ' not').replace('-', ' ').split())
        negative |= bool(pattern(NOSEARCH).search(normalized))
        positive |= bool(pattern(SEARCH).search(pattern(NOSEARCH).sub(' ', normalized)))
    return positive, negative


def evidence(source):
    tree = ast.parse(source)
    aliases = set()
    direct_regex = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update(a.asname or a.name.split('.')[0] for a in node.names if a.name.split('.')[0] == 're')
        elif isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] == 're':
            aliases.update(a.asname or a.name for a in node.names)
            direct_regex.update(a.asname or a.name for a in node.names if a.name in {'search', 'match', 'fullmatch', 'findall', 'finditer'})

    def library(node):
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''
        return (isinstance(func, ast.Attribute) and name == 'search') or (name in {'execute', 'executemany'} and bool(node.args) and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and ' MATCH ' in node.args[0].value.upper())

    def match_op(node):
        if isinstance(node, ast.Compare) and any(isinstance(op, ast.In) for op in node.ops):
            return True
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if library(node):
            return True
        if isinstance(func, ast.Attribute):
            return func.attr in {'search', 'match', 'find', 'startswith', 'endswith'} or (isinstance(func.value, ast.Name) and func.value.id in aliases and func.attr in {'fullmatch', 'findall', 'finditer'})
        return isinstance(func, ast.Name) and func.id in direct_regex

    routes = set()
    for node in ast.walk(tree):
        if library(node):
            routes.add('C')
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = {a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs}
            params.update(a.arg for a in (node.args.vararg, node.args.kwarg) if a)
            query = params & QUERY_NAMES
            operations = [op for statement in node.body for op in ast.walk(statement) if match_op(op)]
            if 'search' in node.name.lower() and operations:
                routes.add('A')
            if query and any(any(isinstance(n, ast.Name) and n.id in query for n in ast.walk(op)) for op in operations):
                routes.add('B')
    return sorted(routes)


def audit(root, ignores=(), fail_on='HIGH'):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('root must be a readable directory')
    positives, negatives, production, testing, warnings = [], [], [], [], []
    try:
        paths = sorted(root.rglob('*'))
        for path in paths:
            if path.is_symlink() or not path.is_file() or any(p.is_symlink() for p in path.parents if p != root.parent):
                continue
            relative = path.relative_to(root).as_posix()
            if any(fnmatch.fnmatchcase(relative, glob) for glob in ignores):
                continue
            parts = path.relative_to(root).parts
            is_doc = relative == 'README.md' or ('docs' in parts[:-1] and path.suffix.lower() == '.md')
            is_test = 'tests' in parts[:-1] or path.name.startswith('test_') or path.name.endswith('_test.py')
            if is_doc:
                yes, no = claims(path.read_text(encoding='utf-8'))
                if yes:
                    positives.append(relative)
                if no:
                    negatives.append(relative)
            if path.suffix != '.py' or any(p in {'fixtures', 'docs', 'examples'} for p in parts[:-1]):
                continue
            try:
                routes = evidence(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeError) as exc:
                warnings.append(relative + ': ' + str(exc))
                continue
            if routes:
                (testing if is_test else production).append({'path': relative, 'routes': routes})
    except OSError as exc:
        raise ValueError(str(exc)) from exc
    findings = []
    if positives and not production:
        findings.append({'rule': 'documented-search-claim-false', 'severity': 'MEDIUM' if testing else 'HIGH', 'message': 'Documented query matching has evidence only in tests.' if testing else 'Documented query matching lacks production evidence.'})
    if negatives and production:
        findings.append({'rule': 'documented-no-search-claim-false', 'severity': 'HIGH', 'message': 'Documented absence conflicts with production query-matching evidence.'})
    failed = any(f['severity'] == 'HIGH' or fail_on == 'MEDIUM' for f in findings)
    return {'verdict': 'FAIL' if failed else 'PASS', 'findings': findings, 'claims': {'positive': positives, 'negative': negatives}, 'evidence': production, 'test_evidence': testing, 'warnings': warnings}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', nargs='?')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=['HIGH', 'MEDIUM'], default='HIGH')
    try:
        args = parser.parse_args(argv)
        if args.root is None:
            parser.error('a root path is required')
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    try:
        result = audit(args.root, args.ignore, args.fail_on)
    except ValueError as exc:
        print(str(exc), file=__import__('sys').stderr)
        return 1
    if args.json:
        print(json.dumps(result))
    else:
        print(result['verdict'])
        for finding in result['findings']:
            print('{severity} {rule}: {message}'.format(**finding))
        if args.verbose:
            print('Evidence: ' + json.dumps(result['evidence']))
            print('Test evidence: ' + json.dumps(result['test_evidence']))
            for warning in result['warnings']:
                print('Warning: ' + warning)
    return 2 if result['verdict'] == 'FAIL' else 0
