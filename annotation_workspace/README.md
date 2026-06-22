# Standalone PDF Teaching Workspace

A local browser tool for annotating a small number of high-quality Chinese-English examples directly on the original PDF page. It is intentionally separate from the Streamlit review app.

## What it supports

- Open a PDF using the browser file picker.
- Optionally open PDFs placed in the local `pdfs/` folder.
- Render the original page with PDF.js.
- Navigate pages and zoom in or out.
- Select PDF text by dragging across the text layer.
- Draw a rectangle and capture text intersecting that area.
- Label, edit, delete, show, or hide visual annotations.
- Mark wrong auto-pair examples in red when discussing prior extraction output.
- Build Chinese-English pairs from one or more annotations.
- Record page-level or section-level layout rules.
- Export complete JSON, annotations CSV, manual pairs CSV, layout-rules JSON, and a compact Markdown package for ChatGPT.
- Import complete JSON and restore annotations, pairs, rules, notes, and highlights.

## Run locally

Python 3.10 or later is sufficient. No Python packages are required.

```bash
cd "/Users/yichun/Documents/regulation translation + wordings/annotation_workspace"
python3 server.py
```

Open:

[http://localhost:8000](http://localhost:8000)

The PDF.js library is loaded from cdnjs, so the browser needs internet access when the page first loads.

## Open a PDF

Either:

1. Click **Open PDF** and choose a PDF from your computer.
2. Copy PDFs into `annotation_workspace/pdfs/`, refresh the app, choose one from **Local PDFs…**, and click **Open**.

PDF bytes stay in the browser. The server does not upload them elsewhere.

## Recommended annotation workflow

1. Open the PDF and navigate to a representative page.
2. Use **Text selection** to drag across selectable PDF text.
3. If the PDF text layer is fragmented, switch to **Rectangle selection** and draw around the target area.
4. Choose a label and save the annotation.
5. For bilingual examples:
   - select Chinese text and click **Set as Chinese source**;
   - select English text and click **Set as English translation**;
   - repeat if a pair needs several selections;
   - open the **Pairs** tab and click **Create pair**.
6. Add a few layout rules under **Layout rules**.
7. Export the complete JSON for later machine use and the compact Markdown package for discussion with ChatGPT.

The goal is not to annotate every paragraph. Choose a small set that clearly demonstrates:

- the real main Chinese content;
- its corresponding English translation;
- repeated headers, footers, metadata, and company names to ignore;
- revision-history, definitions, reference, or clause-matrix table structure;
- cases where multiple blocks belong to one pair.

## Coordinate format

Coordinates are normalized to the displayed PDF page:

```json
{
  "x1": 0.10,
  "y1": 0.22,
  "x2": 0.84,
  "y2": 0.29
}
```

- Origin: top-left.
- Range: `0` to `1`.
- Coordinates remain stable across zoom levels.
- Text selections may contain several rectangles in `rects`.

## Export files

### Complete annotation JSON

Contains:

- source PDF filename and page count;
- normalized coordinate-system description;
- all annotations;
- all expanded manual pairs;
- all layout rules;
- hidden annotation types;
- general notes;
- intended downstream uses.

This is the best file for later Streamlit integration and for restoring the workspace.

### Annotations CSV

Columns:

- `annotation_id`
- `file_name`
- `page_number`
- `label`
- `selected_text`
- `x1`, `y1`, `x2`, `y2`
- `manual_pair_id`
- `pair_role`
- `pair_type`
- `user_note`

### Manual pairs CSV

Columns:

- `manual_pair_id`
- `file_name`
- `page_number`
- `pair_type`
- `chinese_text`
- `english_text`
- `chinese_annotation_ids`
- `english_annotation_ids`
- `chinese_coordinates`
- `english_coordinates`
- `user_note`

### Layout rules JSON

Contains every rule and its linked annotation and manual-pair examples.

### Compact ChatGPT package

A small Markdown file containing selected bilingual pairs, ignored metadata examples, table examples, layout rules, and general notes.

## Import and restore

1. Open the annotation workspace.
2. Click **Import JSON** and choose a previously exported complete annotation JSON.
3. Open the matching PDF.
4. The annotations and highlights will appear on their saved pages.

Imported annotations can be edited and exported again.

## Browser notes

- Text selection depends on the PDF containing a usable text layer.
- Scanned PDFs without embedded text need OCR before text selection can work.
- Rectangle selection still records an area on scanned PDFs, but selected text may be blank unless OCR text exists.
- Chrome, Edge, and recent Firefox versions are recommended.

## Folder structure

```text
annotation_workspace/
  index.html
  app.js
  style.css
  server.py
  requirements.txt
  README.md
  pdfs/
  exports/
```

Downloads are generated in the browser and normally go to the browser's Downloads folder. The `exports/` folder is provided for manually organizing exported files.
