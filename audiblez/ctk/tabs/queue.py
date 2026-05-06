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

        # Ensure scroll bindings are applied to new children
        if hasattr(self.controller, "_bind_mouse_wheel_recursive"):
            self.controller._bind_mouse_wheel_recursive(self.scroll_frame, self.scroll_frame)

    def on_run_queue(self):
        # Implementation for running the queue
        self.controller.start_queue_processing()

    def on_schedule(self):
        # Implementation for scheduling queue run
        ScheduleDialog(self, self.controller)

    def remove_item(self, item):
        db.remove_queue_item(item['id'])
        self.refresh_queue()

class ScheduleDialog(ctk.CTkToplevel):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.title("Schedule Queue Run")
        self.geometry("400x300")
        
        # Make it modal-ish
        self.after(10, self.grab_set)
        
        self.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(self, text="Schedule Queue Processing", font=("Inter", 16, "bold")).grid(row=0, column=0, pady=20)
        
        import datetime
        now = datetime.datetime.now()
        default_date = now.strftime("%Y-%m-%d")
        # Default to 1 hour from now, rounded to nearest 10 mins
        default_time = (now + datetime.timedelta(hours=1)).strftime("%H:%M")
        
        # Date Input
        ctk.CTkLabel(self, text="Date (YYYY-MM-DD):").grid(row=1, column=0, sticky="w", padx=40)
        self.date_entry = ctk.CTkEntry(self, placeholder_text="YYYY-MM-DD")
        self.date_entry.insert(0, default_date)
        self.date_entry.grid(row=2, column=0, sticky="ew", padx=40, pady=(0, 10))
        
        # Time Input
        ctk.CTkLabel(self, text="Time (HH:MM):").grid(row=3, column=0, sticky="w", padx=40)
        self.time_entry = ctk.CTkEntry(self, placeholder_text="HH:MM")
        self.time_entry.insert(0, default_time)
        self.time_entry.grid(row=4, column=0, sticky="ew", padx=40, pady=(0, 20))
        
        self.set_btn = ctk.CTkButton(self, text="Set Schedule", command=self.on_set)
        self.set_btn.grid(row=5, column=0, pady=10)
        
        self.cancel_btn = ctk.CTkButton(self, text="Cancel", fg_color="transparent", border_width=1, command=self.destroy)
        self.cancel_btn.grid(row=6, column=0, pady=5)

    def on_set(self):
        date_str = self.date_entry.get()
        time_str = self.time_entry.get()
        
        try:
            import datetime
            import time
            dt_str = f"{date_str} {time_str}"
            dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            timestamp = time.mktime(dt.timetuple())
            
            if timestamp < time.time():
                print("Warning: Scheduled time is in the past.")
                # We'll allow it, it will just trigger on next check.
            
            db.save_schedule_time(int(timestamp))
            print(f"Queue scheduled for {dt_str}")
            self.destroy()
        except ValueError:
            print("Invalid date or time format.")
            # We could add a label for error message here
