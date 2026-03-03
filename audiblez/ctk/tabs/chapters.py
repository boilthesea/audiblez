import customtkinter as ctk
import threading
import numpy as np
import soundfile
import subprocess
from tempfile import NamedTemporaryFile
from audiblez.ctk.constants import PREVIEW_LIMIT

class ChaptersTab(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        # Left: Chapter List
        self.list_frame = ctk.CTkFrame(self)
        self.list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.list_frame.grid_rowconfigure(2, weight=1)
        self.list_frame.grid_columnconfigure(0, weight=1)

        self.list_label = ctk.CTkLabel(self.list_frame, text="Chapters", font=("Inter", 14, "bold"))
        self.list_label.grid(row=0, column=0, sticky="nw", padx=10, pady=5)

        # Parser selection - matching legacy UX
        self.parser_frame = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.parser_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 5))
        
        ctk.CTkLabel(self.parser_frame, text="Parsing Method:", font=("Inter", 11)).pack(side="left", padx=(0, 5))
        
        self.parser_switch = ctk.CTkSegmentedButton(
            self.parser_frame, 
            values=["Standard", "Zip", "Calibre Only"],
            command=self.on_parser_change
        )
        # Map current_parsing_method (1,2,3) to values
        initial_val = "Standard"
        if self.controller.current_parsing_method == 2: initial_val = "Zip"
        if self.controller.current_parsing_method == 3: initial_val = "Calibre Only"
        self.parser_switch.set(initial_val)
        self.parser_switch.pack(side="left", fill="x", expand=True)

        self.scroll_header = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.scroll_header.grid(row=2, column=0, sticky="ew", padx=10)
        self.scroll_header.columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.scroll_header, text="Inc.", font=("Inter", 11, "bold"), width=40).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(self.scroll_header, text="Chapter Name", font=("Inter", 11, "bold")).grid(row=0, column=1, sticky="w", padx=10)
        ctk.CTkLabel(self.scroll_header, text="Length", font=("Inter", 11, "bold"), width=80).grid(row=0, column=2, sticky="e")

        self.scroll_frame = ctk.CTkScrollableFrame(self.list_frame)
        self.scroll_frame.grid(row=3, column=0, sticky="nsew", padx=5, pady=(0, 5))
        self.list_frame.grid_rowconfigure(3, weight=1)

        # Right: Text Preview & Edit
        self.preview_frame = ctk.CTkFrame(self)
        self.preview_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.preview_frame.grid_rowconfigure(1, weight=1)
        self.preview_frame.grid_columnconfigure(0, weight=1)

        self.preview_top = ctk.CTkFrame(self.preview_frame, fg_color="transparent")
        self.preview_top.grid(row=0, column=0, sticky="ew", padx=10, pady=5)

        self.chapter_title_label = ctk.CTkLabel(self.preview_top, text="No Chapter Selected", font=("Inter", 12, "italic"))
        self.chapter_title_label.pack(side="left")

        self.preview_audio_btn = ctk.CTkButton(self.preview_top, text="🔊 Audio Preview", width=120, command=self.on_audio_preview)
        self.preview_audio_btn.pack(side="right")

        self.text_area = ctk.CTkTextbox(self.preview_frame, font=("Courier New", 14))
        self.text_area.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

        self.staging_btn = ctk.CTkButton(self.preview_frame, text="📥 Stage Book for Batching", command=self.on_stage)
        self.staging_btn.grid(row=2, column=0, sticky="ew", padx=10, pady=10)

        self.preview_threads = []

    def on_parser_change(self, value):
        mapping = {"Standard": 1, "Zip": 2, "Calibre Only": 3}
        self.controller.current_parsing_method = mapping.get(value, 1)
        print(f"Parsing method changed to: {value} ({self.controller.current_parsing_method})")

    def load_chapters(self, chapters):
        self.chapters = chapters
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        self.chapter_vars = []
        for i, chapter in enumerate(chapters):
            var = ctk.BooleanVar(value=chapter.get('is_selected', True))
            self.chapter_vars.append(var)
            
            # Row frame
            row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            row.pack(fill="x", padx=5, pady=1)
            row.columnconfigure(1, weight=1)
            
            cb_container = ctk.CTkFrame(row, fg_color="transparent", width=40)
            cb_container.grid(row=0, column=0, sticky="w")
            cb_container.grid_propagate(False)
            
            cb = ctk.CTkCheckBox(cb_container, text="", variable=var, width=20, command=self.on_toggle_selection)
            cb.place(relx=0.5, rely=0.5, anchor="center")
            
            title = chapter.get('title', f"Chapter {i+1}")
            text_len = len(chapter.get('extracted_text', ''))
            
            name_btn = ctk.CTkButton(
                row, 
                text=title, 
                fg_color="transparent", 
                text_color=("gray10", "gray90"),
                anchor="w", 
                hover_color=("gray70", "gray30"),
                height=24,
                command=lambda c=chapter: self.on_chapter_select(c)
            )
            name_btn.grid(row=0, column=1, sticky="ew", padx=(5, 10))
            
            len_label = ctk.CTkLabel(row, text=f"{text_len:,}", font=("Inter", 11), width=80, anchor="e")
            len_label.grid(row=0, column=2, sticky="e", padx=(0, 5))

        if chapters:
            self.on_chapter_select(chapters[0])
        
        self.on_toggle_selection()

    def on_toggle_selection(self):
        # Update app-level selection total if it exists
        if hasattr(self.controller, 'update_stats'):
            self.controller.update_stats()


    def on_chapter_select(self, chapter):
        self.selected_chapter = chapter
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
                voice_tuple = self.controller.params.voice_var.get().split(' ')[1:] # Remove flag
                voice = " ".join(voice_tuple)
                speed = float(self.controller.params.speed_var.get())
                engine = self.controller.params.engine_var.get()
                
                pipeline = KPipeline(lang_code=voice[0], device=engine) # Rough mapping
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

        thread = threading.Thread(target=generate_preview)
        thread.start()
        self.preview_threads.append(thread)

    def on_stage(self):
        if not hasattr(self.controller, 'current_book'):
            print("No book loaded.")
            return

        import audiblez.database as db
        book = self.controller.current_book
        
        # Filter selected chapters
        selected_chapters = []
        for i, chap in enumerate(self.chapters):
            if self.chapter_vars[i].get():
                selected_chapters.append(chap)
        
        if not selected_chapters:
            print("No chapters selected.")
            return

        db.add_staged_book(
            title=book['title'],
            author=book['author'],
            source_path="N/A", # Path needs to be tracked properly if needed
            output_folder=self.controller.params.output_path.get() or ".",
            chapters=selected_chapters
        )
        print(f"Staged: {book['title']}")
        self.controller.staging_tab.refresh_staging()
