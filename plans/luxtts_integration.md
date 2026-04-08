# LuxTTS Integration Plan

This document details the modular refactoring of the TTS engine architecture in `Audiblez` to support **LuxTTS** (via the `zipvoice` library) alongside the existing **Kokoro** engine.

## Overview
The goal is to implement a non-disruptive "Modular Engine" system, as originally envisioned in the project's blueprint. This allows for easy swapping between different TTS backends (Kokoro, LuxTTS, and potentially others like Qwen3 later).

## Architecture: The "Modular Engine" Pattern

### 1. New Directory Structure
We will populate the (currently empty) `audiblez/engines/` directory:
- `audiblez/engines/base.py`: Defines the `BaseEngine` abstract class.
- `audiblez/engines/kokoro_engine.py`: Port the existing Kokoro logic here.
- `audiblez/engines/luxtts_engine.py`: Implement LuxTTS support using the `zipvoice` library.
- `audiblez/engines/__init__.py`: Provides a factory mechanism to instantiate the selected engine.

### 2. Engine Interface (`base.py`)
```python
import numpy as np

class BaseEngine:
    def __init__(self, device: str):
        self.device = device
    
    def generate(self, text: str, **kwargs) -> tuple[np.ndarray, int]:
        """Returns (audio_data, sample_rate)"""
        raise NotImplementedError
```

### 3. LuxTTS Specifics (`luxtts_engine.py`)
- **Sample Rate:** 48,000 Hz (Standard) or 24,000 Hz (if smoothing is enabled).
- **Inference:** Uses `zipvoice.luxvoice.LuxTTS`.
- **Chunking:** Implements a "greedy" sentence-aware joiner to maximize context within the 100-999 character limit.
- **Voice Cloning:** Requires a path to a reference `.wav` file (stored in `database.py`).

## LuxTTS Parameter Reference
Based on source code analysis and external documentation for ZipVoice/LuxTTS:

- **Speed (0.5 to 2.0, Default 1.0):** Controls pacing. Higher values are faster. (Internal multiplier of 1.3 is applied by the library).
- **Guidance Scale (1.0 to 10.0, Default 3.0):** Classifier-Free Guidance. Higher values force the model to adhere more strictly to the style/prosody of the reference prompt.
- **T-Shift (0.0 to 2.0, Default 0.5):** Adjusts timbre/pitch via the time schedule. 
    - Values < 1.0: Deeper, more masculine tone.
    - Values > 1.0: Higher, brighter, more feminine tone.
- **Target RMS (0.0 to 2.0, Default 0.1):** Volume normalization level for the output.
- **Prompt Duration (1 to 15s, Default 5s):** The length of the reference audio segment used for the clone. 3-5s is usually optimal.
- **Return Smooth (Boolean, Default False):** If enabled, applies vocos smoothing to reduce waveform roughness. **Note:** This reduces output sample rate to 24kHz.
- **Seed (Integer):** Controls the randomness of the flow matching. Fixed seeds provide deterministic output.

## Phased Development Plan

### Phase 1: Engine Abstraction & Database Prep (Completed)
- Create `audiblez/engines/` directory structure.
- Extract Kokoro-specific logic from `core.py` into `kokoro_engine.py`.
- **Database Update (`database.py`):** Added `tts_model`, `luxtts_reference_wav`, `luxtts_num_steps`, `luxtts_max_chunk_len`.

### Phase 2: LuxTTS Engine Implementation (Completed)
- Implement `LuxTTSEngine` in `luxtts_engine.py`.
- Implement sentence-aware chunking.

### Phase 3: Core Refactor (Completed)
- Refactor `audiblez/core.py` to use an engine factory.
- Update `gen_audio_segments` logic into engines.

### Phase 4: UI Integration (Completed)
- Update `audiblez/ctk/panels/params.py` with Model selection and LuxTTS basic fields.

### Phase 5: Verification (In Progress)
- Regression testing for Kokoro.
- Quality check for LuxTTS.

### Phase 6: Advanced Parameters & UI Enhancements
- **Database:** Add columns for all advanced LuxTTS parameters.
- **Engine:** Update `LuxTTSEngine.generate()` to accept and apply:
    - Guidance Scale, T-Shift, dynamic Speed, Target RMS, Prompt Duration, Return Smooth.
    - Global seed management via `torch.manual_seed()`.
- **UI (`ParamsPanel`):**
    - Replace basic entries with `CTkSlider` for continuous ranges (Guidance, T-Shift, Speed, RMS, Duration).
    - Add "Vocos Smoothing" checkbox.
    - Implement **Seed Lock Logic**:
        - Entry field + Toggle button (🔓/🔒).
        - If unlocked: "Audio Preview" generates random seed, updates UI, and uses it.
        - If locked: Use the UI's seed value for all synthesis.
- **Preview Integration:** Update `PreviewPanel` to communicate with the `ParamsPanel` for seed updates.
- **CLI:** Add command line flags for all new parameters.
