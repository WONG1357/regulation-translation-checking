from src.bilingual_pairer import pair_blocks, validate_pairs_with_ai
from src.schemas import (
    BlockType,
    ExtractedBlock,
    Language,
    PairStatus,
    PairValidationItem,
    PairValidationResponse,
)
from src.translation_checker import deterministic_translation_checks


def paragraph(block_id, language, text, order, *, revision=None):
    return ExtractedBlock(
        block_id=block_id,
        page=10,
        section="0.3",
        block_type=BlockType.paragraph,
        language=language,
        text=text,
        reading_order=order,
        revision_id=revision,
        content_class="change_history" if revision else "bilingual_prose",
    )


def test_pairer_uses_machine_translation_similarity_not_position():
    blocks = [
        paragraph("zh1", Language.zh, "本手册适用于所有医疗器械。", 1),
        paragraph("en_wrong", Language.en, "The products require sterilization.", 2),
        paragraph("zh2", Language.zh, "产品不需要安装和服务。", 3),
        paragraph(
            "en1", Language.en, "This manual applies to all medical devices.", 8
        ),
        paragraph(
            "en2",
            Language.en,
            "The products do not require installation or service.",
            9,
        ),
    ]
    translations = {
        "zh1": "This manual applies to all medical devices.",
        "zh2": "The products do not require installation or service.",
    }
    pairs = pair_blocks(blocks, translations)
    confirmed = [
        pair for pair in pairs if pair.pair_status == PairStatus.confirmed
    ]
    assert {(pair.chinese_block_id, pair.english_block_id) for pair in confirmed} == {
        ("zh1", "en1"),
        ("zh2", "en2"),
    }


def test_low_similarity_is_not_forced_or_major():
    block = paragraph("zh", Language.zh, "仅有中文。", 1)
    pairs = pair_blocks([block], {"zh": "Chinese text only."})
    assert pairs[0].pair_status == PairStatus.missing_english
    assert pairs[0].should_check_translation is False
    assert deterministic_translation_checks(pairs) == []


def test_heading_glossary_handles_section_number_once():
    blocks = [
        ExtractedBlock(
            block_id="zh",
            page=1,
            section="0.1",
            block_type=BlockType.heading,
            language=Language.zh,
            text="0.1 目录",
        ),
        ExtractedBlock(
            block_id="en",
            page=1,
            section="0.1",
            block_type=BlockType.heading,
            language=Language.en,
            text="Table of Contents",
        ),
    ]
    pairs = pair_blocks(blocks, {"zh": "Table of Contents"})
    pair = next(pair for pair in pairs if pair.pair_status == PairStatus.confirmed)
    assert pair.pairing_method == "heading_glossary"
    assert pair.should_check_translation is False


def test_change_history_revisions_are_not_mixed():
    chinese = paragraph(
        "zh_b", Language.zh, "修改范围。", 1, revision="B"
    )
    wrong_revision = paragraph(
        "en_c", Language.en, "Updated the scope.", 2, revision="C"
    )
    pairs = pair_blocks(
        [chinese, wrong_revision], {"zh_b": "Updated the scope."}
    )
    assert not any(pair.pair_status == PairStatus.confirmed for pair in pairs)


def test_reference_table_pair_never_enters_translation_checking():
    block = ExtractedBlock(
        block_id="row",
        page=14,
        section="0.7",
        block_type=BlockType.reference_table,
        language=Language.mixed,
        text="4.2.1 | 文件控制 Document Control | 820.40 | QSP0401",
        content_class="reference_table",
        table_id="matrix",
        row_index=1,
    )
    pair = pair_blocks([block], {})[0]
    assert pair.pair_status == PairStatus.confirmed
    assert pair.should_check_translation is False
    assert deterministic_translation_checks([pair]) == []


def test_regulatory_matrix_is_preserved_not_normally_paired():
    block = ExtractedBlock(
        block_id="matrix_row",
        page=14,
        section="0.7",
        block_type=BlockType.reference_table,
        language=Language.mixed,
        text=(
            "7.3.1 | 总则 | 820.30(a) | 7.3.1 | "
            "QSP0704 设计与开发控制 Design and Development Control"
        ),
        content_class="regulatory_matrix",
    )
    pair = pair_blocks([block], {})[0]
    assert pair.pair_status == PairStatus.unpaired
    assert pair.needs_manual_review is False
    assert "normal bilingual pairing is not required" in pair.pairing_reason
    assert pair.should_check_translation is False


def test_english_only_definition_is_not_missing_chinese():
    block = ExtractedBlock(
        block_id="company_def",
        page=12,
        section="0.5",
        block_type=BlockType.table_row,
        language=Language.en,
        text="Company | Means any one of MC, NM",
        content_class="definition_table",
    )
    pair = pair_blocks([block], {})[0]
    assert pair.pair_status == PairStatus.unpaired
    assert pair.needs_manual_review is False
    assert "Company" in pair.unpaired_text
    assert "normal bilingual pairing is not required" in pair.pairing_reason


