import customtkinter as ctk

class SynthesisPanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        self.grid_columnconfigure(0, weight=1)

        self.start_btn = ctk.CTkButton(self, text="🚀 Start Audiobook Synthesis", height=40, font=("Inter", 14, "bold"), command=self.on_start)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))

        self.progress_label = ctk.CTkLabel(self, text="Synthesis Progress: 0%")
        self.progress_label.grid(row=1, column=0, sticky="w", padx=10)

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=5)

        self.eta_label = ctk.CTkLabel(self, text="Estimated Time Remaining: ---", font=("Inter", 11))
        self.eta_label.grid(row=3, column=0, sticky="w", padx=10, pady=(0, 10))

    def on_start(self):
        self.controller.start_synthesis()

    def update_progress(self, progress, eta=None):
        self.progress_bar.set(progress / 100.0)
        self.progress_label.configure(text=f"Synthesis Progress: {progress}%")
        if eta:
            self.eta_label.configure(text=f"Estimated Time Remaining: {eta}")
