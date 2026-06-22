import unittest
from unittest.mock import patch

from src.llm_client import LLMConfig
from src.section_ai_review import (
    SectionPackage,
    analyze_sections_with_ai,
    build_section_packages,
    validate_section_response,
)
from src.utils import DocumentResult, TextBlock


def block(index, text, page=1):
    return TextBlock(
        block_id=f"sample:b:{index}",
        file_name="sample.pdf",
        file_type="pdf",
        text=text,
        block_type="paragraph",
        order=index,
        page_number=page,
    )


class SectionAIReviewTests(unittest.TestCase):
    def test_package_contains_complete_section_across_pages(self):
        doc = DocumentResult(
            "sample.pdf",
            "pdf",
            [
                block(0, "4.2 文件要求 Documentation Requirements"),
                block(1, "第一页中文。"),
                block(2, "First page English."),
                block(3, "第二页中文。", page=2),
                block(4, "Second page English.", page=2),
                block(5, "4.2.1 总则 General", page=2),
            ],
            [],
            {"page_count": 2},
        )
        packages = build_section_packages([doc], review_start_section="4.0")
        self.assertEqual([item.section_id for item in packages], ["4.2", "4.2.1"])
        self.assertEqual(len(packages[0].blocks), 5)
        self.assertEqual((packages[0].page_start, packages[0].page_end), (1, 2))

    def test_one_api_call_receives_whole_section_without_block_limit(self):
        package = SectionPackage(
            document_name="sample.pdf",
            section_id="4.2",
            section_title="Documentation Requirements",
            page_start=1,
            page_end=3,
            blocks=[
                {"block_id": f"b:{index}", "text": f"text {index}"}
                for index in range(150)
            ],
        )
        response = {
            "section_id": "4.2",
            "section_title": "Documentation Requirements",
            "page_start": 1,
            "page_end": 3,
            "block_audit": [
                {
                    "block_id": f"b:{index}",
                    "classification": "ignored",
                    "pair_id": None,
                    "reason": "test",
                }
                for index in range(150)
            ],
            "pairs": [],
            "translation_issues": [],
            "wording_consistency": [],
            "warnings": [],
        }
        with patch("src.section_ai_review.call_llm_json", return_value=response) as call:
            results = analyze_sections_with_ai(
                [package],
                LLMConfig("DeepSeek", "sk-test", "model", "https://api.deepseek.com"),
            )
        self.assertEqual(call.call_count, 1)
        sent = call.call_args.args[1][1]["content"]
        self.assertIn('"block_id": "b:149"', sent)
        self.assertEqual(results[0].status, "No main content")

    def test_missing_block_audit_rejects_section(self):
        package = SectionPackage(
            "sample.pdf",
            "4.2",
            "Documentation Requirements",
            1,
            1,
            [{"block_id": "b:1", "text": "中文"}, {"block_id": "b:2", "text": "English"}],
        )
        result = validate_section_response(
            package,
            {
                "section_id": "4.2",
                "page_start": 1,
                "page_end": 1,
                "block_audit": [
                    {
                        "block_id": "b:1",
                        "classification": "chinese_source",
                        "pair_id": None,
                        "reason": "",
                    }
                ],
                "pairs": [],
                "translation_issues": [],
                "wording_consistency": [],
            },
        )
        self.assertEqual(result.status, "Needs review")
        self.assertEqual(result.missing_block_ids, ["b:2"])


if __name__ == "__main__":
    unittest.main()
