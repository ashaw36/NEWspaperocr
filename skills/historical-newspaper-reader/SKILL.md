---
name: historical-newspaper-reader
description: Use the historical newspaper OCR service to turn scanned Chinese newspapers into readable, historically faithful text and then answer research questions about the source.
---

# Historical Newspaper Reader

Use the local newspaper OCR service as the execution layer. The skill is the conversational orchestration layer: it decides how much to process, explains uncertainty, and presents the final historical text in normal prose.

## Operating rules

- Start with the current page or first page unless the user explicitly requests the whole document.
- Prefer the balanced workflow: layout review, user confirmation, visual transcription, semantic composition, then background local-OCR cross-check.
- Treat local OCR as a draft and quality signal, never as unquestionable source text.
- Preserve traditional characters, names, dates, historical wording and source order. Do not modernize silently.
- Keep three conceptual layers: raw OCR, visual draft, and final composed text. Never overwrite the raw layer with a correction.
- Surface low confidence, empty regions, conflicting readings and unresolved characters for human review.
- Let the user continue reading while later pages or background checks are still running.
- If a visual or language-model call fails, keep the local OCR result and say that the page is pending review; do not block export.

## Service workflow

Use the service endpoints configured by the host:

1. Create a task with `POST /api/tasks` using the source PDF or image.
2. Poll `GET /api/tasks/{task_id}` until the first page reaches `awaiting_layout_review`.
3. Present the proposed windows and ask for confirmation when the layout is ambiguous. Use `PUT /api/tasks/{task_id}/layout` for edits.
4. Start page-scoped recognition with `POST /api/tasks/{task_id}/ocr` and `page_numbers` containing the requested pages.
5. Read `GET /api/tasks/{task_id}/ocr`; show readable text as soon as a page completes.
6. Start semantic composition with `POST /api/tasks/{task_id}/correction`. Prefer the current page first.
7. Read `GET /api/tasks/{task_id}/correction` and present `corrected_text` as the final draft, with warnings and correction notes separated from the prose.
8. Use `POST /api/tasks/{task_id}/analysis` only when the user asks for summary, research analysis or a question. Render the returned fields as normal headings, paragraphs and lists rather than exposing raw JSON.
9. Offer `/api/tasks/{task_id}/export/corrected` for the composed historical text and `/api/tasks/{task_id}/export/raw` for the uncorrected transcription.

## Processing modes

- Fast preview: current page, visual draft first, no blocking background OCR.
- Balanced (default): current page first, visual draft plus local-OCR cross-check for low-confidence or conflicting regions.
- Archive: expand the layout to all pages, process pages incrementally, preserve page markers and export the completed document.

## Response style

Return the final newspaper text first. Then, when useful, include a short note describing pages processed, unresolved regions and whether the text is a draft or human-approved. For research analysis, separate source-stated facts from interpretation and list evidence page by page.
