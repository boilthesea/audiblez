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
        self.chapter_vars = []
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Controls
        self.controls = ctk.CTkFrame(self)
        self.controls.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        
        self.select_all_btn = ctk.CTkButton(self.controls, text="Select All", width=100, command=self.select_all)
        self.select_all_btn.pack(side="left", padx=5, pady=5)
        
        self.select_none_btn = ctk.CTkButton(self.controls, text="Select None", width=100, command=self.select_none)
        self.select_none_btn.pack(side="left", padx=5, pady=5)

        self.queue_btn = ctk.CTkButton(self.controls, text="➕ Add to Queue", width=120, fg_color="green", hover_color="darkgreen", command=self.on_queue)
        self.queue_btn.pack(side="right", padx=5, pady=5)

        # Chapters List (Scrollable)
        self.scrollable_frame = ctk.CTkScrollableFrame(self, label_text="Book Chapters")
        self.scrollable_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.scrollable_frame.grid_columnconfigure(0, weight=1)

    def load_chapters(self, chapters):
        # Clear existing
        for child in self.scrollable_frame.winfo_children():
            child.destroy()
        self.chapter_vars = []

        for i, chapter in enumerate(chapters):
            var = ctk.BooleanVar(value=chapter.get('is_selected', True))
            self.chapter_vars.append(var)
            
            frame = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
            frame.grid(row=i, column=0, sticky="ew", pady=2)
            frame.grid_columnconfigure(1, weight=1)

            cb = ctk.CTkCheckBox(frame, text="", variable=var, width=20, command=self.controller.update_stats)
            cb.grid(row=0, column=0, padx=(5, 0))
            
            btn = ctk.CTkButton(frame, text=chapter.get('title', f'Chapter {i+1}'), 
                                anchor="w", fg_color="transparent", text_color=("gray10", "gray90"),
                                hover_color=("gray70", "gray30"),
                                command=lambda c=chapter: self.controller.on_chapter_selected(c))
            btn.grid(row=0, column=1, sticky="ew")
            
            len_label = ctk.CTkLabel(frame, text=f"{len(chapter.get('extracted_text', '')):,} chars", font=("Inter", 10))
            len_label.grid(row=0, column=2, padx=10)

        self.controller.update_stats()
        # Ensure scroll bindings are applied to new children
        if hasattr(self.controller, "_bind_mouse_wheel_recursive"):
            self.controller._bind_mouse_wheel_recursive(self.scrollable_frame, self.scrollable_frame)

    def select_all(self):
        for v in self.chapter_vars:
            v.set(True)
        self.controller.update_stats()
        # Ensure scroll bindings are applied to new children
        if hasattr(self.controller, "_bind_mouse_wheel_recursive"):
            self.controller._bind_mouse_wheel_recursive(self.scrollable_frame, self.scrollable_frame)

    def select_none(self):
        for v in self.chapter_vars:
            v.set(False)
        self.controller.update_stats()
        # Ensure scroll bindings are applied to new children
        if hasattr(self.controller, "_bind_mouse_wheel_recursive"):
            self.controller._bind_mouse_wheel_recursive(self.scrollable_frame, self.scrollable_frame)

    def on_queue(self):
        if not hasattr(self.controller, 'current_book'):
            return

        selected_chapters = []
        for i, chapter in enumerate(self.controller.current_book['chapters']):
            if self.chapter_vars[i].get():
                # We only need title and order for the queue item, text will be fetched if needed
                selected_chapters.append({
                    'staged_chapter_id': chapter.get('id'),
                    'title': chapter.get('title'),
                    'order': i,
                    'text_content': chapter.get('extracted_text')
                })

        if not selected_chapters:
            print("No chapters selected.")
            return

        voice = self.controller.params.voice_var.get()
        speed = self.controller.params.speed_var.get()
        engine = self.controller.params.engine_var.get()
        output_folder = self.controller.params.output_path.get() or "."
        m4b_method = self.controller.params.m4b_var.get()

        synthesis_settings = {
            'engine': engine,
            'voice': voice,
            'speed': speed,
            'output_folder': output_folder,
            'm4b_assembly_method': m4b_method,
            'tts_model': self.controller.params.model_var.get(),
            'luxtts_reference_wav': self.controller.params.ref_wav_var.get(),
            'luxtts_num_steps': int(self.controller.params.steps_var.get() or 4),
            'luxtts_max_chunk_len': int(self.controller.params.chunk_var.get() or 900),
            'luxtts_guidance': float(self.controller.params.guidance_var.get()),
            'luxtts_t_shift': float(self.controller.params.t_shift_var.get()),
            'luxtts_speed': float(self.controller.params.lux_speed_var.get()),
            'luxtts_rms': float(self.controller.params.rms_var.get()),
            'luxtts_duration': float(self.controller.params.duration_var.get()),
            'luxtts_smooth': self.controller.params.smooth_var.get(),
            'luxtts_seed': int(self.controller.params.seed_var.get() or 0) if self.controller.params.seed_locked_var.get() else None,
            'custom_rate': self.controller.params.rate_var.get()
        }

        details = {
            'staged_book_id': self.controller.current_book.get('id'),
            'book_title': self.controller.current_book.get('title'),
            'source_path': self.controller.selected_file_path,
            'synthesis_settings': synthesis_settings,
            'chapters': selected_chapters
        }

        import audiblez.database as db
        queue_id = db.add_item_to_queue(details)
        if queue_id:
            print(f"Added to queue with ID: {queue_id}")
            self.controller.queue_tab.refresh_queue()
            # Switch to Queue tab
            if hasattr(self.controller, 'tab_view'):
                self.controller.tab_view.set("Queue")
        else:
            print("Failed to add to queue.")
