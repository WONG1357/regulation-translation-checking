from src.chinese_to_english_pairing import (
    semantic_similarity,
    translate_chinese_blocks,
)
from src.schemas import (
    BlockType,
    ChineseTranslationItem,
    ChineseTranslationResponse,
    ExtractedBlock,
    Language,
)


class FakeTranslationClient:
    def request_json(self, system_prompt, payload, schema):
        assert "Translate the Chinese-language content" in system_prompt
        assert schema is ChineseTranslationResponse
        return ChineseTranslationResponse(
            items=[
                ChineseTranslationItem(
                    block_id=item["block_id"],
                    translated_english="The purpose of this manual is to describe the quality management system.",
                )
                for item in payload["blocks"]
            ]
        )


def test_chinese_is_translated_before_similarity_pairing():
    block = ExtractedBlock(
        block_id="zh",
        page=1,
        block_type=BlockType.paragraph,
        language=Language.zh,
        text="本手册之目的是描述质量管理体系。",
    )
    translations = translate_chinese_blocks([block], FakeTranslationClient())
    assert translations["zh"].startswith("The purpose of this manual")
    assert (
        semantic_similarity(
            translations["zh"],
            "The purpose of this manual is to describe the quality management system.",
        )
        > 0.95
    )


def test_dry_run_does_not_invent_prose_translation():
    block = ExtractedBlock(
        block_id="zh",
        page=1,
        block_type=BlockType.paragraph,
        language=Language.zh,
        text="本手册之目的是描述质量管理体系。",
    )
    assert translate_chinese_blocks([block], None) == {}
