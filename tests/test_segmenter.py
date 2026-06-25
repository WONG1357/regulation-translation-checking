from src.layout_segmenter import segment_blocks
from src.schemas import BlockType, ExtractedBlock, Language


def test_segmenter_preserves_multiple_blocks_and_propagates_section():
    raw = [
        ExtractedBlock(
            block_id="h",
            page=1,
            section=None,
            block_type=BlockType.heading,
            language=Language.mixed,
            text="4.2.4 文件控制 Control of documents",
            reading_order=0,
        ),
        ExtractedBlock(
            block_id="zh",
            page=1,
            section=None,
            block_type=BlockType.paragraph,
            language=Language.zh,
            text="文件发布前要得到评审和批准。",
            reading_order=1,
        ),
        ExtractedBlock(
            block_id="en",
            page=1,
            section=None,
            block_type=BlockType.paragraph,
            language=Language.en,
            text="Documents shall be reviewed and approved prior to issue.",
            reading_order=2,
        ),
    ]
    blocks = segment_blocks(raw)
    assert len(blocks) == 3
    assert all(block.section == "4.2.4" for block in blocks)


def test_segmenter_ignores_repeated_header_by_default():
    raw = [
        ExtractedBlock(
            block_id="header",
            page=1,
            block_type=BlockType.header,
            language=Language.mixed,
            text="文件编号 Doc No. QM01",
        )
    ]
    blocks = segment_blocks(raw)
    assert blocks[0].ignored is True


def test_segmenter_classifies_reference_matrix_rows():
    raw = [
        ExtractedBlock(
            block_id="matrix",
            page=14,
            block_type=BlockType.table_row,
            language=Language.mixed,
            text="4.2.1 | 820.40 | 4.2 | QSP0401",
            table_id="t1",
            row_index=1,
        )
    ]
    block = segment_blocks(raw)[0]
    assert block.block_type == BlockType.reference_table
    assert block.content_class == "reference_table"


def test_segmenter_ignores_table_of_contents_locator_fragments():
    raw = [
        ExtractedBlock(
            block_id="toc_title",
            page=7,
            block_type=BlockType.heading,
            language=Language.mixed,
            text="0.1 目录Table of Contents",
            reading_order=1,
        ),
        ExtractedBlock(
            block_id="toc_blob",
            page=7,
            block_type=BlockType.paragraph,
            language=Language.mixed,
            text="\n".join(
                [
                    "章节Chapter 标题Titles 页码Page",
                    "1.0",
                    "公司简介Company History",
                    "20",
                    "4.1",
                    "总则General requirements",
                    "36",
                    "5.4",
                    "策划Planning",
                    "43",
                    "8.2",
                    "监控和测量Monitoring and measurement",
                    "74",
                ]
            ),
            reading_order=2,
        ),
        ExtractedBlock(
            block_id="real_heading",
            page=20,
            block_type=BlockType.heading,
            language=Language.mixed,
            text="1.0 公司简介Company History",
            reading_order=1,
        ),
    ]
    blocks = segment_blocks(raw)
    toc_blocks = [block for block in blocks if block.page == 7]
    assert toc_blocks
    assert all(block.ignored for block in toc_blocks)
    assert all(block.content_class == "table_of_contents" for block in toc_blocks)
    assert not any(
        block.page == 7 and not block.ignored and block.text in {"8.2", "43"}
        for block in blocks
    )
    real_heading = next(block for block in blocks if block.block_id == "real_heading")
    assert real_heading.ignored is False
    assert real_heading.section == "1.0"
    assert real_heading.language == Language.mixed


def test_bare_numeric_fragment_does_not_become_section():
    raw = [
        ExtractedBlock(
            block_id="number",
            page=1,
            block_type=BlockType.paragraph,
            language=Language.unknown,
            text="8.2",
            reading_order=1,
        ),
        ExtractedBlock(
            block_id="body",
            page=1,
            block_type=BlockType.paragraph,
            language=Language.en,
            text="Monitoring and measurement shall be planned.",
            reading_order=2,
        ),
    ]
    blocks = segment_blocks(raw)
    number = next(block for block in blocks if block.block_id == "number")
    body = next(block for block in blocks if block.block_id == "body")
    assert number.ignored is True
    assert number.section is None
    assert body.section is None


