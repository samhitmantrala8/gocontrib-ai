from go_contributor.tools import grep


def test_grep_finds_function(tiny_go_repo):
    hits = grep.grep(tiny_go_repo, r"func add\(")
    assert any(h["file"] == "main.go" for h in hits)


def test_grep_no_match(tiny_go_repo):
    assert grep.grep(tiny_go_repo, r"definitelyNotPresentXYZ123") == []
