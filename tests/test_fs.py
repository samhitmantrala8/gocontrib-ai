from go_contributor.tools import fs

import pytest


def test_read_write_roundtrip(tiny_go_repo):
    fs.write_file(tiny_go_repo, "hello.txt", "hi\n")
    assert fs.read_file(tiny_go_repo, "hello.txt") == "hi\n"


def test_list_dir_filters_git(tiny_go_repo):
    entries = fs.list_dir(tiny_go_repo)
    assert "main.go" in entries
    assert all(not e.startswith(".git") for e in entries)


def test_path_escape_blocked(tiny_go_repo):
    with pytest.raises(fs.PathOutsideRepoError):
        fs.read_file(tiny_go_repo, "../../etc/passwd")


def test_walk_go_files(tiny_go_repo):
    files = fs.walk_go_files(tiny_go_repo)
    assert "main.go" in files
    assert "main_test.go" in files