def test_chinese_paragraph_with_roman_regulatory_tokens_stays_whole():
    raw = [
        ExtractedBlock(
            block_id="mixed_roman_tokens",
            page=10,
            section="0.3",
            block_type=BlockType.paragraph,
            language=Language.mixed,
            text=(
                "现时，医科创建集团从事于为客户设计、生产、销售塑料及金属外科手术医疗器械和配件。MC 具有\n"
                "生产II 类医疗器械的能力（美国的II 类医疗器械、欧盟的II a 及II b 类医疗器械），这些都是一次性\n"
                "使用器械，包括一次性腹腔手术器械。"
            ),
            reading_order=7,
        )
    ]
    blocks = segment_blocks(raw)
    assert len(blocks) == 1
    assert blocks[0].language == Language.zh
    assert blocks[0].text.count("生产II 类医疗器械") == 1
    assert "\n" not in blocks[0].text


def test_section_classifier_rejects_impossible_jump_and_accepts_valid_next():
    raw = [
        ExtractedBlock(
            block_id="s21",
            page=1,
            block_type=BlockType.heading,
            language=Language.mixed,
            text="2.1 管理职责 Management Responsibility",
            reading_order=1,
        ),
        ExtractedBlock(
            block_id="bad_jump",
            page=1,
            block_type=BlockType.heading,
            language=Language.mixed,
            text="5.4 策划 Planning",
            reading_order=2,
        ),
        ExtractedBlock(
            block_id="child",
            page=1,
            block_type=BlockType.heading,
            language=Language.mixed,
            text="2.1.1 职责 Responsibility",
            reading_order=3,
        ),
        ExtractedBlock(
            block_id="s22",
            page=2,
            block_type=BlockType.heading,
            language=Language.mixed,
            text="2.2 资源 Resource",
            reading_order=4,
        ),
        ExtractedBlock(
            block_id="s30",
            page=3,
            block_type=BlockType.heading,
            language=Language.mixed,
            text="3.0 组织 Organization",
            reading_order=5,
        ),
    ]
    by_id = {block.block_id: block for block in segment_blocks(raw)}
    assert by_id["s21"].section == "2.1"
    assert by_id["bad_jump"].section == "2.1"
    assert by_id["child"].section == "2.1.1"
    assert by_id["s22"].section == "2.2"
    assert by_id["s30"].section == "3.0"


def test_top_of_page_real_section_heading_is_not_discarded_as_header():
    raw = [
        ExtractedBlock(
            block_id="real_top_heading",
            page=24,
            block_type=BlockType.header,
            language=Language.mixed,
            text="3.0 组织及职责Organization & Responsibility",
            bbox=(56.7, 121.3, 282.1, 134.0),
            reading_order=4,
        ),
        ExtractedBlock(
            block_id="sub",
            page=24,
            block_type=BlockType.heading,
            language=Language.en,
            text="3.1 Organization Charts",
            reading_order=5,
        ),
    ]
    by_id = {block.block_id: block for block in segment_blocks(raw)}
    assert by_id["real_top_heading"].ignored is False
    assert by_id["real_top_heading"].block_type == BlockType.heading
    assert by_id["real_top_heading"].section == "3.0"
    assert by_id["sub"].section == "3.1"


def test_section_classification_after_line_split_handles_internal_headings():
    raw = [
        ExtractedBlock(
            block_id="s324",
            page=29,
            block_type=BlockType.heading,
            language=Language.mixed,
            text="3.2.4 研发 Research and Development",
            reading_order=1,
        ),
        ExtractedBlock(
            block_id="director",
            page=29,
            block_type=BlockType.heading,
            language=Language.zh,
            text="3.2.4.1\n研发总监",
            reading_order=2,
        ),
        ExtractedBlock(
            block_id="director_resp",
            page=29,
            block_type=BlockType.heading,
            language=Language.zh,
            text="3.2.4.1.1\n向总经理负责所有工程事宜及协调临床事宜",
            reading_order=3,
        ),
        ExtractedBlock(
            block_id="eng_manager",
            page=29,
            block_type=BlockType.heading,
            language=Language.zh,
            text="3.2.4.2\n工程经理",
            reading_order=4,
        ),
        ExtractedBlock(
            block_id="eng_resp",
            page=29,
            block_type=BlockType.heading,
            language=Language.zh,
            text="3.2.4.2.1\n向研发总监负责，处理部门技术和工程相关事宜",
            reading_order=5,
        ),
    ]
    blocks = [block for block in segment_blocks(raw) if not block.ignored]
    by_text = {block.text: block.section for block in blocks}
    assert by_text["3.2.4 研发 Research and Development"] == "3.2.4"
    assert by_text["研发总监"] == "3.2.4.1"
    assert by_text["向总经理负责所有工程事宜及协调临床事宜"] == "3.2.4.1.1"
    assert by_text["工程经理"] == "3.2.4.2"
    assert by_text["向研发总监负责，处理部门技术和工程相关事宜"] == "3.2.4.2.1"
