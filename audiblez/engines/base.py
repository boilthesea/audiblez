import numpy as np

class BaseEngine:
    def __init__(self, device: str):
        self.device = device
    
    def generate(self, text: str, pause_event=None, stop_event=None, **kwargs) -> tuple[np.ndarray, int]:
        """Returns (audio_data, sample_rate)"""
        raise NotImplementedError
