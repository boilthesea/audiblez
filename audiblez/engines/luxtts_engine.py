from .base import BaseEngine
import numpy as np
import torch
import spacy
import os

class LuxTTSEngine(BaseEngine):
    def __init__(self, device: str):
        super().__init__(device)
        try:
            from zipvoice.luxvoice import LuxTTS
        except ImportError:
            raise ImportError("LuxTTS dependencies not found. Please install zipvoice: pip install git+https://github.com/ysharma3501/LuxTTS")
        
        self.lux_tts = LuxTTS('YatharthS/LuxTTS', device=self.device)
        self.nlp = spacy.load('xx_ent_wiki_sm')
        if 'sentencizer' not in self.nlp.pipe_names:
            self.nlp.add_pipe('sentencizer')
        
        self._current_ref_wav = None
        self._encoded_prompt = None

    def _get_encoded_prompt(self, reference_wav: str):
        if reference_wav != self._current_ref_wav:
            if not os.path.exists(reference_wav):
                raise FileNotFoundError(f"Reference WAV not found: {reference_wav}")
            self._encoded_prompt = self.lux_tts.encode_prompt(reference_wav)
            self._current_ref_wav = reference_wav
        return self._encoded_prompt

    def generate(self, text: str, **kwargs) -> tuple[np.ndarray, int]:
        """
        Generates audio using LuxTTS with voice cloning.
        Expected kwargs: reference_wav, num_steps
        """
        reference_wav = kwargs.get('reference_wav')
        if not reference_wav:
            raise ValueError("LuxTTS requires a reference_wav for voice cloning.")
        
        num_steps = kwargs.get('num_steps', 4)
        max_chunk_len = kwargs.get('max_chunk_len', 900)
        encoded_prompt = self._get_encoded_prompt(reference_wav)
        
        # Chunking: Greedy sentence-aware approach using user-defined max_chunk_len.
        doc = self.nlp(text)
        sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
        
        chunks = []
        current_chunk = ""
        
        for sent in sentences:
            if len(current_chunk) + len(sent) + 1 < max_chunk_len:
                if current_chunk:
                    current_chunk += " " + sent
                else:
                    current_chunk = sent
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sent
        
        if current_chunk:
            chunks.append(current_chunk)
            
        # LuxTTS might fail if a chunk is too short (< 100 chars)?
        # The prompt says 100-999. Let's ensure minimum length if possible,
        # or just rely on the model handling it if it's the last bit of text.
        
        all_audio = []
        for chunk in chunks:
            # Padding if too short? 
            # LuxTTS docs say 100-999. If it's < 100, we might need to pad with spaces.
            if len(chunk) < 100:
                chunk = chunk.ljust(100)
                
            wav_tensor = self.lux_tts.generate_speech(chunk, encoded_prompt, num_steps=num_steps)
            wav_data = wav_tensor.squeeze().cpu().numpy()
            all_audio.append(wav_data)
            
        if not all_audio:
            return np.array([]), 48000
            
        return np.concatenate(all_audio), 48000
