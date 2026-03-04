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
                from kokoro import KPipeline
                
                # Get settings from controller/params
                voice_data = self.controller.params.voice_var.get().split(' ')
                # Handle potential flag in first index
                voice = " ".join(voice_data[1:]) if len(voice_data) > 1 else voice_data[0]
                
                speed = float(self.controller.params.speed_var.get())
                engine = self.controller.params.engine_var.get()
                
                pipeline = KPipeline(lang_code=voice[0], device=engine) 
                core.load_spacy()
                
                audio_segments = core.gen_audio_segments(pipeline, text, voice=voice, speed=speed)
                if not audio_segments:
                    return
                
                final_audio = np.concatenate(audio_segments)
                with NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                    soundfile.write(tmp.name, final_audio, core.sample_rate)
                    subprocess.run(['ffplay', '-autoexit', '-nodisp', tmp.name])
            except Exception as e:
                print(f"Preview error: {e}")
            finally:
                self.preview_audio_btn.configure(text="🔊 Audio Preview", state="normal")

        thread = threading.Thread(target=generate_preview, daemon=True)
        thread.start()
        self.preview_threads.append(thread)
