"""
Wargame W1 backstop: no LLM-accessible tool returns rows joined against
`snps` or `pedigree*`. This is the schema-level guard — even if the
privacy regex misses a clever rephrase, the model has no SURFACE to leak
raw genotypes.

This test asserts that:
  1. No tool name is `get_snps`, `get_pedigree`, `run_sql`, or `read_file`.
  2. The `get_traits` SQL queries don't reference `snps` or `pedigree`.
"""

from __future__ import annotations

import inspect

from app.llm import tools


FORBIDDEN_TOOL_NAMES = {"get_snps", "get_pedigree", "run_sql", "read_file"}


def test_forbidden_tool_names_absent():
    names = {t["name"] for t in tools.TOOL_SCHEMAS}
    for forbidden in FORBIDDEN_TOOL_NAMES:
        assert forbidden not in names, f"{forbidden} must not be exposed"


def test_no_write_prefix_in_tool_names():
    """W8 — no write surface, ever."""
    for t in tools.TOOL_SCHEMAS:
        n = t["name"]
        assert not n.startswith(("set_", "write_", "delete_", "insert_", "update_")), (
            f"{n} starts with a write-flavored prefix"
        )


def test_get_traits_does_not_reference_snps_or_pedigree():
    src = inspect.getsource(tools.get_traits)
    s = src.lower()
    assert " from snps" not in s
    assert " join snps" not in s
    assert " from pedigree" not in s
    assert " join pedigree" not in s


def test_no_tool_function_references_pedigree_in_sql():
    """Every registered tool's SQL must not reference `pedigree` or `snps`
    as a table. We allow the words in docstrings/comments — the test
    looks specifically for SQL clauses (`from <table>`, `join <table>`)."""
    forbidden_sql_clauses = (
        "from snps", "join snps",
        "from pedigree", "join pedigree",
        "from pedigree_conditions", "join pedigree_conditions",
    )
    for name, fn in tools.TOOL_FUNCS.items():
        src = inspect.getsource(fn).lower()
        # Strip docstring(s) so commentary doesn't false-positive
        # (rudimentary: drop the first """...""" block).
        for delim in ('"""', "'''"):
            if delim in src:
                first = src.find(delim)
                second = src.find(delim, first + len(delim))
                if first != -1 and second != -1:
                    src = src[:first] + src[second + len(delim):]
        for clause in forbidden_sql_clauses:
            assert clause not in src, f"tool {name} SQL references `{clause}`"
