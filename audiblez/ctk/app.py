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

class AudiblezApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Load settings
        self.user_settings = db.load_all_user_settings(ui_name='ctk')
        self.selected_file_path = None
        self.current_parsing_method = 1 # 1: Standard, 2: Zip, 3: Calibre
        
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

        # Main Splitter replacement
        self.main_container = ctk.CTkFrame(self, corner_radius=0)
        self.main_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.main_container.grid_columnconfigure(0, weight=4) # Left: Tabs
        self.main_container.grid_columnconfigure(1, weight=1) # Right: Panels
        self.main_container.grid_rowconfigure(0, weight=1)

        # Left Side: Notebook (Tabs)
        self.tab_view = ctk.CTkTabview(self.main_container)
        self.tab_view.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        
        self.chapters_tab = ChaptersTab(self.tab_view.add("Chapters"), self)
        self.chapters_tab.pack(expand=True, fill="both")
        
        self.staging_tab = StagingTab(self.tab_view.add("Staging"), self)
        self.staging_tab.pack(expand=True, fill="both")
        
        self.queue_tab = QueueTab(self.tab_view.add("Queue"), self)
        self.queue_tab.pack(expand=True, fill="both")

        # Right Side: Panels
        self.right_container = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.right_container.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.right_container.grid_rowconfigure(0, weight=0) # Details
        self.right_container.grid_rowconfigure(1, weight=0) # Params
        self.right_container.grid_rowconfigure(2, weight=0) # Synthesis
        self.right_container.grid_rowconfigure(3, weight=1) # Spacer to push everything up

        self.book_details = BookDetailsPanel(self.right_container, self)
        self.book_details.grid(row=0, column=0, sticky="nsew", pady=(0, 5))

        self.params = ParamsPanel(self.right_container, self)
        self.params.grid(row=1, column=0, sticky="nsew", pady=5)

        self.synthesis = SynthesisPanel(self.right_container, self)
        self.synthesis.grid(row=2, column=0, sticky="new", pady=(5, 0))

    def on_open_epub(self):
        file_path = ctk.filedialog.askopenfilename(filetypes=[("EPUB Files", "*.epub")])
        if file_path:
            self.selected_file_path = file_path
            # Use the method selected in the ChaptersTab if it exists, else default to 1 (Standard)
            method = getattr(self, 'current_parsing_method', 1)
            threading.Thread(target=self._load_book_file_threaded, args=(file_path,), kwargs={'method': method}, daemon=True).start()

    def _load_book_file_threaded(self, file_path, method=1):
        from audiblez.calibre_handler import open_book_experimental
        from pathlib import Path
        import traceback

        try:
            # Use open_book_experimental as it handles all 3 methods uniformly
            res_method, msg, chapters, metadata, cover_info = open_book_experimental(
                file_path, 
                ui_callback_for_path_selection=self._ask_user_for_calibre_path_generic,
                method=method
            )

            if not chapters:
                print(f"Failed to load chapters: {msg}")
                return

            # Normalize metadata handling (Method 1/2 returns list of tuples, Method 3 returns strings)
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
            print(f"Loaded: {title} with method {res_method}")

        except Exception as e:
            print(f"Error loading EPUB: {e}")
            traceback.print_exc()

    def on_open_with_calibre(self):
        file_path = ctk.filedialog.askopenfilename(filetypes=[("Ebook files", "*.epub;*.mobi;*.azw;*.azw3;*.fb2;*.lit;*.pdf"), ("All files", "*.*")])
        if file_path:
            self.selected_file_path = file_path
            # For Calibre button, we default to Calibre Only (method 3)
            threading.Thread(target=self._load_book_file_threaded, args=(file_path,), kwargs={'method': 3}, daemon=True).start()


    def _ask_user_for_calibre_path_generic(self):
        # In CTK we could use a simple message box then dir dialog
        # For now let's just use the dir dialog directly or assume user knows
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
        
        # Update Chapters Tab
        self.chapters_tab.load_chapters(chapters)
        
        print(f"UI Updated for: {title}")

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
        voice = self.params.voice_var.get().split(' ')[1] # Just the voice name
        params = {
            'file_path': self.selected_file_path,
            'voice': voice,
            'pick_manually': False,
            'speed': float(self.params.speed_var.get()),
            'engine': self.params.engine_var.get(),
            'output_folder': self.params.output_path.get() or ".",
            'selected_chapters': [c for i, c in enumerate(self.current_book['chapters']) if self.chapters_tab.chapter_vars[i].get()],
            'm4b_assembly_method': self.params.m4b_var.get()
        }

        self.synth_thread = CoreThread(params, self.handle_core_event)
        self.synth_thread.start()

    def handle_core_event(self, event_name, **kwargs):
        if event_name == 'CORE_PROGRESS':
            stats = kwargs.get('stats')
            if stats:
                self.after(0, lambda: self.synthesis.update_progress(stats.progress, stats.eta))
        elif event_name == 'CORE_FINISHED':
            self.after(0, lambda: self.synthesis.update_progress(100, "Done"))
            print("Synthesis Finished")
        elif event_name == 'error':
            error_msg = kwargs.get('error_message', 'Unknown Error')
            print(f"Core Error: {error_msg}")

    def on_about(self):
        msg = "Audiblez CTK UI\nA modern, dark-mode-only interface for generating audiobooks."
        dialog = ctk.CTkEntry(self, placeholder_text=msg)
        # Using a simple Toplevel for About
        top = ctk.CTkToplevel(self)
        top.title("About Audiblez")
        top.geometry("400x200")
        label = ctk.CTkLabel(top, text=msg, pady=20)
        label.pack()
        btn = ctk.CTkButton(top, text="Close", command=top.destroy)
        btn.pack(pady=10)

    def on_resize(self, event):
        if event.widget == self:
            db.save_user_setting('window_geometry', f"{self.winfo_width()}x{self.winfo_height()}", ui_name='ctk')

    def on_close(self):
        self.destroy()

if __name__ == "__main__":
    app = AudiblezApp()
    app.mainloop()
