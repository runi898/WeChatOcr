# OCR Copy Cleanup Design

**Date:** 2026-03-15
**Branch:** `feature/ocr-copy-v24`

## Goal

Improve screenshot-to-text copy quality by reusing a shared WeChat OCR post-processing pipeline, remove the center hint text from all screenshot overlays, and package a new `v24` executable into `dist/`.

## Scope

- Extract OCR line grouping and text assembly into a reusable helper module.
- Route both copy-text and translate flows through the same helper so they share ordering and merge behavior.
- Remove overlay hint text from all screenshot capture modes.
- Build `WeChatOCR_Tool_v24.exe` from a new spec file.

## Approach

1. Add a pure OCR post-processing module that:
   - normalizes raw OCR items
   - groups fragments into lines using vertical overlap and line-center heuristics
   - sorts fragments within a line by horizontal position
   - joins fragments with Chinese/English-aware spacing rules
2. Add unit tests around the helper before implementation.
3. Replace the inline merge logic in translation mode and the raw join logic in copy mode with the shared helper.
4. Remove the overlay hint `create_text(...)` call from capture UI.
5. Copy the latest spec to `WeChatOCR_Tool_v24.spec`, update the executable name, and build into `dist/`.

## Risks

- Over-aggressive line merging can collapse neighboring rows.
- English spacing rules can introduce extra spaces around punctuation.
- Packaging may fail if local PyInstaller environment diverges from earlier releases.

## Verification

- Unit tests for OCR post-processing.
- Existing translation layout tests.
- `py_compile` for touched Python files.
- `pyinstaller WeChatOCR_Tool_v24.spec` build output in `dist/`.
