from src.regulation_detector import select_primary_regulation
from src.schemas import DetectedRegulation, RegulationSelectionResponse


def reg(name, page=1, aliases=None):
    return DetectedRegulation(
        name=name,
        version="unknown",
        evidence_text=name,
        page=page,
        section="0.4",
        confidence=0.9,
        aliases=aliases or [],
    )


def test_primary_regulation_fallback_prefers_iso_13485_for_quality_manual():
    selected, reason = select_primary_regulation(
        [
            reg("EU MDR Regulation (EU) 2017/745", page=11),
            reg("ISO 13485", page=11, aliases=["ISO13485"]),
            reg("21 CFR Part 820", page=11),
        ],
        [],
        client=None,
    )
    assert [item.name for item in selected] == ["ISO 13485"]
    assert "fallback" in reason.lower()


def test_primary_regulation_uses_ai_choice_when_available():
    class FakeSelector:
        def request_json(self, prompt, payload, schema):
            assert schema is RegulationSelectionResponse
            assert len(payload["detected_regulations"]) == 2
            return RegulationSelectionResponse(
                selected_name="21 CFR Part 820",
                reason="The document scope explicitly targets US QSR.",
                confidence=0.93,
                alternative_names_considered=["ISO 13485"],
            )

    selected, reason = select_primary_regulation(
        [
            reg("ISO 13485", aliases=["ISO13485"]),
            reg("21 CFR Part 820", aliases=["21 CFR 820"]),
        ],
        [],
        client=FakeSelector(),
    )
    assert [item.name for item in selected] == ["21 CFR Part 820"]
    assert "US QSR" in reason
    assert selected[0].confidence == 0.93
