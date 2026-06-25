# Uncertain bilingual-pair validator

Validate only the supplied uncertain pair. Deterministic matching has already compared the
machine-translated Chinese text with the original English text.

For each pair consider:

- Chinese original text;
- machine-translated English from Chinese;
- candidate original English;
- page, section, block type, revision ID, table metadata, and nearby context.

Rules:

- Confirm only when Chinese and English are translations of the same logical content.
- Similar topic is not enough.
- Do not mix change-history revisions.
- A known bilingual heading may be a `heading_pair` even if the section number appears once.
- Regulatory/reference matrix rows are `table_reference`; they should not proceed to
  translation-equivalence checking.
- Partial translations are `partial_match` and normally require manual review.
- Wrong or doubtful candidates remain uncertain; do not rescue them merely because they are
  adjacent.
- If the candidate English is immediately after the Chinese source in the same section/page,
  treat that as strong layout evidence, because this document often places English directly
  behind each Chinese paragraph.
- Section numbers must progress plausibly. For example, after section `2.1`, the next new
  section can only be `2.1.1`, `2.2`, or `3`/`3.0`. If a candidate depends on an impossible
  section jump, mark it uncertain or wrong unless the nearby context proves the section changed
  on that page.
- The Chinese side should not contain English prose except abbreviations/codes, and the English
  side should not contain Chinese characters. Treat mixed-side leakage as an extraction warning
  in the reason.
- `should_check_translation` is true only for reliable bilingual prose.

Return JSON only, with one item per candidate:

```json
{
  "items": [
    {
      "pair_id": "...",
      "is_correct_pair": true,
      "confidence": 0.0,
      "reason": "...",
      "pair_type": "exact_meaning | partial_match | wrong_pair | heading_pair | table_reference | uncertain",
      "should_check_translation": true
    }
  ]
}
```
