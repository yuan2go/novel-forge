# MKAOS Knowledge Asset OS Acceptance Suite

## Scope

`tests/acceptance/test_mkaos_knowledge_asset_os.py` validates the MKAOS P1 vertical slice:

1. source import through the import pipeline;
2. source chunk and evidence span creation;
3. knowledge extraction candidate and approval;
4. knowledge card and usage bindings;
5. selector v2 and knowledge pack build;
6. source isolation in prose pack;
7. artifact validation and MKAOS issue generation;
8. ReviewIssue persistence;
9. RevisionTask candidate creation;
10. reader feedback attribution;
11. feedback learning snapshot;
12. lineage report;
13. pack debugger;
14. regression case suite.

## Command

```bash
PYTHONPATH=src python3 -m unittest tests.acceptance.test_mkaos_knowledge_asset_os
```

## Acceptance Result

Latest local run: passed.

The suite is deterministic, local-first, and does not call real providers or external platform APIs.

## Source Isolation

The suite asserts that the acceptance report marks `source_isolation.raw_text_included = false`. Source raw or clean text remains in the evidence layer; production-facing packs and reports carry ids, hashes, and abstract knowledge.

## Known Limits

- It is a fast vertical slice, not a 12-chapter longform stress test.
- The extraction step uses deterministic abstraction rather than a real model.
- Graph reasoning is persisted and queryable, but UI rendering is first-slice list/summary form.
