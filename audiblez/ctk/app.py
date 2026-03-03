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
        self.current_parsing_method = 0
        
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
        self.main_container.grid_columnconfigure(0, weight=2) # Left: Tabs
        self.main_container.grid_columnconfigure(1, weight=1) # Right: Panels

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
        self.right_container.grid_rowconfigure(0, weight=1) # Details
        self.right_container.grid_rowconfigure(1, weight=1) # Params
        self.right_container.grid_rowconfigure(2, weight=0) # Synthesis

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
            self.current_parsing_method = 0
            threading.Thread(target=self._load_epub_file, args=(file_path,), daemon=True).start()

    def _load_epub_file(self, file_path):
        from ebooklib import epub
        from audiblez.core import find_document_chapters_and_extract_texts, find_cover
        from pathlib import Path

        try:
            book = epub.read_epub(file_path)
            meta_title = book.get_metadata('DC', 'title')
            title = meta_title[0][0] if meta_title else Path(file_path).stem
            meta_creator = book.get_metadata('DC', 'creator')
            author = meta_creator[0][0] if meta_creator else 'Unknown Author'

            ebooklib_chapters = find_document_chapters_and_extract_texts(book)
            document_chapters = []
            for i, ch in enumerate(ebooklib_chapters):
                document_chapters.append({
                    'title': ch.get_name(),
                    'extracted_text': getattr(ch, 'extracted_text', ''),
                    'chapter_index': i
                })
            
            cover = find_cover(book)
            
            self.after(0, lambda: self._load_book_data_into_ui(
                title=title,
                author=author,
                chapters=document_chapters,
                cover={'type': 'epub_cover', 'content': cover.content} if cover else None
            ))
            
        except Exception as e:
            print(f"Error loading EPUB: {e}")

    def on_open_with_calibre(self):
        file_path = ctk.filedialog.askopenfilename(filetypes=[("Ebook files", "*.epub;*.mobi;*.azw;*.azw3;*.fb2;*.lit;*.pdf"), ("All files", "*.*")])
        if file_path:
            self.selected_file_path = file_path
            # We don't know the method yet until _load_with_calibre finishes
            threading.Thread(target=self._load_with_calibre, args=(file_path,), daemon=True).start()

    def _load_with_calibre(self, file_path):
        from audiblez.calibre_handler import open_book_experimental
        from types import SimpleNamespace

        result, result_desc, chapters, metadata, cover_info = open_book_experimental(file_path, self._ask_user_for_calibre_path_generic)
        
        if not chapters:
            print(f"Failed to open book with Calibre: {result_desc}")
            return

        self.current_parsing_method = result - 1

        document_chapters = []
        for i, chapter_data in enumerate(chapters):
            chapter_obj = {
                'title': chapter_data.get('title', f"Chapter {i+1}"),
                'extracted_text': chapter_data.get('extracted_text', ''),
                'chapter_index': i
            }
            document_chapters.append(chapter_obj)

        book_title = "Unknown Title"
        book_author = "Unknown Author"
        if isinstance(metadata, dict):
            book_title = metadata.get('title', ["Unknown Title"])[0]
            book_author = metadata.get('creator', ["Unknown Author"])[0]

        self.after(0, lambda: self._load_book_data_into_ui(
            title=book_title,
            author=book_author,
            chapters=document_chapters,
            cover=cover_info
        ))

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
