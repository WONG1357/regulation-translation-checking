import unittest

from src.section_parser import (
    build_section_segments,
    is_valid_next_section,
    parse_section_heading,
    parse_sections,
    section_at_or_after,
    section_order_key,
)
from src.chunker import build_chunks
from src.bilingual_pairer import validate_pairing_result


class NewSectionParserTests(unittest.TestCase):
    def test_supported_number_formats(self):
        expected = {
            "0.1 Purpose": "0.1",
            "1.0 范围 Scope": "1.0",
            "3.2.11 Detailed controls": "3.2.11",
            "7.5.9.b) Records": "7.5.9.b",
            "7.5.9 b) Records": "7.5.9.b",
        }
        for text, section_id in expected.items():
            with self.subTest(text=text):
                self.assertEqual(parse_section_heading(text).section_id, section_id)

    def test_section_continues_across_pages(self):
        blocks = [
            {"block_id": "a", "page": 1, "order": 1, "text": "0.1 Scope", "block_type": "paragraph"},
            {"block_id": "b", "page": 2, "order": 2, "text": "Continued text", "block_type": "paragraph"},
            {"block_id": "c", "page": 2, "order": 3, "text": "0.2 Responsibilities", "block_type": "paragraph"},
        ]
        parsed = parse_sections(blocks)
        self.assertEqual(parsed[1]["section"], "0.1")
        self.assertEqual(parsed[2]["section"], "0.2")

    def test_categories_and_appendices(self):
        revision = parse_section_heading("0.2 Revision History 修订历史")
        appendix = parse_section_heading("Appendix A Forms")
        self.assertEqual(revision.category, "revision_history")
        self.assertEqual(appendix.section_type, "appendix")
        self.assertEqual(appendix.category, "appendix")

    def test_table_clause_reference_is_not_heading(self):
        self.assertIsNone(parse_section_heading("4.2 | Updated wording | 2026-01-01", "table_row"))

    def test_numeric_section_order(self):
        ordered = sorted(["5.0", "4.10", "4.2.10", "4.2.9", "4.2"], key=section_order_key)
        self.assertEqual(ordered, ["4.2", "4.2.9", "4.2.10", "4.10", "5.0"])
        self.assertTrue(section_at_or_after("4.2.1", "2.0"))
        self.assertFalse(section_at_or_after("1.9", "2.0"))

    def test_multiple_sections_per_page_and_continuation_segments(self):
        blocks = [
            {"block_id": "a", "page": 36, "order": 1, "text": "0.1 General", "block_type": "paragraph", "language": "en"},
            {"block_id": "b", "page": 36, "order": 2, "text": "content", "block_type": "paragraph", "language": "en"},
            {"block_id": "c", "page": 36, "order": 3, "text": "0.2 Documentation", "block_type": "paragraph", "language": "en"},
            {"block_id": "d", "page": 37, "order": 4, "text": "continued", "block_type": "paragraph", "language": "en"},
            {"block_id": "e", "page": 37, "order": 5, "text": "0.2.1 General", "block_type": "paragraph", "language": "en"},
        ]
        parsed = parse_sections(blocks)
        self.assertEqual([item["section"] for item in parsed], ["0.1", "0.1", "0.2", "0.2", "0.2.1"])
        segments = build_section_segments(parsed)
        self.assertEqual(len(segments), 4)
        self.assertTrue(segments[2]["continued_from_previous_page"])

    def test_chunks_can_combine_small_sections_and_split_large_section(self):
        blocks = [
            {"block_id": "a", "page": 1, "order": 1, "text": "0.1 General", "block_type": "paragraph", "language": "en"},
            {"block_id": "b", "page": 1, "order": 2, "text": "small", "block_type": "paragraph", "language": "en"},
            {"block_id": "c", "page": 1, "order": 3, "text": "0.2 Documents", "block_type": "paragraph", "language": "en"},
            {"block_id": "d", "page": 1, "order": 4, "text": "small", "block_type": "paragraph", "language": "en"},
        ]
        chunks = build_chunks(parse_sections(blocks), max_characters=1000)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["section_ids"], ["0.1", "0.2"])

        large = [
            {"block_id": "x", "page": 1, "order": 1, "text": "0.1 Large", "block_type": "paragraph", "language": "en"},
            {"block_id": "y", "page": 1, "order": 2, "text": "x" * 300, "block_type": "paragraph", "language": "en"},
            {"block_id": "z", "page": 2, "order": 3, "text": "x" * 300, "block_type": "paragraph", "language": "en"},
        ]
        self.assertGreater(len(build_chunks(parse_sections(large), max_characters=250)), 1)

    def test_python_rejects_cross_section_ai_pair(self):
        result = {
            "pairs": [{
                "pair_id": "bad",
                "chinese_block_ids": ["zh"],
                "english_block_ids": ["en"],
                "chinese_text": "中文",
                "english_text": "English",
                "confidence": 0.9,
                "status": "paired",
            }],
            "block_statuses": [],
        }
        block_map = {
            "zh": {"section": "4.1"},
            "en": {"section": "4.2"},
        }
        pairs, statuses, warnings = validate_pairing_result(
            result, "chunk_001", set(block_map), block_map
        )
        self.assertEqual(pairs, [])
        self.assertTrue(any("cross-section" in warning for warning in warnings))

    def test_document_must_start_at_zero_one(self):
        blocks = [
            {"block_id": "a", "page": 1, "order": 1, "text": "1.0 Wrong start", "block_type": "paragraph"},
            {"block_id": "b", "page": 1, "order": 2, "text": "0.1 Correct start", "block_type": "paragraph"},
        ]
        parsed = parse_sections(blocks)
        self.assertIsNone(parsed[0]["section"])
        self.assertEqual(parsed[0]["section_candidate_rejected"], "1.0")
        self.assertEqual(parsed[1]["section"], "0.1")

    def test_zero_one_has_only_three_valid_next_sections(self):
        self.assertTrue(is_valid_next_section("0.1", "0.2"))
        self.assertTrue(is_valid_next_section("0.1", "1.0"))
        self.assertTrue(is_valid_next_section("0.1", "0.1.1"))
        for invalid in ["0.3", "0.1.2", "1.1", "2.0", "4.2"]:
            with self.subTest(invalid=invalid):
                self.assertFalse(is_valid_next_section("0.1", invalid))

    def test_invalid_candidate_does_not_change_active_section(self):
        blocks = [
            {"block_id": "a", "page": 1, "order": 1, "text": "0.1 Start", "block_type": "paragraph"},
            {"block_id": "b", "page": 1, "order": 2, "text": "0.3 Invalid jump", "block_type": "paragraph"},
            {"block_id": "c", "page": 1, "order": 3, "text": "ordinary content", "block_type": "paragraph"},
            {"block_id": "d", "page": 1, "order": 4, "text": "0.2 Valid next", "block_type": "paragraph"},
        ]
        parsed = parse_sections(blocks)
        self.assertEqual([item["section"] for item in parsed], ["0.1", "0.1", "0.1", "0.2"])
        self.assertEqual(parsed[1]["section_candidate_rejected"], "0.3")


if __name__ == "__main__":
    unittest.main()
