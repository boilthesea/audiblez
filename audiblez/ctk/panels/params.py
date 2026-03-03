import customtkinter as ctk
import torch
import audiblez.database as db
from audiblez.voices import voices, flags

class ParamsPanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.grid_columnconfigure(1, weight=1)

        self.label = ctk.CTkLabel(self, text="Audiobook Parameters", font=("Inter", 16, "bold"))
        self.label.grid(row=0, column=0, columnspan=2, sticky="nw", padx=10, pady=5)

        # Engine
        ctk.CTkLabel(self, text="Engine:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.engine_var = ctk.StringVar(value=self.controller.user_settings.get('engine', 'cpu'))
        self.engine_switch = ctk.CTkSegmentedButton(self, values=["cpu", "cuda"], variable=self.engine_var, command=self.on_engine_change)
        self.engine_switch.grid(row=1, column=1, sticky="ew", padx=10, pady=5)

        # Voice
        ctk.CTkLabel(self, text="Voice:").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        self.voice_list = []
        for code, l in voices.items():
            for v in l:
                self.voice_list.append(f"{flags[code]} {v}")
        
        saved_voice = self.controller.user_settings.get('voice')
        if not saved_voice or saved_voice not in self.voice_list:
            saved_voice = self.voice_list[0] if self.voice_list else ""
            
        self.voice_var = ctk.StringVar(value=saved_voice)
        self.voice_dropdown = ctk.CTkOptionMenu(self, values=self.voice_list, variable=self.voice_var, command=self.on_voice_change)
        self.voice_dropdown.grid(row=2, column=1, sticky="ew", padx=10, pady=5)

        # Speed
        ctk.CTkLabel(self, text="Speed:").grid(row=3, column=0, sticky="w", padx=10, pady=5)
        self.speed_var = ctk.StringVar(value=str(self.controller.user_settings.get('speed', 1.0)))
        self.speed_entry = ctk.CTkEntry(self, textvariable=self.speed_var)
        self.speed_entry.grid(row=3, column=1, sticky="ew", padx=10, pady=5)
        self.speed_entry.bind("<KeyRelease>", self.on_speed_change)

        # Custom Rate
        ctk.CTkLabel(self, text="Custom Rate:").grid(row=4, column=0, sticky="w", padx=10, pady=5)
        self.rate_var = ctk.StringVar(value=str(self.controller.user_settings.get('custom_rate', '')))
        self.rate_entry = ctk.CTkEntry(self, textvariable=self.rate_var, placeholder_text="chars/sec (experimental)")
        self.rate_entry.grid(row=4, column=1, sticky="ew", padx=10, pady=5)
        self.rate_entry.bind("<KeyRelease>", self.on_rate_change)

        # Output Folder
        ctk.CTkLabel(self, text="Output:").grid(row=5, column=0, sticky="w", padx=10, pady=5)
        self.output_path = ctk.CTkEntry(self)
        self.output_path.grid(row=5, column=1, sticky="ew", padx=(10, 80), pady=5)
        self.output_btn = ctk.CTkButton(self, text="📂", width=60, command=self.select_output)
        self.output_btn.grid(row=5, column=1, sticky="e", padx=(0, 10), pady=5)

        # M4B Assembly
        ctk.CTkLabel(self, text="M4B Assembly:").grid(row=6, column=0, sticky="w", padx=10, pady=5)
        self.m4b_var = ctk.StringVar(value=self.controller.user_settings.get('m4b_assembly_method', 'original'))
        self.m4b_switch = ctk.CTkSegmentedButton(self, values=["original", "extra crispy"], variable=self.m4b_var, command=self.on_m4b_change)
        self.m4b_switch.grid(row=6, column=1, sticky="ew", padx=10, pady=5)

    def on_engine_change(self, value):
        db.save_user_setting('engine', value, ui_name='ctk')
        if value == 'cuda' and not torch.cuda.is_available():
            print("CUDA not available, switching back to CPU")
            self.engine_var.set('cpu')
            db.save_user_setting('engine', 'cpu', ui_name='ctk')

    def on_voice_change(self, value):
        db.save_user_setting('voice', value, ui_name='ctk')

    def on_speed_change(self, event):
        try:
            val = float(self.speed_entry.get())
            db.save_user_setting('speed', val, ui_name='ctk')
        except ValueError:
            pass

    def on_m4b_change(self, value):
        db.save_user_setting('m4b_assembly_method', value, ui_name='ctk')

    def on_rate_change(self, event):
        try:
            val = int(self.rate_entry.get())
            db.save_user_setting('custom_rate', val, ui_name='ctk')
        except ValueError:
            pass

    def select_output(self):
        folder = ctk.filedialog.askdirectory()
        if folder:
            self.output_path.delete(0, "end")
            self.output_path.insert(0, folder)
            db.save_user_setting('output_folder', folder, ui_name='ctk')
