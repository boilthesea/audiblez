from .kokoro_engine import KokoroEngine

def get_engine(model_name: str, device: str):
    if model_name.lower() == 'kokoro':
        return KokoroEngine(device)
    elif model_name.lower() == 'luxtts':
        from .luxtts_engine import LuxTTSEngine
        return LuxTTSEngine(device)
    else:
        raise ValueError(f"Unknown engine: {model_name}")
