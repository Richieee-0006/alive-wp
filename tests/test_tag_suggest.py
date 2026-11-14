from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tag_suggest


class TagSuggestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.temp_dir.name) / "tags_cache.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_save_and_load_cache(self) -> None:
        initial = {"1": "Vampire", "2": "The Vampire Diaries"}
        tag_suggest.save_cache(self.cache_path, initial)
        loaded = tag_suggest.load_cache(self.cache_path)
        self.assertEqual(loaded, initial)

    def test_rank_matches_prioritizes_exact_and_prefix(self) -> None:
        tags = {
            "1": "Buffy the Vampire Slayer",
            "2": "vampire",
            "3": "The Vampire Diaries",
            "4": "vampire kiss",
        }
        matches = tag_suggest.rank_matches("vampire", tags)
        # Exact match first
        self.assertEqual(matches[0], ("2", "vampire"))
        # Prefix match second
        self.assertEqual(matches[1], ("4", "vampire kiss"))
        # Word match third
        names = [name for _, name in matches]
        self.assertIn("The Vampire Diaries", names)
        self.assertIn("Buffy the Vampire Slayer", names)

    def test_suggest_tags_offline(self) -> None:
        tags = {"3871": "The Vampire Diaries", "123": "Anime"}
        tag_suggest.save_cache(self.cache_path, tags)

        results = tag_suggest.suggest_tags(
            "#the vamp",
            cache_path=self.cache_path,
            allow_network=False,
        )
        self.assertEqual(results, [("3871", "The Vampire Diaries")])

    def test_suggest_tags_strips_syntax_prefixes(self) -> None:
        tags = {"3871": "The Vampire Diaries"}
        tag_suggest.save_cache(self.cache_path, tags)

        for query in ["#The Vampire", "tag:The Vampire", "id:The Vampire"]:
            results = tag_suggest.suggest_tags(
                query,
                cache_path=self.cache_path,
                allow_network=False,
            )
            self.assertEqual(results, [("3871", "The Vampire Diaries")])

    @mock.patch("urllib.request.urlopen")
    def test_fetch_remote_tags_parsing(self, mock_urlopen) -> None:
        sample_html = (
            '<html><body>'
            '<a href="https://wallhaven.cc/tag/3871">The Vampire Diaries</a>'
            '<a href="https://wallhaven.cc/tag/123">Other Tag</a>'
            '</body></html>'
        ).encode("utf-8")

        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = sample_html
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        remote = tag_suggest.fetch_remote_tags("vampire")
        self.assertEqual(remote, [
            ("3871", "The Vampire Diaries"),
            ("123", "Other Tag"),
        ])
