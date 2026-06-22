import unittest

from src.bilingual_pairing import PairingOptions, analyze_bilingual_pairing
from src.block_classification import classify_document_blocks
from src.section_detection import compare_sections, section_sort_key
from src.utils import DocumentResult, TextBlock


def block(index, text, **kwargs):
    return TextBlock(
        block_id=f"sample:b:{index}",
        file_name="sample.pdf",
        file_type="pdf",
        text=text,
        block_type=kwargs.pop("block_type", "paragraph"),
        order=index,
        page_number=kwargs.pop("page_number", 1),
        section_heading=kwargs.pop("section_heading", "2.0 Quality Policy and Objective"),
        **kwargs,
    )


def document(blocks):
    return DocumentResult("sample.pdf", "pdf", blocks, [], {"page_count": 2})


class PairingTests(unittest.TestCase):
    def test_detects_multiple_sections_on_one_page_and_does_not_cross_pair(self):
        doc = document(
            [
                block(0, "4.1 总则 General requirements", block_type="paragraph", section_heading=None),
                block(1, "第一节中文。", section_heading=None),
                block(2, "First section English.", section_heading=None),
                block(3, "4.2 文件要求 Documentation Requirements", block_type="paragraph", section_heading=None),
                block(4, "第二节中文。", section_heading=None),
                block(5, "Second section English.", section_heading=None),
            ]
        )
        analysis = analyze_bilingual_pairing(doc, PairingOptions(review_start_section="4.0"))
        self.assertEqual([item.section_id for item in doc.blocks], ["4.1", "4.1", "4.1", "4.2", "4.2", "4.2"])
        self.assertEqual(len(analysis.pairs), 2)
        self.assertEqual(analysis.pairs[0].section_heading, "4.1 总则 General requirements")
        self.assertEqual(analysis.pairs[1].section_heading, "4.2 文件要求 Documentation Requirements")

    def test_section_continues_across_pages_until_new_heading(self):
        doc = document(
            [
                block(0, "4.2.3 医疗器械文档 Medical Device Document", section_heading=None),
                block(1, "本节开始。", section_heading=None),
                block(2, "This section starts.", section_heading=None),
                block(3, "本节跨页继续。", page_number=2, section_heading=None),
                block(4, "This section continues.", page_number=2, section_heading=None),
                block(5, "4.2.4 文件控制 Document control", page_number=2, section_heading=None),
            ]
        )
        analysis = analyze_bilingual_pairing(doc, PairingOptions(review_start_section="4.0"))
        self.assertEqual(doc.blocks[3].section_id, "4.2.3")
        self.assertEqual(doc.blocks[4].section_id, "4.2.3")
        self.assertEqual(doc.blocks[5].section_id, "4.2.4")
        self.assertEqual(len(analysis.segments), 3)
        self.assertEqual(len(analysis.pairs), 2)

    def test_does_not_pair_across_unrelated_section_heading(self):
        doc = document(
            [
                block(0, "4.1 总则 General", section_heading=None),
                block(1, "只有中文。", section_heading=None),
                block(2, "4.2 文件要求 Documentation", section_heading=None),
                block(3, "English belonging to section 4.2.", section_heading=None),
            ]
        )
        analysis = analyze_bilingual_pairing(doc, PairingOptions(review_start_section="4.0"))
        self.assertEqual(analysis.pairs, [])
        self.assertEqual(analysis.block_status["sample:b:1"], "unpaired")
        self.assertEqual(analysis.block_status["sample:b:3"], "unpaired")

    def test_numeric_section_ordering(self):
        self.assertLess(compare_sections("4.2.9", "4.2.10"), 0)
        self.assertLess(compare_sections("4.2", "4.10"), 0)
        self.assertLess(compare_sections("4.9", "5.0"), 0)
        self.assertEqual(
            sorted(["4.10", "5.0", "4.2.10", "4.2.9"], key=section_sort_key),
            ["4.2.9", "4.2.10", "4.10", "5.0"],
        )

    def test_review_start_uses_numeric_section_order(self):
        doc = document(
            [
                block(0, "4.2.9 前一条 Previous clause", section_heading=None),
                block(1, "前一条中文。", section_heading=None),
                block(2, "Previous clause English.", section_heading=None),
                block(3, "4.2.10 后一条 Later clause", section_heading=None),
                block(4, "后一条中文。", section_heading=None),
                block(5, "Later clause English.", section_heading=None),
            ]
        )
        analysis = analyze_bilingual_pairing(doc, PairingOptions(review_start_section="4.2.10"))
        self.assertEqual(len(analysis.pairs), 1)
        self.assertEqual(analysis.pairs[0].chinese_text, "后一条中文。")

    def test_revision_table_clause_reference_is_not_a_section_heading(self):
        doc = document(
            [
                block(0, "2.0 质量方针 Quality Policy", section_heading=None),
                block(
                    1,
                    "8.2.3 into Supporting Procedure of existing section 8.2.5",
                    block_type="table_cell",
                    section_heading=None,
                    table_index=0,
                    row_index=1,
                    cell_index=2,
                    extraction_source="table",
                ),
                block(2, "正文中文。", section_heading=None),
                block(3, "Main English text.", section_heading=None),
            ]
        )
        analysis = analyze_bilingual_pairing(doc)
        self.assertEqual(doc.blocks[1].section_id, "2.0")
        self.assertEqual(doc.blocks[2].section_id, "2.0")
        self.assertEqual(len(analysis.pairs), 1)

    def test_recovers_parallel_language_runs_within_one_section_segment(self):
        doc = document(
            [
                block(0, "4.2 文件要求 Documentation Requirements", section_heading=None),
                block(1, "第一项中文。", section_heading=None),
                block(2, "第二项中文。", section_heading=None),
                block(3, "First English item.", section_heading=None),
                block(4, "Second English item.", section_heading=None),
            ]
        )
        analysis = analyze_bilingual_pairing(doc, PairingOptions(review_start_section="4.0"))
        self.assertEqual(len(analysis.pairs), 2)
        self.assertTrue(all("parallel" in pair.pairing_reason for pair in analysis.pairs))

    def test_pairs_interleaved_chinese_then_english(self):
        analysis = analyze_bilingual_pairing(
            document(
                [
                    block(0, "本手册规定质量管理体系的目的。"),
                    block(1, "This manual defines the purpose of the quality management system."),
                    block(2, "本手册适用于所有部门。"),
                    block(3, "This manual applies to all departments."),
                ]
            )
        )
        self.assertEqual(len(analysis.pairs), 2)
        self.assertEqual(analysis.pairs[0].chinese_block_ids, ["sample:b:0"])
        self.assertEqual(analysis.pairs[0].english_block_ids, ["sample:b:1"])
        self.assertEqual(analysis.pairs[1].chinese_block_ids, ["sample:b:2"])
        self.assertEqual(analysis.pairs[1].english_block_ids, ["sample:b:3"])

    def test_merges_wrapped_lines_before_pairing(self):
        analysis = analyze_bilingual_pairing(
            document(
                [
                    block(0, "本手册用于规定质量管理体系", bbox=(50, 100, 300, 112)),
                    block(1, "并明确各部门的职责。", bbox=(50, 114, 250, 126)),
                    block(2, "This manual defines the quality management", bbox=(50, 130, 350, 142)),
                    block(3, "system and departmental responsibilities.", bbox=(50, 144, 350, 156)),
                ]
            )
        )
        self.assertEqual(len(analysis.pairs), 1)
        self.assertEqual(analysis.pairs[0].chinese_block_ids, ["sample:b:0", "sample:b:1"])
        self.assertEqual(analysis.pairs[0].english_block_ids, ["sample:b:2", "sample:b:3"])
        self.assertIn("paragraph continuation merged", analysis.pairs[0].pairing_reason)

    def test_does_not_over_group_interleaved_bullets(self):
        analysis = analyze_bilingual_pairing(
            document(
                [
                    block(0, "1. 增加管理评审要求"),
                    block(1, "1. Add management review requirements"),
                    block(2, "2. 更新程序编号"),
                    block(3, "2. Update the procedure number"),
                ]
            )
        )
        self.assertEqual(len(analysis.pairs), 2)
        self.assertEqual(analysis.pairs[0].chinese_text, "增加管理评审要求")
        self.assertEqual(analysis.pairs[0].english_text, "Add management review requirements")
        self.assertEqual(analysis.pairs[1].english_text, "Update the procedure number")

    def test_removes_leading_clause_numbers_but_preserves_meaningful_numbers(self):
        analysis = analyze_bilingual_pairing(
            document(
                [
                    block(0, "3.2.4.3.1 向董事总经理汇报所有技术发展事宜，包括3D模型设计。"),
                    block(1, "3.2.4.3.1 Report all technological development matters, including 3D model design."),
                ]
            )
        )
        self.assertEqual(
            analysis.pairs[0].chinese_text,
            "向董事总经理汇报所有技术发展事宜，包括3D模型设计。",
        )
        self.assertEqual(
            analysis.pairs[0].english_text,
            "Report all technological development matters, including 3D model design.",
        )
        self.assertTrue(analysis.pairs[0].chinese_block_ids)

    def test_splits_mixed_bilingual_block(self):
        analysis = analyze_bilingual_pairing(
            document([block(0, "质量手册 Quality Manual")]),
            PairingOptions(include_headings=True),
        )
        self.assertEqual(len(analysis.pairs), 1)
        self.assertEqual(analysis.pairs[0].chinese_text, "质量手册")
        self.assertEqual(analysis.pairs[0].english_text, "Quality Manual")
        self.assertEqual(analysis.pairs[0].pairing_reason, "same mixed bilingual line")

    def test_pairs_table_cells_in_row_order(self):
        analysis = analyze_bilingual_pairing(
            document(
                [
                    block(0, "管理评审", block_type="table_cell", table_index=0, row_index=2, cell_index=0),
                    block(1, "Management review", block_type="table_cell", table_index=0, row_index=2, cell_index=1),
                ]
            )
        )
        self.assertEqual(len(analysis.pairs), 1)
        self.assertEqual(analysis.pairs[0].pairing_reason, "same table row")
        self.assertEqual(analysis.pairs[0].confidence, "High")

    def test_ignores_repeated_header_by_default_but_accounts_for_it(self):
        header = block(0, "质量管理体系 Quality Management System")
        header.is_repeated_header_footer = True
        analysis = analyze_bilingual_pairing(
            document(
                [
                    header,
                    block(1, "适用范围。"),
                    block(2, "Scope of application."),
                ]
            )
        )
        self.assertEqual(len(analysis.pairs), 1)
        self.assertEqual(analysis.block_status[header.block_id], "ignored header-footer")

    def test_never_pairs_with_earlier_english(self):
        analysis = analyze_bilingual_pairing(
            document(
                [
                    block(0, "Earlier English text."),
                    block(1, "后面的中文内容。"),
                ]
            )
        )
        self.assertEqual(analysis.pairs, [])
        self.assertEqual(analysis.block_status["sample:b:1"], "unpaired")

    def test_default_review_start_ignores_pre_section_two(self):
        analysis = analyze_bilingual_pairing(
            document(
                [
                    block(0, "早期内容。", section_heading="1.0 Scope"),
                    block(1, "Earlier content.", section_heading="1.0 Scope"),
                    block(2, "正文内容。", section_heading="2.0 Quality Policy"),
                    block(3, "Main content.", section_heading="2.0 Quality Policy"),
                ]
            )
        )
        self.assertEqual(len(analysis.pairs), 1)
        self.assertEqual(analysis.pairs[0].chinese_text, "正文内容。")
        self.assertTrue(analysis.block_status["sample:b:0"].startswith("ignored"))

    def test_headings_and_metadata_are_ignored_by_default(self):
        analysis = analyze_bilingual_pairing(
            document(
                [
                    block(0, "2.0 质量方针和目标 Quality Policy and Objective", block_type="heading"),
                    block(1, "文件编号 Doc No. QM01"),
                    block(2, "质量方针应得到实施。"),
                    block(3, "The quality policy shall be implemented."),
                ]
            )
        )
        self.assertEqual(len(analysis.pairs), 1)
        self.assertEqual(analysis.block_status["sample:b:0"], "ignored heading")
        self.assertEqual(analysis.block_status["sample:b:1"], "ignored document metadata")

    def test_every_block_gets_deterministic_audit_fields(self):
        doc = document(
            [
                block(0, "1.0 范围", block_type="heading", section_heading="1.0 范围"),
                block(1, "早期中文内容。", section_heading="1.0 范围"),
                block(2, "2.0 质量方针和目标", block_type="heading", section_heading="2.0 质量方针和目标"),
                block(3, "质量方针应得到实施。", section_heading="2.0 质量方针和目标"),
                block(4, "The quality policy shall be implemented.", section_heading="2.0 Quality Policy and Objective"),
            ]
        )
        classify_document_blocks(doc, 2.0)
        self.assertEqual(doc.blocks[1].classification, "main_chinese_paragraph")
        self.assertIn("before configured review start", doc.blocks[1].ignore_reason)
        self.assertEqual(doc.blocks[3].classification, "main_chinese_paragraph")
        self.assertEqual(doc.blocks[3].ignore_reason, "")
        self.assertEqual(doc.blocks[4].classification, "main_english_translation")
        self.assertTrue(all(item.detected_language for item in doc.blocks))
        self.assertTrue(all(item.extraction_source for item in doc.blocks))

    def test_reference_and_definition_sections_are_kept_but_ignored(self):
        doc = document(
            [
                block(0, "3.0 Definitions and abbreviations", block_type="heading", section_heading="3.0 Definitions and abbreviations"),
                block(1, "QMS means quality management system.", section_heading="3.0 Definitions and abbreviations"),
                block(2, "4.0 质量职责", block_type="heading", section_heading="4.0 质量职责"),
                block(3, "管理者应确保职责明确。", section_heading="4.0 质量职责"),
                block(4, "Management shall ensure responsibilities are defined.", section_heading="4.0 Quality Responsibilities"),
            ]
        )
        analysis = analyze_bilingual_pairing(doc)
        self.assertEqual(doc.blocks[1].classification, "definitions_abbreviation")
        self.assertEqual(analysis.block_status[doc.blocks[1].block_id], "ignored definitions")
        self.assertEqual(len(analysis.pairs), 1)


if __name__ == "__main__":
    unittest.main()
