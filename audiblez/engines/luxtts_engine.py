from .base import BaseEngine
import numpy as np
import torch
import spacy
import os
import random

class LuxTTSEngine(BaseEngine):
    def __init__(self, device: str):
        super().__init__(device)
        from zipvoice.luxvoice import LuxTTS
        self.lux_tts = LuxTTS('YatharthS/LuxTTS', device=self.device)
        self.nlp = spacy.load('xx_ent_wiki_sm')
        if 'sentencizer' not in self.nlp.pipe_names:
            self.nlp.add_pipe('sentencizer')
        
        self._current_ref_wav = None
        self._encoded_prompt = None
        self._current_duration = 5
        self._current_rms = 0.1

    def _get_encoded_prompt(self, reference_wav: str, duration: float = 5, rms: float = 0.1):
        # Re-encode if WAV path, duration or RMS changes
        if (reference_wav != self._current_ref_wav or 
            duration != self._current_duration or 
            rms != self._current_rms):
            
            if not os.path.exists(reference_wav):
                raise FileNotFoundError(f"Reference WAV not found: {reference_wav}")
            
            self._encoded_prompt = self.lux_tts.encode_prompt(reference_wav, duration=duration, rms=rms)
            self._current_ref_wav = reference_wav
            self._current_duration = duration
            self._current_rms = rms
            
        return self._encoded_prompt

    def generate(self, text: str, pause_event=None, stop_event=None, **kwargs) -> tuple[np.ndarray, int]:
        """
        Generates audio using LuxTTS with voice cloning.
        Expected kwargs: reference_wav, num_steps, guidance_scale, t_shift, speed, rms, duration, return_smooth, seed
        """
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        reference_wav = kwargs.get('reference_wav')
        if not reference_wav:
            raise ValueError("LuxTTS requires a reference_wav for voice cloning.")
        
        num_steps = kwargs.get('num_steps', 4)
        guidance_scale = kwargs.get('guidance_scale', 3.0)
        t_shift = kwargs.get('t_shift', 0.5)
        speed = kwargs.get('speed', 1.0)
        rms = kwargs.get('rms', 0.1)
        duration = kwargs.get('duration', 5.0)
        return_smooth = kwargs.get('return_smooth', False)
        seed = kwargs.get('seed')
        max_chunk_len = kwargs.get('max_chunk_len', 900)

        # Apply seed if provided
        if seed is not None:
            torch.manual_seed(seed)
            np.random.seed(seed)
            random.seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)

        encoded_prompt = self._get_encoded_prompt(reference_wav, duration=duration, rms=rms)
        
        # Chunking: Greedy sentence-aware approach
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
            
        all_audio = []
        for chunk in chunks:
            if stop_event and stop_event.is_set():
                print("Synthesis stopped by user.")
                return np.array([]), 48000
            
            if pause_event and pause_event.is_set():
                print("Synthesis paused. Waiting...")
                while pause_event.is_set():
                    if stop_event and stop_event.is_set():
                        return np.array([]), 48000
                    pause_event.wait(0.1)
                print("Synthesis resumed.")

            if len(chunk) < 100:
                chunk = chunk.ljust(100)
                
            wav_tensor = self.lux_tts.generate_speech(
                chunk, 
                encoded_prompt, 
                num_steps=num_steps,
                guidance_scale=guidance_scale,
                t_shift=t_shift,
                speed=speed,
                return_smooth=return_smooth
            )
            wav_data = wav_tensor.squeeze().cpu().numpy()
            all_audio.append(wav_data)
            
        if not all_audio:
            return np.array([]), 48000
            
        return np.concatenate(all_audio), 48000
