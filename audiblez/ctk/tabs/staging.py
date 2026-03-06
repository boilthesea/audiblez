import customtkinter as ctk
import audiblez.database as db

class StagingTab(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.label = ctk.CTkLabel(self, text="Staging Area", font=("Inter", 14, "bold"))
        self.label.grid(row=0, column=0, sticky="nw", padx=10, pady=5)

        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

        self.refresh_btn = ctk.CTkButton(self, text="🔄 Refresh Staging", command=self.refresh_staging)
        self.refresh_btn.grid(row=2, column=0, sticky="ew", padx=10, pady=10)

        self.refresh_staging()

    def refresh_staging(self):
        # Clear current list
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        staged_books = db.get_staged_books_with_chapters()
        if not staged_books:
            ctk.CTkLabel(self.scroll_frame, text="No books in staging area.").pack(pady=20)
            return

        for book in staged_books:
            book_frame = ctk.CTkFrame(self.scroll_frame)
            book_frame.pack(fill="x", pady=5, padx=5)
            
            ctk.CTkLabel(book_frame, text=book['title'], font=("Inter", 12, "bold")).pack(side="left", padx=10)
            ctk.CTkLabel(book_frame, text=book['author']).pack(side="left", padx=10)
            
            queue_btn = ctk.CTkButton(book_frame, text="➕ Add to Queue", width=120, command=lambda b=book: self.add_to_queue(b))
            queue_btn.pack(side="right", padx=10)

    def add_to_queue(self, book):
        import audiblez.database as db
        import json
        
        # Prepare settings
        voice_raw = self.controller.params.voice_var.get()
        voice_data = voice_raw.split(' ')
        voice = " ".join(voice_data[1:]) if len(voice_data) > 1 else voice_data[0]
        
        settings = {
            'voice': voice,
            'speed': float(self.controller.params.speed_var.get()),
            'engine': self.controller.params.engine_var.get(),
            'output_folder': self.controller.params.output_path.get() or ".",
            'm4b_assembly_method': self.controller.params.m4b_var.get()
        }

        details = {
            'staged_book_id': book['id'],
            'book_title': book['title'],
            'source_path': book.get('source_path', 'N/A'),
            'synthesis_settings': settings,
            'chapters': [{'staged_chapter_id': c['id'], 'title': c['title'], 'order': c['chapter_number']} for c in book['chapters']]
        }

        db.add_item_to_queue(details)
        print(f"Added to queue: {book['title']}")
        self.controller.queue_tab.refresh_queue()
