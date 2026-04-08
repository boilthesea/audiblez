# Audiblez Project Blueprint

## Overview

Audiblez is a high-performance tool for converting electronic books (`.epub`) into high-quality audiobooks (`.m4b` or `.wav`). It leverages the **Kokoro-82M** TTS model for natural-sounding synthesis and supports both a command-line interface (CLI) and a graphical user interface (GUI).

This project is a fork optimized for Windows environments, specifically requiring **Python 3.12** and **CUDA** support for GPU-accelerated speech generation.

## Architecture

The application follows a modular "Engine" pattern, allowing different TTS backends to be swapped or added easily.

### Core Flow

1. **Extraction**: `calibre_handler.py` or `core.py` extracts text from EPUB chapters.
2. **Persistence**: `database.py` manages the state of books being processed (staging) and configuration.
3. **Processing**: `core.py` coordinates the generation loop, passing text chunks to the selected engine.
4. **Synthesis**: Engines in `audiblez/engines/` interact with AI models (Kokoro now, Qwen3 later) to produce audio segments.
5. **Assembly**: `ffmpeg` is used to concatenate segments into chapters and finally into a metadata-rich `.m4b` file.

## File Responsibilities (`audiblez/`)

### Management & Entry Points

- **[cli.py](../audiblez/cli.py)**: Entry point for the Command Line Interface. Handles argument parsing and execution flow.
- **[ui.py](../audiblez/ui.py)**: Modern **CustomTkinter** GUI entry point. Now the primary interface.
- **[ctk/](../audiblez/ctk/)**: Modular components for the modern UI (tabs, panels, custom widgets).
- **[database.py](../audiblez/database.py)**: SQLite integration. Enhanced to support isolated settings for different UIs (`ui_name` key) and persistent output folders.

### Synthesis & Logic

- **[core.py](../audiblez/core.py)**: The central logic hub. Manages the conversion lifecycle, chapter discovery, and final file assembly via FFmpeg.
- **[engines/](../audiblez/engines/)**: Modular TTS drivers. [TODO]
  - `base.py`: Abstract base class for all engines. [TODO]
  - `kokoro_engine.py`: Default high-speed engine. Includes CPU/CUDA device selection. [TODO]
  - `qwen3_engine.py`: Support for advanced LLM-based TTS. [TODO]
  - `luxtts_engine.py`: Support for LuxTTS (next on the list). [TODO]
- **[voices.py](../audiblez/voices.py)**: Configuration and list of supported TTS voices across different languages.

### Utilities

- **[calibre_handler.py](../audiblez/calibre_handler.py)**: Optimized logic for parsing EPUBs. Now includes three experimental methods: Standard (ebooklib), Zip-direct, and Calibre-only (conversion).
- **[text_utils.py](../audiblez/text_utils.py)**: Helpers for text normalization and sentence-level chunking.
- **[inspector.py](../audiblez/inspector.py)**: Debugging tool for analyzing EPUB structure and metadata.

## Development Reference

### Environment [under construction]

- **Python Version**: 3.12 (Strictly recommended for compatibility with specific Windows wheels).
- **Package Manager**: `uv` is preferred.
- **Install Method**: Editable install (`uv pip install -e .`) ensures code changes are immediately reflected in the environment.

### External Dependencies

- **FFmpeg**: Required for audio concatenation and M4B encoding.
- **espeak-ng**: Required by Kokoro for phoneme generation.
- **CUDA**: 12.x recommended for GPU acceleration.

## Task & Planning

New features or major refactors should be documented in the **[plans/](./)** directory to maintain architectural clarity.
