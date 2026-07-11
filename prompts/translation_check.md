# Translation, terminology, and regulatory review

This is the second AI stage. Every supplied pair is already confirmed and marked
`should_check_translation=true`. Do not review pairing uncertainty or missing-language blocks.

Translation checks:

- same subject, action, obligation level, scope, condition, exception, timing, responsibility, status, entity name, procedure number, clause number, date, and version;
- omissions, additions, mistranslations, weakened/strengthened obligations, ambiguous wording, and grammar/style issues;
- medical-device QMS terminology and professional drafting.

Regulatory checks:

- There is exactly one selected target standard/regulation in `detected_regulations`; review
  only against that one target.
- This batch is only a small set of supplied pairs. It cannot establish document-wide
  compliance, coverage, applicability, or absence of evidence.
- Create a regulatory finding only for a pair-local Potential Conflict, Confirmed Conflict,
  or Manual Review Required observation. Never return Compliant, Partially Compliant,
  Missing Evidence, Not Applicable, evidence-not-found, or an overall conclusion.
- Regulatory observations must not assert that content is absent, missing, omitted, lacking,
  nowhere, everywhere, or absent throughout the document. Use a translation observation for
  a pair-local language omission; document-wide absence is outside this batch's scope.
- A Quality Manual may summarize a process and refer to supporting procedures. If the
  supporting procedure is not supplied, use Manual Review Required rather than treating it as
  missing evidence or assigning Major/Critical severity.
- Do not invent evidence that is not present in the supplied pairs.
- Do not assume failure merely because details are not included in the Quality Manual.
- Only classify Confirmed Conflict if the document clearly contradicts the selected standard.
- If applicability depends on scope, product type, design responsibility, manufacturing,
  servicing, sterilization, software, or market region, explain the dependency and require
  manual review.
- Do not over-penalize formatting, section numbering, or wording differences.
- Never claim overall compliance, certification, notified-body acceptance, or legal effect.
- For each regulatory finding, fill these fields where available:
  `decision`, `requirement_summary`, `gap_or_concern`, `manual_review_reason`, and start
  `issue` with `Decision: <category> — ...`.
- After the decision prefix, identify the exact evidence `pair_id` and describe only
  what that pair says. Any reference to the document/manual as a whole will be rejected.
- `regulation` must match the one selected target. A numeric clause/provision may be
  returned only when it occurs explicitly in the supplied pair or selected-target evidence.

Terminology checks:

- identify inconsistent Chinese-English mappings, capitalization, abbreviations, titles, singular/plural usage, and regulatory terminology;
- prefer established terms such as Quality Management System, Medical Device File, Management Representative, Person Responsible for Regulatory Compliance, Corrective Action, and Preventive Action when context supports them.

Severity:

- Critical: a clear pair-local regulatory meaning conflict or wrong obligation that may change
  compliance meaning.
- Major: confirmed meaning mismatch, confirmed wrong regulatory/procedure/document reference,
  or confirmed omission of important operational or regulatory content.
- Minor: terminology, grammar, consistency, or style issue.
- Observation: possible wording improvement or manual regulatory review point.

Regulatory matrix/reference-table rows, headers, footers, page metadata, pure company names,
and headings are excluded upstream. Do not create findings for them. Do not compare clause
numbers by naïve substring extraction. Only report a reference issue when the correctly paired
texts clearly cite different regulatory clauses, procedures, or documents.

For a change-history pair, compare Chinese and English bullet-by-bullet within the same
revision ID. If one bullet is missing, identify that specific bullet. Do not mark the whole
revision row as mismatched merely because bullet counts or ordering differ.

Do not rewrite sound text. Suggestions must be conservative and specific. Every translation
finding must include the exact supplied `pair_id`. Every regulatory and terminology finding
must include `evidence_pair_ids` and `source_block_ids` copied exactly from the supplied pairs.
Never invent either kind of ID. Page, section, Chinese text, English text, and terminology
locations are source-controlled fields and will be replaced from those IDs; do not infer them.
Every translation and regulatory observation must also include `evidence_quote`: one exact,
specific phrase copied from the supplied Chinese or English pair text. It is used as the stable
issue discriminator and will be rejected if it is absent from the authoritative pair.
Return JSON only.
