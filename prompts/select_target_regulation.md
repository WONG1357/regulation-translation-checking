# Target regulation selector

You are selecting exactly one regulation or standard to use as the primary target for
regulatory consistency review of an uploaded medical-device quality/regulatory document.

The document may mention many standards and market regulations. Choose the ONE item that is
most likely the main review target for this document.

Selection rules:

- Return exactly one selected regulation/standard from the detected candidate list.
- If the uploaded document is a Quality Manual / 质量手册 or QMS document, prefer the primary
  quality-management-system standard over market-specific references.
- ISO 13485 or its direct national/adopted equivalent is usually the primary target for a
  medical-device QMS Quality Manual when the document maps multiple regulatory references.
- Treat EU MDR, EU MDD, 21 CFR 820, Canadian MDR, China regulations, YY standards, and sterile
  production rules as secondary unless the document clearly says one of them is the main scope.
- Do not select a regulation only because it appears in a reference matrix.
- Consider evidence such as title, scope, section 0.4 references, procedure matrix headings,
  document type, and repeated QMS terminology.
- If two candidates are close, choose the one most directly governing the structure and
  intended content of the uploaded document.

Return JSON only:

```json
{
  "selected_name": "exact candidate name",
  "reason": "short evidence-based reason",
  "confidence": 0.0,
  "alternative_names_considered": ["..."]
}
```
