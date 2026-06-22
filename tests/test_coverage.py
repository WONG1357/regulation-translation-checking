import unittest

from app import build_coverage_rows
from src.bilingual_pairing import PairingOptions, analyze_bilingual_pairing
from src.utils import DocumentResult, TextBlock


class CoverageTests(unittest.TestCase):
    def test_small_leftover_is_partial_coverage_not_blocking_risk(self):
        texts = [
            "4.2 文件要求 Documentation Requirements",
            "第一项中文。",
            "First English item.",
            "第二项中文。",
            "Second English item.",
            "补充中文。",
        ]
        blocks = [
            TextBlock(
                block_id=f"sample:b:{index}",
                file_name="sample.pdf",
                file_type="pdf",
                text=text,
                block_type="paragraph",
                order=index,
                page_number=1,
            )
            for index, text in enumerate(texts)
        ]
        doc = DocumentResult("sample.pdf", "pdf", blocks, [], {"page_count": 1})
        options = PairingOptions(review_start_section="4.0")
        analysis = analyze_bilingual_pairing(doc, options)
        unpaired = [
            {
                "file name": "sample.pdf",
                "page number": 1,
                "section_id": "4.2",
                "detected language": "Chinese",
                "reason not paired": "No suitable English block immediately followed this Chinese block/group.",
            }
        ]
        _, sections = build_coverage_rows(
            [doc],
            analysis.pairs,
            analysis.pairs,
            unpaired,
            [],
            {"sample.pdf": analysis},
            options,
        )
        self.assertEqual(sections[0]["status"], "Partial coverage")


if __name__ == "__main__":
    unittest.main()
