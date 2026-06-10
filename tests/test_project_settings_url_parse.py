"""Unit tests for GitHub URL parsing used by OSS project settings API."""

from __future__ import annotations

import pytest

from amprealize.project_settings_api import parse_github_repository_url

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/foo/bar", ("foo", "bar")),
        ("https://github.com/foo/bar/", ("foo", "bar")),
        ("http://github.com/foo/bar.git", ("foo", "bar")),
        ("git@github.com:foo/bar.git", ("foo", "bar")),
        ("", None),
        ("https://gitlab.com/foo/bar", None),
        ("https://github.com/foo", None),
    ],
)
def test_parse_github_repository_url(url: str, expected):
    assert parse_github_repository_url(url) == expected
