import contextlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from search_claim_audit import audit, claims, evidence, main

ROOT = Path(__file__).resolve().parents[1]


class AuditTests(unittest.TestCase):
    def fixture(self, text='searches', source=None, filename='app.py', fail_on='HIGH'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text(text)
            if source is not None:
                target = root / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source)
            return audit(root, fail_on=fail_on)

    def good(self, source, text='searches'):
        result = self.fixture(text, source)
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(result['findings'], [])

    def bad(self, source):
        result = self.fixture(source=source)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(result['findings'][0]['severity'], 'HIGH')
        self.assertEqual(result['findings'][0]['rule'], 'documented-search-claim-false')

    def test_01_route_a(self):
        self.good('def search_items(items, q): return [x for x in items if q in x]', 'full text search')

    def test_02_route_b(self):
        self.good('def lookup(query): return [x for x in items if query in x["name"]]')

    def test_03_regex(self):
        self.good('import re\ndef find(query): return [x for x in items if re.search(query, x)]', 'fuzzy search')

    def test_04_library(self):
        self.good('client.search(value)', 'search results')

    def test_05_fts(self):
        self.good('cur.execute("SELECT body FROM entries WHERE body MATCH ?", (q,))')

    def test_06_prefix(self):
        self.good('def search_items(items): return name.startswith(value)', 'searchable')

    def test_07_empty_function(self):
        self.bad('def search(): print("hi"); return []')

    def test_08_dict(self):
        self.bad('def lookup(key): return index[key], data.get(key)')

    def test_09_filter(self):
        self.bad('result = filter(lambda x: x.status == "open", items)\nresult = [x for x in items if x.status == "open"]')

    def test_10_paging(self):
        self.bad('result = sorted(items)[offset:offset+limit]')

    def test_11_validation(self):
        self.bad('import re\ndef validate_email(v): return re.match(PAT, v)')

    def test_12_literal(self):
        self.bad('if "error" in text: print(text)')

    def test_13_negative(self):
        result = self.fixture('no search', 'def search_items(): return q in text')
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(result['findings'], [{'rule': 'documented-no-search-claim-false', 'severity': 'HIGH', 'message': 'Documented absence conflicts with production query-matching evidence.'}])

    def test_14_neutral(self):
        self.good('client.search(q)', 'A local tool.')

    def test_15_bare(self):
        self.good('data.get(key)', 'use the search box to find items')

    def test_16_paging_claim(self):
        self.good('sorted(items)[offset:limit]', 'paged results; sorted results; filter by status')

    def test_17_no_source(self):
        self.assertEqual(self.fixture()['verdict'], 'FAIL')
        self.assertEqual(self.fixture('no search')['verdict'], 'PASS')

    def test_18_test_only(self):
        for filename in ('tests/helper.py', 'test_app.py', 'app_test.py'):
            for threshold, verdict in [('HIGH', 'PASS'), ('MEDIUM', 'FAIL')]:
                result = self.fixture(source='def search_items(): return q in text', filename=filename, fail_on=threshold)
                self.assertEqual(result['verdict'], verdict)
                self.assertEqual(result['findings'][0]['severity'], 'MEDIUM')

    def test_19_fences(self):
        self.assertEqual(claims('```text\nsearches\n```\n~~~\nno search\n~~~'), (False, False))
        self.assertEqual(claims('`searches`'), (True, False))

    def test_20_negation(self):
        self.assertEqual(claims('does not search'), (False, True))
        self.assertEqual(claims("doesn't search"), (False, True))

    def test_21_unused(self):
        self.bad('def lookup(query): return []')
        self.bad('def lookup(query): return "error" in text')

    def test_22_cli(self):
        for options, expected in [(['--version'], 0), (['/nonexistent'], 1), ([], 1), (['--unknown'], 1)]:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(options), expected)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main([str(ROOT / 'tests/fixtures/bad'), '--json']), 2)
        self.assertEqual(len(json.loads(out.getvalue())['findings']), 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main([str(ROOT / 'tests/fixtures/good'), '--verbose']), 0)
        self.assertIn('app.py', out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(ROOT / 'tests/fixtures/bad'), '--ignore', 'README.md']), 0)

    def test_23_self(self):
        result = audit(ROOT)
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(result['claims'], {'positive': [], 'negative': []})

    def test_24_env_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('MARKER_ONLY')
            original = Path.open
            def guarded(path, *args, **kwargs):
                self.assertNotEqual(path.name, '.env')
                return original(path, *args, **kwargs)
            with patch.object(Path, 'open', guarded):
                self.assertEqual(audit(root)['verdict'], 'PASS')

    def test_25_packaging(self):
        forbidden = re.compile(r'\b' + 'py' + r'thon\b(?!\s*=)')
        for path in list((ROOT / 'search_claim_audit').glob('*.py')) + list((ROOT / 'tests').rglob('*.py')) + [ROOT / 'README.md']:
            self.assertIsNone(forbidden.search(path.read_text()), str(path))
        config = (ROOT / 'pyproject.toml').read_text() if (ROOT / 'pyproject.toml').exists() else ''
        if config:
            self.assertIn('license = "MIT"', config)
            self.assertIn('setuptools>=77', config)
        self.assertTrue((ROOT / 'tests/fixtures/good/app.py').is_file())

    def test_26_aliases(self):
        for call in ('rx.findall(query, text)', 'fm(query, text)', 'rx.fullmatch(query, text)', 'rx.finditer(query, text)'):
            self.good('import re as rx\nfrom re import fullmatch as fm\ndef lookup(query): return ' + call)

    def test_27_methods(self):
        for call in ('text.find(query)', 'text.endswith(query)', 'compiled.match(query)', 'query.startswith(text)', 'pattern.match(value=query)'):
            self.good('def lookup(query): return ' + call)

    def test_28_exclusions(self):
        for filename in ('docs/app.py', 'examples/app.py', 'fixtures/app.py'):
            self.assertEqual(self.fixture(source='client.search(q)', filename=filename)['findings'][0]['severity'], 'HIGH')

    def test_29_non_evidence(self):
        for source in ('items.index(value); items.count(value)', 'import re\nimport whoosh\nimport elasticsearch', '"client.search(query)"', 'def search_items(): return search_other()', 'import re\ndef lookup(query): return re(query)', 'from re import compile as rc\ndef lookup(query): return rc(query)'):
            self.bad(source)

    def test_30_normalization(self):
        self.assertEqual(claims('FULL-TEXT\nSEARCH'), (True, False))
        self.assertEqual(claims('researches'), (False, False))
        self.assertEqual(claims('search\n\nfor'), (False, False))

    def test_31_both(self):
        result = self.fixture('searches. no search.')
        self.assertEqual(len(result['findings']), 1)

    def test_32_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text('searches')
            (root / 'app.py').symlink_to(ROOT / 'tests/fixtures/good/app.py')
            self.assertEqual(audit(root)['verdict'], 'FAIL')

    def test_33_module(self):
        result = subprocess.run([sys.executable, '-m', 'search_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '0.1.0')

    def test_34_doc_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'nested/docs/deep').mkdir(parents=True)
            (root / 'nested/docs/deep/note.md').write_text('searches')
            self.assertEqual(audit(root)['verdict'], 'FAIL')
            self.assertEqual(audit(root, ['nested/docs/*'])['verdict'], 'PASS')


if __name__ == '__main__':
    unittest.main()
