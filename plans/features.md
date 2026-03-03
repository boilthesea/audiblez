# Preserved Features for CustomTkinter UI

This document lists all features from the existing `wxPython` UI (`ui.py`) that must be preserved in the new `customtkinter` implementation.

## 1. File Handling & Extraction

- **EPUB Support**: Open and parse EPUB files.
- **Calibre Integration**: "Open with Calibre" button for specialized parsing.
- **Multiple Parsing Methods**:
  - Ebooklib
  - Zip Extraction
  - Calibre Only
- **Experimental Support**: Placeholders for Markdown, TXT, and PDF.

## 2. Chapter Management

- **Chapter List**: Display chapters with checkboxes for selection.
- **Text Preview**: View and edit extracted text for the selected chapter.
- **Audio Preview**: Generate and play a short audio snippet (first 300 characters) of the selected chapter using current synthesis settings.
- **Status Indicators**: Show current processing status for each chapter (Pending, In Progress, Done, Error).

## 3. Book Metadata

- **Details Display**: Show Title, Author, and Total Character Length.
- **Cover Art**: Display the book's cover image.
- **Debugging**: "Debug Structure" button for analyzing EPUB internals.

## 4. Audiobook Synthesis Parameters

- **Engine Selection**: Toggle between CPU and CUDA (GPU) acceleration.
- **Voice Selection**: Dropdown menu featuring all supported voices with flag icons.
- **Speech Speed**: Adjustable speed multiplier (float).
- **Custom Rate**: Experimental rate setting (chars/sec).
- **M4B Assembly**: Toggle between "Original" and "Extra Crispy" assembly methods.
- **Output Folder**: Persistent selection of the destination directory.

## 5. Staging & Workflow

- **Staging Tab**: Manage multiple books before adding them to the synthesis queue.
- **Chapter Selection**: Refined selection of specific chapters for each staged book.

## 6. Queue & Scheduling

- **Queue Tab**: Batch processing of multiple books.
- **Execution**: Run queue items sequentially.
- **Scheduling**: Ability to schedule queue execution for a later time.

## 7. Configuration & State

- **Settings Persistence**: Database-driven storage of all parameters (engine, voice, speed, etc.).
- **Window Geometry**: Remember and restore window size and position.
- **Dark Mode**: Native dark mode support (required only for the new UI).

## 8. User Feedback

- **Progress Tracking**: Real-time progress bar and synthesis percentage.
- **ETA Information**: Estimated time remaining for the current synthesis.
- **About Dialog**: Project information and contributor credits.
