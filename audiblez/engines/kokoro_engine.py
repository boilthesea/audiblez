from .base import BaseEngine
import numpy as np

class KokoroEngine(BaseEngine):
    def __init__(self, device: str):
        super().__init__(device)
        from kokoro import KPipeline
        self.pipeline = KPipeline(lang_code='a', device=self.device)
    
    def generate(self, text: str, **kwargs) -> tuple[np.ndarray, int]:
        """
        Generates audio using Kokoro-82M.
        Expected kwargs: voice, speed
        """
        voice = kwargs.get('voice', 'af_heart')
        speed = kwargs.get('speed', 1.0)
        
        generator = self.pipeline(text, voice=voice, speed=speed, split_pattern=None)
        
        all_audio = []
        for _, _, audio in generator:
            all_audio.append(audio)
            
        if not all_audio:
            return np.array([]), 24000
            
        return np.concatenate(all_audio), 24000
