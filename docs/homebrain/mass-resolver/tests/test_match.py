#!/usr/bin/env python3
"""Unit tests for the pure text matcher. Run: python tests/test_match.py"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from match import clean, compact, match_rank


class MatchTest(unittest.TestCase):
    def test_clean_lowercases_and_strips_punctuation(self):
        self.assertEqual(clean("E-N-G-E-L!"), "e n g e l")

    def test_compact_removes_all_non_alnum(self):
        self.assertEqual(compact("E-N-G-E-L"), "engel")

    def test_exact_match_is_rank_0(self):
        self.assertEqual(match_rank("Engel", "Engel"), 0)

    def test_punctuation_insensitive_exact_is_rank_0(self):
        self.assertEqual(match_rank("E-N-G-E-L", "Engel"), 0)

    def test_prefix_is_rank_1(self):
        self.assertEqual(match_rank("Du", "Du Hast"), 1)

    def test_contains_is_rank_2(self):
        self.assertEqual(match_rank("Hast", "Du Hast"), 2)

    def test_all_tokens_present_is_rank_3(self):
        self.assertEqual(match_rank("hast du", "Du Hast Mich"), 3)

    def test_close_typo_is_rank_4(self):
        self.assertEqual(match_rank("Rammstein", "Ramstein"), 4)

    def test_title_by_artist_uses_title_only(self):
        self.assertEqual(match_rank("Engel by Rammstein", "Engel"), 0)

    def test_no_match_returns_none(self):
        self.assertIsNone(match_rank("Beethoven", "Du Hast"))

    def test_empty_name_returns_none(self):
        self.assertIsNone(match_rank("anything", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
