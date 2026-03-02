# Qwen3-TTS Integration Plan

This document details the integration of `Qwen3-TTS` into `Audiblez`, providing high-quality, customizable speech synthesis with voice cloning support.

## Architecture Overview

To maintain clean code in `core.py`, the TTS engines will be decoupled.

1.  **Engine Interface**: A common interface for TTS engines (e.g., `TTSEngine` abstract class or a simple dispatch mechanism).
2.  **Kokoro Engine**: Moved or encapsulated as a standard engine.
3.  **Qwen3 Engine**: New engine implementation in `audiblez/engines/qwen3.py`.
4.  **Audiobook Chapter Generator**: Updated to call the selected engine.

## Qwen3-TTS Features

### 1. Model Selection

Support for two base models:

- **0.6b**: Faster, less resource-intensive.
- **1.7b**: Higher quality, requires more VRAM/compute.

### 2. Voice Cloning

- Users select a `.wav` file as a reference sample.
- The engine uses this sample to clone the voice for the entire audiobook.

### 3. Seed Management

- **Random by Default**: New seed generated for each preview/chapter if not specified.
- **Retain Seed**: After a preview, the user can choose to lock that specific seed for the full audiobook generation to ensure consistent output.

### 4. Smart Chunking

- Uses `spaCy` (already a dependency).
- **Strategy**: Accumulate full sentences until the character limit (50-500) is reached. If a single sentence exceeds the limit, it may be split or handled as a single large chunk depending on model constraints.

## UI Changes

### Audiobook Parameters Refactor

- **Engine Selector**: Radio buttons or Dropdown to switch between "Kokoro" and "Qwen3-TTS".
- **Dynamic Configuration**:
  - **Kokoro Mode**: Shows the existing Voice dropdown and Speed.
  - **Qwen3 Mode**:
    - Model selection (.6b/.17b).
    - Reference Voice (.wav file picker).
    - Seed field (Hex/Int input + "Randomize" checkbox).
    - Last Preview Seed display + "Use this seed" button.
- **Chunking Section**:
  - Slider or Spinner for Max Chunk Length (50-500).

## Persistence

All new settings will be stored in the existing database via `audiblez.database`:

- `tts_engine_type`
- `qwen3_model_size`
- `qwen3_voice_sample_path`
- `qwen3_seed`
- `chunk_length_limit`

## Implementation Steps

1.  **Engine Refactoring**:
    - Extract `KPipeline` logic into a Kokoro-specific module.
    - Create `Qwen3Engine` module.
2.  **Chunking Logic**:
    - Implement the sentence-aware chunking function.
3.  **UI Updates**:
    - Implement conditional rendering of parameter panels.
    - Add voice sample file picker.
4.  **Integration**:
    - Connect UI events to engine parameters.
    - Update `core.main` to use the engine factory.