def test_same_block_delimited_row_uses_translation_cells_and_cleans_tags():
    block = ExtractedBlock(
        block_id="row",
        page=2,
        section="0.5",
        block_type=BlockType.table_row,
        language=Language.mixed,
        text="<tr><td>0.5</td> | <td>定义/简写</td> | <td>Definitions and Abbreviations</td></tr>",
        table_id="toc",
        row_index=1,
    )
    pair = pair_blocks([block], {"row": "Definitions and Abbreviations"})[0]
    assert pair.pair_status == PairStatus.confirmed
    assert pair.chinese_text == "定义/简写"
    assert pair.english_text == "Definitions and Abbreviations"
    assert "<td>" not in pair.chinese_text


def test_same_block_compact_label_keeps_languages_separate():
    block = ExtractedBlock(
        block_id="planning",
        page=7,
        section="5.4",
        block_type=BlockType.heading,
        language=Language.mixed,
        text="5.4 策划Planning",
        reading_order=1,
    )
    pair = pair_blocks([block], {"planning": "Planning"})[0]
    assert pair.chinese_text == "策划"
    assert pair.english_text == "Planning"
    assert not any("A" <= char <= "z" for char in pair.chinese_text)
    assert not any("\u3400" <= char <= "\u9fff" for char in pair.english_text)


def test_same_block_multilingual_term_removes_english_from_chinese_side():
    block = ExtractedBlock(
        block_id="qms",
        page=4,
        section="4.0",
        block_type=BlockType.heading,
        language=Language.mixed,
        text="质量管理体系Quality Management System",
        reading_order=1,
    )
    pair = pair_blocks([block], {"qms": "Quality Management System"})[0]
    assert pair.chinese_text == "质量管理体系"
    assert pair.english_text == "Quality Management System"


def test_adjacent_line_logic_surfaces_candidate_without_translation():
    blocks = [
        paragraph("en", Language.en, "This manual applies to all medical devices.", 1),
        paragraph("zh", Language.zh, "本手册适用于所有医疗器械。", 2),
    ]
    pairs = pair_blocks(blocks, {})
    pair = next(
        pair
        for pair in pairs
        if pair.chinese_block_id == "zh" and pair.english_block_id == "en"
    )
    assert pair.pair_status == PairStatus.uncertain
    assert pair.pairing_method == "layout_adjacency_candidate"
    assert pair.should_check_translation is False
    assert "structural_adjacency" in pair.pairing_reason


def test_adjacent_english_behind_chinese_is_used_when_translation_matches():
    blocks = [
        paragraph("zh", Language.zh, "本手册适用于所有医疗器械。", 1),
        paragraph("en", Language.en, "This manual applies to all medical devices.", 2),
    ]
    pairs = pair_blocks(
        blocks,
        {"zh": "This manual applies to all medical devices."},
    )
    pair = next(pair for pair in pairs if pair.chinese_block_id == "zh")
    assert pair.english_block_id == "en"
    assert pair.pair_status == PairStatus.confirmed


def test_pair_output_follows_original_chinese_sequence():
    blocks = [
        paragraph("zh1", Language.zh, "第一段。", 1),
        paragraph("en1", Language.en, "First paragraph.", 2),
        paragraph("zh2", Language.zh, "第二段。", 3),
        paragraph("en2", Language.en, "Second paragraph.", 4),
    ]
    pairs = [
        pair
        for pair in pair_blocks(
            blocks,
            {"zh1": "First paragraph.", "zh2": "Second paragraph."},
        )
        if pair.chinese_text
    ]
    assert [pair.chinese_block_id for pair in pairs] == ["zh1", "zh2"]


