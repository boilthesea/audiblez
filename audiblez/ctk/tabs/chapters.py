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
        
        # Main Layout: Just the chapter list
        # We remove column 1 expansion and the preview_frame
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Chapter List Frame (now fills the whole area)
        self.list_frame = ctk.CTkFrame(self)
        self.list_frame.grid(row=0, column=0, sticky="nsew", padx=0)
        self.list_frame.grid_rowconfigure(3, weight=1)
        self.list_frame.grid_columnconfigure(0, weight=1)

        self.list_label = ctk.CTkLabel(self.list_frame, text="Chapters", font=("Inter", 14, "bold"))
        self.list_label.grid(row=0, column=0, sticky="nw", padx=10, pady=(5, 2))

        # Parser selection
        self.parser_frame = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.parser_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 2))
        
        ctk.CTkLabel(self.parser_frame, text="Parsing Method:", font=("Inter", 11)).pack(side="left", padx=(0, 5))
        
        self.parser_switch = ctk.CTkSegmentedButton(
            self.parser_frame, 
            values=["Standard", "Zip", "Calibre Only"],
            command=self.on_parser_change
        )
        initial_val = "Standard"
        if self.controller.current_parsing_method == 2: initial_val = "Zip"
        if self.controller.current_parsing_method == 3: initial_val = "Calibre Only"
        self.parser_switch.set(initial_val)
        self.parser_switch.pack(side="left", fill="x", expand=True)

        self.scroll_header = ctk.CTkFrame(self.list_frame, fg_color="transparent", height=24)
        self.scroll_header.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 0))
        self.scroll_header.columnconfigure(1, weight=1)
        self.scroll_header.grid_propagate(False)
        
        ctk.CTkLabel(self.scroll_header, text="Inc.", font=("Inter", 11, "bold"), width=40).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(self.scroll_header, text="Chapter Name", font=("Inter", 11, "bold")).grid(row=0, column=1, sticky="w", padx=10)
        ctk.CTkLabel(self.scroll_header, text="Length", font=("Inter", 11, "bold"), width=80).grid(row=0, column=2, sticky="e")

        self.scroll_frame = ctk.CTkScrollableFrame(self.list_frame)
        self.scroll_frame.grid(row=3, column=0, sticky="nsew", padx=5, pady=(0, 5))

        self.staging_btn = ctk.CTkButton(self.list_frame, text="📥 Stage Book for Batching", command=self.on_stage)
        self.staging_btn.grid(row=4, column=0, sticky="ew", padx=10, pady=(10, 5))

        self.queue_btn = ctk.CTkButton(self.list_frame, text="⏩ Queue All Selected (Skip Staging)", command=self.on_queue)
        self.queue_btn.grid(row=5, column=0, sticky="ew", padx=10, pady=(5, 10))

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
            row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent", height=28)
            row.pack(fill="x", padx=5, pady=0)
            row.columnconfigure(1, weight=1)
            row.grid_propagate(False)
            
            cb_container = ctk.CTkFrame(row, fg_color="transparent", width=40, height=28)
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
        # Notify controller so it can update the PreviewPanel
        if hasattr(self.controller, 'on_chapter_selected'):
            self.controller.on_chapter_selected(chapter)

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
            source_path="N/A", 
            output_folder=self.controller.params.output_path.get() or ".",
            chapters=selected_chapters
        )
        print(f"Staged: {book['title']}")
        # Notification will be handled by controller if needed, or staging_tab directly
        if hasattr(self.controller, 'staging_tab'):
            self.controller.staging_tab.refresh_staging()

    def on_queue(self):
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

        # Prepare synthesis settings
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
            'm4b_assembly_method': m4b_method
        }

        # Prepare chapters for DB
        final_chapters_for_db = []
        for idx, chap in enumerate(selected_chapters):
            final_chapters_for_db.append({
                'staged_chapter_id': None,
                'title': chap.get('title', f"Chapter {idx+1}"),
                'text_content': chap.get('extracted_text', ''),
                'order': idx
            })

        db_queue_details = {
            'staged_book_id': None,
            'book_title': book['title'],
            'source_path': self.controller.selected_file_path or "N/A",
            'synthesis_settings': synthesis_settings,
            'chapters': final_chapters_for_db
        }

        new_item_id = db.add_item_to_queue(db_queue_details)
        if new_item_id:
            print(f"Added to Queue: {book['title']}")
            if hasattr(self.controller, 'queue_tab'):
                self.controller.queue_tab.refresh_queue()
            # Switch to Queue tab
            if hasattr(self.controller, 'tab_view'):
                self.controller.tab_view.set("Queue")
        else:
            print("Failed to add to queue.")

