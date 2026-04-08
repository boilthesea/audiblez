import customtkinter as ctk
import threading
import numpy as np
import soundfile
import subprocess
from tempfile import NamedTemporaryFile
from audiblez.ctk.constants import PREVIEW_LIMIT

class PreviewPanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.preview_top = ctk.CTkFrame(self, fg_color="transparent")
        self.preview_top.grid(row=0, column=0, sticky="ew", padx=10, pady=5)

        self.chapter_title_label = ctk.CTkLabel(self.preview_top, text="No Chapter Selected", font=("Inter", 12, "italic"))
        self.chapter_title_label.pack(side="left")

        self.preview_audio_btn = ctk.CTkButton(self.preview_top, text="🔊 Audio Preview", width=120, command=self.on_audio_preview)
        self.preview_audio_btn.pack(side="right")

        self.text_area = ctk.CTkTextbox(self, font=("Courier New", 14))
        self.text_area.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

        self.preview_threads = []

    def set_chapter(self, chapter):
        self.chapter_title_label.configure(text=chapter.get('title', 'Untitled'))
        self.text_area.delete("1.0", "end")
        self.text_area.insert("1.0", chapter.get('extracted_text', ''))

    def on_audio_preview(self):
        text = self.text_area.get("1.0", f"1.0 + {PREVIEW_LIMIT}c")
        if not text.strip():
            return

        self.preview_audio_btn.configure(text="⏳", state="disabled")

        def generate_preview():
            try:
                import audiblez.core as core
                import audiblez.engines as engines
                
                # Get settings from controller/params
                voice_data = self.controller.params.voice_var.get().split(' ')
                # Handle potential flag in first index
                voice = " ".join(voice_data[1:]) if len(voice_data) > 1 else voice_data[0]
                
                engine_device = self.controller.params.engine_var.get()
                tts_model = self.controller.params.model_var.get()
                ref_wav = self.controller.params.ref_wav_var.get()
                steps = int(self.controller.params.steps_var.get() or 4)
                chunk_len = int(self.controller.params.chunk_var.get() or 900)
                
                # Use get_effective_seed to handle random vs locked
                effective_seed = self.controller.params.get_effective_seed()
                
                # LuxTTS specifically uses lux_speed slider
                if tts_model == 'luxtts':
                    speed = float(self.controller.params.lux_speed_var.get())
                else:
                    speed = float(self.controller.params.speed_var.get() or 1.0)

                active_engine = engines.get_engine(tts_model, engine_device)
                core.load_spacy()
                
                engine_kwargs = {
                    'voice': voice,
                    'speed': speed,
                    'reference_wav': ref_wav,
                    'num_steps': steps,
                    'max_chunk_len': chunk_len,
                    'guidance_scale': float(self.controller.params.guidance_var.get()),
                    't_shift': float(self.controller.params.t_shift_var.get()),
                    'rms': float(self.controller.params.rms_var.get()),
                    'duration': float(self.controller.params.duration_var.get()),
                    'return_smooth': self.controller.params.smooth_var.get(),
                    'seed': effective_seed
                }
                
                audio_data, current_sample_rate = active_engine.generate(text, **engine_kwargs)
                
                if audio_data.size > 0:
                    with NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                        soundfile.write(tmp.name, audio_data, current_sample_rate)
                        subprocess.run(['ffplay', '-autoexit', '-nodisp', tmp.name])
            except Exception as e:
                print(f"Preview error: {e}")
            finally:
                self.preview_audio_btn.configure(text="🔊 Audio Preview", state="normal")

        thread = threading.Thread(target=generate_preview, daemon=True)
        thread.start()
        self.preview_threads.append(thread)