def test_consecutive_table_rows_are_grouped_before_pairing():
    chinese_rows = [
        "醫創天工主要负责设计，制造及分销微創手術使用的医疗设备的业务，定位为一家國際品牌的",
        "医疗设备制造商。醫創天工的优势在于它独特的技能及经验，在欧洲的医疗器材专家负责设计，",
        "香港负责制造，而中国作主要的生产。这个独特的组合，确保我们为客户提供创新以及高品质",
        "的手術用膠水槍。醫創天工能够提供外科医生所需的高性能，附合人体工程学和高质量方面的",
        "医疗设备。我们承诺聆听医生的需要，结合先进的设计与高端制造技术，使我们超越竞争对手。",
        "我们的使命是改善病人护理，以及保证患者安全。",
    ]
    english_rows = [
        "Medifabrica Ltd. (MF) is in the business of design, manufacturing and distribution of minimally invasive",
        "surgery devices and is positioned as an international brand medical device manufacturer. Medifabrica’s",
        "strength is in its unique mix of skills and experience: European Device Expertise in designs, Hong Kong",
        "managed manufacturing, and China based production. This rare combination ensures that we provide",
        "our customers with innovative, high quality medical devices. Medifabrica’s design devices that deliver",
        "what today’s highly skilled surgeons are looking for in terms of performance, ergonomics and quality.",
        "Our commitment to listening to surgeons, combining leading edge design with high-end manufacturing",
        "technology, gives us an edge over our competitors. Our mission is to improve patient care and ensure",
        "patient safety.",
    ]
    blocks = [
        ExtractedBlock(
            block_id=f"zh{i}",
            page=22,
            section="1.4",
            block_type=BlockType.table_row,
            language=Language.zh,
            text=text,
            reading_order=i,
        )
        for i, text in enumerate(chinese_rows, start=90)
    ] + [
        ExtractedBlock(
            block_id=f"en{i}",
            page=22,
            section="1.4",
            block_type=BlockType.table_row,
            language=Language.en,
            text=text,
            reading_order=i,
        )
        for i, text in enumerate(english_rows, start=96)
    ]
    translations = {
        f"zh{i}": translation
        for i, translation in enumerate(
            [
                "is primarily responsible for the business of designing, manufacturing and distributing medical devices used in minimally invasive surgery, positioned as a globally branded",
                "medical device manufacturer. Its advantage lies in its unique skills and experience, with European medical equipment experts responsible for design,",
                "Hong Kong is responsible for manufacturing, while China serves as the main production base. This unique combination ensures that we provide customers with innovative and high-quality",
                "surgical glue guns. Medifabrica can provide surgeons with high performance, ergonomic and high-quality",
                "medical devices. We are committed to listening to doctors' needs, combining advanced design with high-end manufacturing technology, enabling us to surpass competitors.",
                "Our mission is to improve patient care and ensure patient safety.",
            ],
            start=90,
        )
    }
    pairs = pair_blocks(blocks, translations)
    grouped = next(
        pair
        for pair in pairs
        if pair.pairing_method == "consecutive_paragraph_group"
    )
    assert grouped.pair_status == PairStatus.confirmed
    assert grouped.chinese_block_id == "zh90"
    assert grouped.english_block_id == "en96"
    assert "我们的使命是改善病人护理" in grouped.chinese_text
    assert "patient safety" in grouped.english_text
    assert len(grouped.source_block_ids) == 15
    assert not any(pair.pair_status == PairStatus.missing_english for pair in pairs)
    assert not any(pair.pair_status == PairStatus.missing_chinese for pair in pairs)


def test_same_table_row_cell_logic_surfaces_candidate_without_translation():
    blocks = [
        ExtractedBlock(
            block_id="zh_cell",
            page=3,
            section="0.4",
            block_type=BlockType.table_cell,
            language=Language.zh,
            text="内部流程",
            reading_order=10,
            table_id="tbl",
            row_index=2,
            col_index=1,
        ),
        ExtractedBlock(
            block_id="en_cell",
            page=3,
            section="0.4",
            block_type=BlockType.table_cell,
            language=Language.en,
            text="Internal Process",
            reading_order=11,
            table_id="tbl",
            row_index=2,
            col_index=2,
        ),
    ]
    pairs = pair_blocks(blocks, {})
    pair = next(pair for pair in pairs if pair.chinese_block_id == "zh_cell")
    assert pair.english_block_id == "en_cell"
    assert pair.pair_status == PairStatus.uncertain
    assert pair.pairing_method == "layout_adjacency_candidate"


def test_ai_validates_uncertain_pairs_only():
    blocks = [
        paragraph("zh", Language.zh, "本手册适用于医疗器械。", 1),
        paragraph("en", Language.en, "This manual applies to medical devices.", 2),
    ]
    pairs = pair_blocks(
        blocks,
        {"zh": "This manual is applicable to medical devices."},
        confirmed_threshold=0.98,
        uncertain_threshold=0.60,
    )
    uncertain = next(
        pair for pair in pairs if pair.pair_status == PairStatus.uncertain
    )

    class FakeValidator:
        def request_json(self, prompt, payload, schema):
            assert len(payload["candidate_pairs"]) == 1
            assert schema is PairValidationResponse
            return PairValidationResponse(
                items=[
                    PairValidationItem(
                        pair_id=uncertain.pair_id,
                        is_correct_pair=True,
                        confidence=0.91,
                        reason="The meanings match.",
                        pair_type="exact_meaning",
                        should_check_translation=True,
                    )
                ]
            )

    validated = validate_pairs_with_ai(pairs, blocks, FakeValidator())
    result = next(pair for pair in validated if pair.pair_id == uncertain.pair_id)
    assert result.pair_status == PairStatus.confirmed
    assert result.should_check_translation is True
    assert result.pairing_method == "ai_validated"
