import customtkinter as ctk
import audiblez.database as db
import threading
import os
from audiblez.ctk.constants import *
from audiblez.ctk.tabs.chapters import ChaptersTab
from audiblez.ctk.tabs.staging import StagingTab
from audiblez.ctk.tabs.queue import QueueTab
from audiblez.ctk.panels.book_details import BookDetailsPanel
from audiblez.ctk.panels.params import ParamsPanel
from audiblez.ctk.panels.synthesis import SynthesisPanel
from audiblez.ctk.panels.preview import PreviewPanel

class AudiblezApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Load settings
        self.user_settings = db.load_all_user_settings()

        self.selected_file_path = None
        self.current_parsing_method = 1 # 1: Standard, 2: Zip, 3: Calibre
        self.failed_methods = set()
        
        # Queue state
        self.queue_running = False
        self.current_queue_item = None
        
        # Window configuration
        self.title(APP_NAME)
        self.geometry(self.user_settings.get('window_geometry', f"{DEFAULT_WIDTH}x{DEFAULT_HEIGHT}"))
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.bind("<Configure>", self.on_resize)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Create main layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Top Bar (Global actions)
        self.top_bar = ctk.CTkFrame(self, height=50, corner_radius=0)
        self.top_bar.grid(row=0, column=0, sticky="ew")

        self.open_btn = ctk.CTkButton(self.top_bar, text="📁 Open EPUB", command=self.on_open_epub)
        self.open_btn.pack(side="left", padx=5, pady=10)

        self.calibre_btn = ctk.CTkButton(self.top_bar, text="📖 Open with Calibre", command=self.on_open_with_calibre)
        self.calibre_btn.pack(side="left", padx=5, pady=10)

        self.about_btn = ctk.CTkButton(self.top_bar, text="ℹ️ About", width=80, command=self.on_about)
        self.about_btn.pack(side="right", padx=10, pady=10)

        # Main 3-Column Container
        self.main_container = ctk.CTkFrame(self, corner_radius=0)
        self.main_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        
        # Column 0: Metadata/Params (Left)
        # Column 1: Tabs (Middle)
        # Column 2: Preview (Right) - Expandable
        self.main_container.grid_columnconfigure(0, weight=0, minsize=350) 
        self.main_container.grid_columnconfigure(1, weight=0, minsize=400) 
        self.main_container.grid_columnconfigure(2, weight=1) 
        self.main_container.grid_rowconfigure(0, weight=1)

        # Column 0: Left Side Panels
        self.left_container = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.left_container.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.left_container.grid_rowconfigure(0, weight=0) # Details
        self.left_container.grid_rowconfigure(1, weight=0) # Params
        self.left_container.grid_rowconfigure(2, weight=0) # Synthesis
        self.left_container.grid_rowconfigure(3, weight=1) # Spacer

        self.book_details = BookDetailsPanel(self.left_container, self)
        self.book_details.grid(row=0, column=0, sticky="nsew", pady=(0, 5))

        self.params = ParamsPanel(self.left_container, self)
        self.params.grid(row=1, column=0, sticky="nsew", pady=5)

        self.synthesis = SynthesisPanel(self.left_container, self)
        self.synthesis.grid(row=2, column=0, sticky="new", pady=(5, 0))

        # Column 1: Middle Side (Notebook/Tabs)
        self.tab_container = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.tab_container.grid(row=0, column=1, sticky="nsew", padx=0)
        self.tab_container.grid_columnconfigure(0, weight=1)
        self.tab_container.grid_rowconfigure(0, weight=1)

        self.tab_view = ctk.CTkTabview(self.tab_container)
        self.tab_view.grid(row=0, column=0, sticky="nsew")
        
        self.chapters_tab = ChaptersTab(self.tab_view.add("Chapters"), self)
        self.chapters_tab.pack(expand=True, fill="both")
        
        self.staging_tab = StagingTab(self.tab_view.add("Staging"), self)
        self.staging_tab.pack(expand=True, fill="both")
        
        self.queue_tab = QueueTab(self.tab_view.add("Queue"), self)
        self.queue_tab.pack(expand=True, fill="both")

        # Column 2: Right Side (Preview)
        self.preview = PreviewPanel(self.main_container, self)
        self.preview.grid(row=0, column=2, sticky="nsew", padx=(10, 0))

        # Start background tasks
        self.after(5000, self.check_schedule)

    def on_open_epub(self):
        file_path = ctk.filedialog.askopenfilename(filetypes=[("EPUB Files", "*.epub")])
        if file_path:
            self.selected_file_path = file_path
            self.failed_methods = set()
            # Restore Stable Track (Pure Python)
            threading.Thread(target=self._load_book_file_threaded, args=(file_path,), kwargs={'method': 'pure'}, daemon=True).start()

    def _load_book_file_threaded(self, file_path, method=None):
        from audiblez.calibre_handler import open_book_experimental
        from audiblez.epub_handler import open_book_pure_python
        from pathlib import Path
        import traceback

        try:
            # Stable Track: Pure Python (Linux Friendly, No Calibre)
            if method == 'pure':
                print("Parser: Using Stable Pure Python (ebooklib + BeautifulSoup) for EPUB.")
                res_method, msg, chapters, metadata, cover_info = open_book_pure_python(
                    file_path, 
                    include_skeleton=False
                )
            # Experimental Track: Calibre Fallback System
            else:
                res_method, msg, chapters, metadata, cover_info = open_book_experimental(
                    file_path, 
                    ui_callback_for_path_selection=self._ask_user_for_calibre_path_generic,
                    method=method
                )

            if not chapters:
                print(f"Failed to load chapters: {msg}")
                if isinstance(method, int):
                    self.failed_methods.add(method)
                    self.after(0, self.book_details.refresh_reparse_buttons)
                return

            self.current_parsing_method = res_method

            # Normalize metadata handling
            def get_meta_field(field_name, default):
                val = metadata.get(field_name)
                if not val: return default
                if isinstance(val, list):
                    if isinstance(val[0], tuple): return val[0][0]
                    return val[0]
                return val

            title = get_meta_field('title', Path(file_path).stem)
            author = get_meta_field('creator', 'Unknown Author')
            
            # Deselect chapters with "gutenberg" in the title
            for chapter in chapters:
                if 'gutenberg' in chapter['title'].lower():
                    chapter['is_selected'] = False
                    print(f"Deselecting chapter '{chapter['title']}' due to 'gutenberg' in title.")

            # Update UI in main thread
            self.after(0, lambda: self._load_book_data_into_ui(
                title=title,
                author=author,
                chapters=chapters,
                cover=cover_info
            ))
            method_str = "Stable" if res_method == 1 and method == 'pure' else f"Experimental {res_method}"
            print(f"Loaded: {title} with {method_str} parser.")

        except Exception as e:
            print(f"Error loading book: {e}")
            traceback.print_exc()

    def on_open_with_calibre(self):
        file_path = ctk.filedialog.askopenfilename(filetypes=[("Ebook files", "*.epub;*.mobi;*.azw;*.azw3;*.fb2;*.lit;*.pdf"), ("All files", "*.*")])
        if file_path:
            self.selected_file_path = file_path
            self.failed_methods = set()
            # Use Experimental Track with Fallback Chain (method=None)
            threading.Thread(target=self._load_book_file_threaded, args=(file_path,), kwargs={'method': None}, daemon=True).start()


    def _ask_user_for_calibre_path_generic(self):
        print("Audiblez needs to know where Calibre is installed.")
        path = ctk.filedialog.askdirectory(title="Select Calibre Installation Directory (containing ebook-convert)")
        return path if path else None

    def _load_book_data_into_ui(self, title, author, chapters, cover):
        self.current_book = {
            'title': title,
            'author': author,
            'chapters': chapters
        }
        # Update Book Details
        total_chars = sum(len(c.get('extracted_text', '')) for c in chapters)
        self.book_details.update_book_info(title, author, total_chars, cover_data=cover)
        self.book_details.refresh_reparse_buttons()
        
        # Update Chapters Tab
        self.chapters_tab.load_chapters(chapters)
        
        print(f"UI Updated for: {title}")

    def on_chapter_selected(self, chapter):
        # Callback from ChaptersTab
        if hasattr(self, 'preview'):
            self.preview.set_chapter(chapter)

    def update_stats(self):
        if hasattr(self, 'current_book'):
            chapters = self.current_book['chapters']
            selected_len = sum(len(c.get('extracted_text', '')) for i, c in enumerate(chapters) if self.chapters_tab.chapter_vars[i].get())
            self.book_details.update_selection_total(selected_len)

    def start_synthesis(self):
        if not hasattr(self, 'current_book'):
            print("No book loaded.")
            return

        from audiblez.ctk.core_thread import CoreThread
        
        # Prepare parameters
        voice_data = self.params.voice_var.get().split(' ')
        # Handle potential flag in first index
        voice = " ".join(voice_data[1:]) if len(voice_data) > 1 else voice_data[0]
        
        # Map UI label back to internal value for M4B
        m4b_display = self.params.m4b_var.get()
        display_to_val = {"Original": "original", "Extra Crispy": "crispy"}
        m4b_val = display_to_val.get(m4b_display, "original")
        
        effective_seed = self.params.get_effective_seed()

        params = {
            'file_path': self.selected_file_path,
            'voice': voice,
            'pick_manually': False,
            'speed': float(self.params.lux_speed_var.get() if self.params.model_var.get() == 'luxtts' else self.params.speed_var.get() or 1.0),
            'engine_device': self.params.engine_var.get(),
            'output_folder': self.params.output_path.get() or ".",
            'selected_chapters': [c for i, c in enumerate(self.current_book['chapters']) if self.chapters_tab.chapter_vars[i].get()],
            'm4b_assembly_method': m4b_val,
            'custom_rate': self.params.rate_var.get(),
            'tts_model': self.params.model_var.get(),
            'reference_wav': self.params.ref_wav_var.get(),
            'num_steps': int(self.params.steps_var.get() or 4),
            'max_chunk_len': int(self.params.chunk_var.get() or 900),
            'guidance_scale': float(self.params.guidance_var.get()),
            't_shift': float(self.params.t_shift_var.get()),
            'rms': float(self.params.rms_var.get()),
            'duration': float(self.params.duration_var.get()),
            'return_smooth': self.params.smooth_var.get(),
            'seed': effective_seed
        }

        self.synth_thread = CoreThread(params, self.handle_core_event)
        self.synth_thread.start()

    def start_queue_processing(self):
        if self.queue_running:
            print("Queue already running.")
            return

        items = db.get_queued_items()
        pending_item = next((i for i in items if i['status'] == 'pending'), None)

        if pending_item:
            self.queue_running = True
            self.current_queue_item = pending_item
            db.update_queue_item_status(pending_item['id'], 'in_progress')
            self.after(0, self.queue_tab.refresh_queue)
            self._run_queue_item(pending_item)
        else:
            self.queue_running = False
            self.current_queue_item = None
            print("No pending items in queue.")

    def _run_queue_item(self, item):
        from audiblez.ctk.core_thread import CoreThread
        
        settings = item['synthesis_settings']
        
        # Ensure chapters have extracted_text (populate from staged if needed)
        selected_chapters = []
        for chap in item['chapters']:
            if not chap.get('text_content') and chap.get('staged_chapter_id'):
                chap['text_content'] = db.get_chapter_text_content(chap['staged_chapter_id'])
            
            # core.py expects 'extracted_text' in the dict
            chap['extracted_text'] = chap.get('text_content', '')
            selected_chapters.append(chap)

        # Bug Fix: Ensure voice is stripped of flag
        voice_str = settings.get('voice', '')
        if ' ' in voice_str:
            voice = " ".join(voice_str.split(' ')[1:])
        else:
            voice = voice_str

        params = {
            'file_path': item['source_path'],
            'voice': voice,
            'pick_manually': False,
            'speed': float(settings.get('luxtts_speed') if settings.get('tts_model') == 'luxtts' else settings.get('speed', 1.0)),
            'engine_device': settings.get('engine'),
            'output_folder': settings.get('output_folder') or ".",
            'selected_chapters': selected_chapters,
            'm4b_assembly_method': settings.get('m4b_assembly_method', 'original'),
            'custom_rate': settings.get('custom_rate'),
            'tts_model': settings.get('tts_model', 'kokoro'),
            'reference_wav': settings.get('luxtts_reference_wav'),
            'num_steps': int(settings.get('luxtts_num_steps', 4)),
            'max_chunk_len': int(settings.get('luxtts_max_chunk_len', 900)),
            'guidance_scale': float(settings.get('luxtts_guidance', 3.0)),
            't_shift': float(settings.get('luxtts_t_shift', 0.5)),
            'rms': float(settings.get('luxtts_rms', 0.1)),
            'duration': float(settings.get('luxtts_duration', 5.0)),
            'return_smooth': bool(settings.get('luxtts_smooth', False)),
            'seed': settings.get('luxtts_seed')
        }


        self.synth_thread = CoreThread(params, self.handle_core_event)
        self.synth_thread.start()

    def check_schedule(self):
        import time
        scheduled_time = db.load_schedule_time()
        if scheduled_time and time.time() >= scheduled_time:
            print(f"Scheduled run triggered at {time.ctime(time.time())}")
            db.save_schedule_time(None) # Clear schedule
            self.start_queue_processing()
        
        # Check again in 60 seconds
        self.after(60000, self.check_schedule)

    def handle_core_event(self, event_name, **kwargs):
        if event_name == 'CORE_PROGRESS':
            stats = kwargs.get('stats')
            if stats:
                self.after(0, lambda: self.synthesis.update_progress(stats.progress, stats.eta))
        elif event_name == 'CORE_FINISHED':
            self.after(0, lambda: self.synthesis.update_progress(100, "Done"))
            print("Synthesis Finished")
            
            if self.queue_running and self.current_queue_item:
                db.update_queue_item_status(self.current_queue_item['id'], 'completed')
                self.queue_running = False # Reset before starting next
                self.after(0, self.queue_tab.refresh_queue)
                self.after(1000, self.start_queue_processing)

        elif event_name == 'error':
            error_msg = kwargs.get('error_message', 'Unknown Error')
            print(f"Core Error: {error_msg}")
            
            if self.queue_running and self.current_queue_item:
                db.update_queue_item_status(self.current_queue_item['id'], 'error')
                self.queue_running = False
                self.after(0, self.queue_tab.refresh_queue)
                # Still try to process next item
                self.after(1000, self.start_queue_processing)

    def on_about(self):
        msg = "Audiblez CTK UI\nA modern, dark-mode-only interface for generating audiobooks."
        top = ctk.CTkToplevel(self)
        top.title("About Audiblez")
        top.geometry("400x200")
        label = ctk.CTkLabel(top, text=msg, pady=20)
        label.pack()
        btn = ctk.CTkButton(top, text="Close", command=top.destroy)
        btn.pack(pady=10)

    def on_resize(self, event):
        if event.widget == self:
            db.save_user_setting('window_geometry', f"{self.winfo_width()}x{self.winfo_height()}")


    def on_close(self):
        self.destroy()

if __name__ == "__main__":
    app = AudiblezApp()
    app.mainloop()
