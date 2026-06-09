import pytest

from go_contributor.tools import ast_go


def _has_tree_sitter():
    try:
        import tree_sitter_go  # noqa: F401
        import tree_sitter      # noqa: F401
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _has_tree_sitter(), reason="tree-sitter / tree-sitter-go not installed"
)


def test_extracts_symbols(tiny_go_repo):
    syms = ast_go.index_repo(tiny_go_repo)
    by_name = {s.qualified_name: s for s in syms}
    assert "add" in by_name
    assert "main" in by_name
    # Greeter is a type, Hello is a method.
    assert "Greeter" in by_name
    assert by_name["Greeter"].kind == "type"
    assert any(s.qualified_name == "Greeter.Hello" for s in syms)


def test_parse_ok_true_on_valid_go():
    assert ast_go.parse_ok("package main\nfunc f(){}\n")


def test_parse_ok_false_on_broken_go():
    assert not ast_go.parse_ok("package main\nfunc f({  // mismatched brace\n")


def test_callees_recorded(tiny_go_repo):
    syms = ast_go.index_repo(tiny_go_repo)
    main = next(s for s in syms if s.qualified_name == "main")
    assert "Println" in (main.callees or [])
