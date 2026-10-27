# search-claim-audit

Version 0.1.0 audits documented query matching against static source evidence. It operates offline using only the standard library and never executes audited source.

Install and run:

```sh
pip install .
search-claim-audit /path/to/repo --json
python3 -m search_claim_audit /path/to/repo --verbose
python3 -m unittest discover
python3 -m build
```

The positional argument is the repository root. Repeat `--ignore <glob>` to exclude relative paths. `--fail-on HIGH` is the default; `--fail-on MEDIUM` also fails on evidence confined to tests. `--version` prints the version. Exit codes are 0 for PASS, 2 for FAIL and 1 for usage or filesystem errors. JSON contains verdict, findings, claim locations, evidence routes and parse warnings. Verbose text includes evidence paths and routes.

Root README.md and Markdown under a docs path component provide claims. Fenced blocks are excluded; inline code counts. Paragraphs are lowercased, contractions expanded, hyphens replaced and whitespace collapsed. Negative spans are removed before positive matching. At most one finding is emitted for each family. Missing positive evidence is HIGH, or MEDIUM when confined to tests; contradictory negative documentation is HIGH. An empty source tree can substantiate absence but cannot substantiate capability.

## Limitations

Only exact templates count, with word boundaries. Bare nouns such as search, query and find, UI labels, paging, ordering and attribute predicates do not count. The template inventory lives in the implementation and its tests, not in this document, so this document itself stays neutral for a self-check.

Evidence uses AST structure: route A requires a matching operation in a function whose name contains the audited word; route B requires a query parameter referenced in that operation; route C accepts library calls with the relevant method or FTS execution containing the SQL MATCH operator. Supported operations include membership, regular expressions and string prefix, suffix and position methods. This is a structural heuristic, without data flow, runtime correctness guarantees or import execution. Nested bodies count structurally. Import aliases are resolved at module scope for regular expressions. Invalid source produces warnings and supplies no evidence.

Production excludes tests, fixtures, docs, examples, test filename patterns and symlinks. Test evidence is collected separately. Only Markdown and eligible source files are opened; environment files are never read. Glob exclusions apply before file reads. Build artifacts can be excluded explicitly when auditing other repositories.

The rule identifiers are:

```text
documented-search-claim-false
documented-no-search-claim-false
```

MIT licensed. No runtime dependencies.
