import customtkinter as ctk

class SynthesisPanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        self.grid_columnconfigure(0, weight=1)

        self.btn_container = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_container.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        self.btn_container.grid_columnconfigure(0, weight=1)
        self.btn_container.grid_columnconfigure(1, weight=1)

        self.start_btn = ctk.CTkButton(self.btn_container, text="🚀 Start Audiobook Synthesis", height=40, font=("Inter", 14, "bold"), command=self.on_start)
        self.start_btn.grid(row=0, column=0, columnspan=2, sticky="ew")

        self.pause_btn = ctk.CTkButton(self.btn_container, text="⏸️ Pause", height=40, font=("Inter", 14, "bold"), command=self.on_pause, fg_color="#E67E22", hover_color="#D35400")
        self.stop_btn = ctk.CTkButton(self.btn_container, text="🛑 Stop", height=40, font=("Inter", 14, "bold"), command=self.on_stop, fg_color="#C0392B", hover_color="#A93226")
        
        self.is_paused = False

        self.progress_label = ctk.CTkLabel(self, text="Synthesis Progress: 0%")
        self.progress_label.grid(row=1, column=0, sticky="w", padx=10)

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=5)

        self.eta_label = ctk.CTkLabel(self, text="Estimated Time Remaining: ---", font=("Inter", 11))
        self.eta_label.grid(row=3, column=0, sticky="w", padx=10, pady=(0, 10))

        self.set_state("IDLE")

    def set_state(self, state):
        if state == "IDLE":
            self.start_btn.grid(row=0, column=0, columnspan=2, sticky="ew")
            self.pause_btn.grid_remove()
            self.stop_btn.grid_remove()
            self.progress_bar.configure(progress_color="#3B8ED0")
            self.is_paused = False
        elif state == "RUNNING":
            self.start_btn.grid_remove()
            self.pause_btn.grid(row=0, column=0, sticky="ew", padx=(0, 5))
            self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(5, 0))
            self.pause_btn.configure(text="⏸️ Pause")
            self.progress_bar.configure(progress_color="#3B8ED0")
            self.is_paused = False
        elif state == "PAUSED":
            self.pause_btn.configure(text="▶️ Resume")
            self.progress_bar.configure(progress_color="#E67E22")
            self.is_paused = True

    def on_start(self):
        self.set_state("RUNNING")
        self.controller.start_synthesis()

    def on_pause(self):
        if self.is_paused:
            self.set_state("RUNNING")
            self.controller.on_resume_synthesis()
        else:
            self.set_state("PAUSED")
            self.controller.on_pause_synthesis()

    def on_stop(self):
        self.set_state("IDLE")
        self.controller.on_stop_synthesis()

    def update_progress(self, progress, eta=None):
        # Ensure we are in RUNNING or PAUSED state if synthesis is active
        if self.start_btn.winfo_viewable() and progress < 100:
            self.set_state("RUNNING")
            
        if progress >= 100:
            self.set_state("IDLE")
            
        self.progress_bar.set(progress / 100.0)
        self.progress_label.configure(text=f"Synthesis Progress: {progress}%")
        if eta:
            self.eta_label.configure(text=f"Estimated Time Remaining: {eta}")
