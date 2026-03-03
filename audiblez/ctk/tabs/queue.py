import customtkinter as ctk
import audiblez.database as db

class QueueTab(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.label = ctk.CTkLabel(self, text="Synthesis Queue", font=("Inter", 14, "bold"))
        self.label.grid(row=0, column=0, sticky="nw", padx=10, pady=5)

        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)

        self.run_btn = ctk.CTkButton(self.action_frame, text="▶️ Run Queue", command=self.on_run_queue)
        self.run_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))

        self.schedule_btn = ctk.CTkButton(self.action_frame, text="⏰ Schedule", command=self.on_schedule)
        self.schedule_btn.pack(side="right", expand=True, fill="x", padx=(5, 0))

        self.refresh_queue()

    def refresh_queue(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        queue_items = db.get_queued_items()
        if not queue_items:
            ctk.CTkLabel(self.scroll_frame, text="Queue is empty.").pack(pady=20)
            return

        for item in queue_items:
            item_frame = ctk.CTkFrame(self.scroll_frame)
            item_frame.pack(fill="x", pady=5, padx=5)
            
            ctk.CTkLabel(item_frame, text=item['book_title'], font=("Inter", 12, "bold")).pack(side="left", padx=10)
            ctk.CTkLabel(item_frame, text=item['status'], text_color="orange" if item['status'] == 'pending' else "green").pack(side="left", padx=10)
            
            remove_btn = ctk.CTkButton(item_frame, text="❌", width=30, command=lambda i=item: self.remove_item(i))
            remove_btn.pack(side="right", padx=10)

    def on_run_queue(self):
        # Implementation for running the queue
        pass

    def on_schedule(self):
        # Implementation for scheduling queue run
        pass

    def remove_item(self, item):
        db.remove_queue_item(item['id'])
        self.refresh_queue()
