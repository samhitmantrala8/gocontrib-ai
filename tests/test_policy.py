from go_contributor.guardrails.policy import PolicyConfig, check_diff, check_write, is_banned_path


def _cfg(**kw) -> PolicyConfig:
    base = {
        "max_diff_lines": 400,
        "max_files_touched": 8,
        "banned_paths": ["vendor/", "*.pem", "go.sum", ".github/workflows/"],
        "banned_patterns": ["panic("],
        "forbid_new_dependencies": True,
    }
    base.update(kw)
    return PolicyConfig.from_dict(base)


def test_banned_directory_match():
    cfg = _cfg()
    assert is_banned_path("vendor/x.go", cfg.banned_paths)


def test_banned_glob_match():
    cfg = _cfg()
    assert is_banned_path("certs/server.pem", cfg.banned_paths)


def test_check_write_blocks_panic_pattern():
    cfg = _cfg()
    v = check_write("foo.go", "package x\nfunc bad(){ panic(\"no\") }", cfg)
    assert any("panic(" in s for s in v)


def test_check_write_blocks_go_mod():
    cfg = _cfg()
    v = check_write("go.mod", "module x\n", cfg)
    assert any("go.mod" in s for s in v)


def test_check_diff_too_many_files():
    cfg = _cfg(max_files_touched=2)
    v = check_diff("+a\n+b\n", ["a.go", "b.go", "c.go"], cfg)
    assert any("files touched" in s for s in v)


def test_check_diff_too_large():
    cfg = _cfg(max_diff_lines=2)
    diff = "diff --git a/a b/a\n--- a/a\n+++ b/a\n+x\n+y\n+z\n"
    v = check_diff(diff, ["a.go"], cfg)
    assert any("changed lines" in s for s in v)
