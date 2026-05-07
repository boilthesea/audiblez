from .base import BaseEngine
import numpy as np

class KokoroEngine(BaseEngine):
    def __init__(self, device: str):
        super().__init__(device)
        from kokoro import KPipeline
        self.pipeline = KPipeline(lang_code='a', device=self.device)
    
    def generate(self, text: str, pause_event=None, stop_event=None, **kwargs) -> tuple[np.ndarray, int]:
        """
        Generates audio using Kokoro-82M.
        Expected kwargs: voice, speed
        """
        voice = kwargs.get('voice', 'af_heart')
        speed = kwargs.get('speed', 1.0)
        
        generator = self.pipeline(text, voice=voice, speed=speed, split_pattern=None)
        
        all_audio = []
        for _, _, audio in generator:
            if stop_event and stop_event.is_set():
                print("Synthesis stopped by user.")
                return np.array([]), 24000
            
            if pause_event and pause_event.is_set():
                print("Synthesis paused. Waiting...")
                while pause_event.is_set():
                    if stop_event and stop_event.is_set():
                        return np.array([]), 24000
                    pause_event.wait(0.1)
                print("Synthesis resumed.")

            all_audio.append(audio)
            
        if not all_audio:
            return np.array([]), 24000
            
        return np.concatenate(all_audio), 24000
