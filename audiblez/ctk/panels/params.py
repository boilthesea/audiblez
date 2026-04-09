import customtkinter as ctk
import torch
import audiblez.database as db
from audiblez.voices import voices, flags
import random

class ParamsPanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.grid_columnconfigure(1, weight=1)

        self.label = ctk.CTkLabel(self, text="Audiobook Parameters", font=("Inter", 16, "bold"))
        self.label.grid(row=0, column=0, columnspan=2, sticky="nw", padx=10, pady=5)

        # Model Selection (Kokoro vs LuxTTS)
        ctk.CTkLabel(self, text="Model:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.model_var = ctk.StringVar(value=self.controller.user_settings.get('tts_model', 'kokoro'))
        self.model_switch = ctk.CTkSegmentedButton(self, values=["kokoro", "luxtts"], 
                                                   variable=self.model_var, command=self.on_model_change)
        self.model_switch.grid(row=1, column=1, sticky="ew", padx=10, pady=5)

        # Engine
        ctk.CTkLabel(self, text="Engine:").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        self.engine_var = ctk.StringVar(value=self.controller.user_settings.get('engine', 'cpu'))
        self.engine_switch = ctk.CTkSegmentedButton(self, values=["cpu", "cuda"], variable=self.engine_var, command=self.on_engine_change)
        self.engine_switch.grid(row=2, column=1, sticky="ew", padx=10, pady=5)

        # --- Kokoro Specific ---
        self.voice_label = ctk.CTkLabel(self, text="Voice:")
        self.voice_list = []
        for code, l in voices.items():
            for v in l:
                self.voice_list.append(f"{flags[code]} {v}")
        
        saved_voice = self.controller.user_settings.get('voice')
        if not saved_voice or saved_voice not in self.voice_list:
            saved_voice = self.voice_list[0] if self.voice_list else ""
            
        self.voice_var = ctk.StringVar(value=saved_voice)
        self.voice_dropdown = ctk.CTkOptionMenu(self, values=self.voice_list, variable=self.voice_var, command=self.on_voice_change)

        # --- LuxTTS Specific ---
        self.lux_container = ctk.CTkFrame(self, fg_color="transparent")
        self.lux_container.grid_columnconfigure(1, weight=1)

        # Ref WAV
        self.ref_wav_label = ctk.CTkLabel(self.lux_container, text="Ref WAV:")
        self.ref_wav_var = ctk.StringVar(value=self.controller.user_settings.get('luxtts_reference_wav', ''))
        self.ref_wav_entry = ctk.CTkEntry(self.lux_container, textvariable=self.ref_wav_var)
        self.ref_wav_btn = ctk.CTkButton(self.lux_container, text="📂", width=30, command=self.select_ref_wav)

        # Guidance Slider (1.0 - 10.0)
        self.guidance_label = ctk.CTkLabel(self.lux_container, text="Guidance:")
        self.guidance_var = ctk.DoubleVar(value=float(self.controller.user_settings.get('luxtts_guidance', 3.0)))
        self.guidance_slider = ctk.CTkSlider(self.lux_container, from_=1.0, to=10.0, variable=self.guidance_var, command=lambda v: self.on_slider_change('luxtts_guidance', v))
        self.guidance_val_label = ctk.CTkLabel(self.lux_container, text=f"{self.guidance_var.get():.1f}", width=30)

        # T-Shift Slider (0.0 - 2.0)
        self.t_shift_label = ctk.CTkLabel(self.lux_container, text="T-Shift:")
        self.t_shift_var = ctk.DoubleVar(value=float(self.controller.user_settings.get('luxtts_t_shift', 0.5)))
        self.t_shift_slider = ctk.CTkSlider(self.lux_container, from_=0.0, to=2.0, variable=self.t_shift_var, command=lambda v: self.on_slider_change('luxtts_t_shift', v))
        self.t_shift_val_label = ctk.CTkLabel(self.lux_container, text=f"{self.t_shift_var.get():.1f}", width=30)

        # Lux Speed Slider (0.5 - 2.0)
        self.lux_speed_label = ctk.CTkLabel(self.lux_container, text="Speed:")
        self.lux_speed_var = ctk.DoubleVar(value=float(self.controller.user_settings.get('luxtts_speed', 1.0)))
        
        self.speed_slider_frame = ctk.CTkFrame(self.lux_container, fg_color="transparent")
        self.lux_speed_slider = ctk.CTkSlider(self.speed_slider_frame, from_=0.5, to=2.0, variable=self.lux_speed_var, command=lambda v: self.on_slider_change('luxtts_speed', v))
        self.lux_speed_slower = ctk.CTkLabel(self.speed_slider_frame, text="Slower", font=("Inter", 10))
        self.lux_speed_faster = ctk.CTkLabel(self.speed_slider_frame, text="Faster", font=("Inter", 10))
        
        self.lux_speed_slower.pack(side="left")
        self.lux_speed_slider.pack(side="left", expand=True, fill="x", padx=5)
        self.lux_speed_faster.pack(side="left")
        
        self.lux_speed_val_label = ctk.CTkLabel(self.lux_container, text=f"{self.lux_speed_var.get():.1f}", width=30)

        # RMS Slider (0.0 - 2.0)
        self.rms_label = ctk.CTkLabel(self.lux_container, text="RMS:")
        self.rms_var = ctk.DoubleVar(value=float(self.controller.user_settings.get('luxtts_rms', 0.1)))
        self.rms_slider = ctk.CTkSlider(self.lux_container, from_=0.0, to=2.0, variable=self.rms_var, command=lambda v: self.on_slider_change('luxtts_rms', v))
        self.rms_val_label = ctk.CTkLabel(self.lux_container, text=f"{self.rms_var.get():.2f}", width=30)

        # Duration Slider (1 - 15)
        self.duration_label = ctk.CTkLabel(self.lux_container, text="Duration:")
        self.duration_var = ctk.DoubleVar(value=float(self.controller.user_settings.get('luxtts_duration', 5.0)))
        self.duration_slider = ctk.CTkSlider(self.lux_container, from_=1.0, to=15.0, variable=self.duration_var, command=lambda v: self.on_slider_change('luxtts_duration', v))
        self.duration_val_label = ctk.CTkLabel(self.lux_container, text=f"{int(self.duration_var.get())}s", width=30)

        # Steps Entry
        self.steps_label = ctk.CTkLabel(self.lux_container, text="Steps:")
        self.steps_var = ctk.StringVar(value=str(self.controller.user_settings.get('luxtts_num_steps', 4)))
        self.steps_entry = ctk.CTkEntry(self.lux_container, textvariable=self.steps_var)
        self.steps_entry.bind("<KeyRelease>", self.on_steps_change)

        # Chunk Len Entry
        self.chunk_label = ctk.CTkLabel(self.lux_container, text="Chunk Len:")
        self.chunk_var = ctk.StringVar(value=str(self.controller.user_settings.get('luxtts_max_chunk_len', 900)))
        self.chunk_entry = ctk.CTkEntry(self.lux_container, textvariable=self.chunk_var)
        self.chunk_entry.bind("<KeyRelease>", self.on_chunk_change)

        # Smoothing Checkbox
        self.smooth_var = ctk.BooleanVar(value=bool(self.controller.user_settings.get('luxtts_smooth', False)))
        self.smooth_cb = ctk.CTkCheckBox(self.lux_container, text="Vocos Smoothing (24kHz)", variable=self.smooth_var, command=self.on_smooth_change)

        # Seed System
        self.seed_label = ctk.CTkLabel(self.lux_container, text="Seed:")
        self.seed_var = ctk.StringVar(value=str(self.controller.user_settings.get('luxtts_seed', '')))
        self.seed_entry = ctk.CTkEntry(self.lux_container, textvariable=self.seed_var)
        self.seed_locked_var = ctk.BooleanVar(value=bool(self.controller.user_settings.get('luxtts_seed_locked', False)))
        self.seed_lock_btn = ctk.CTkButton(self.lux_container, text="🔓" if not self.seed_locked_var.get() else "🔒", width=30, command=self.toggle_seed_lock)

        # Layout Lux Container
        self.ref_wav_label.grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.ref_wav_entry.grid(row=0, column=1, sticky="ew", padx=(5, 40), pady=2)
        self.ref_wav_btn.grid(row=0, column=1, sticky="e", padx=(0, 5), pady=2)

        self.guidance_label.grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self.guidance_slider.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        self.guidance_val_label.grid(row=1, column=2, sticky="w", padx=5, pady=2)

        self.t_shift_label.grid(row=2, column=0, sticky="w", padx=5, pady=2)
        self.t_shift_slider.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        self.t_shift_val_label.grid(row=2, column=2, sticky="w", padx=5, pady=2)

        self.lux_speed_label.grid(row=3, column=0, sticky="w", padx=5, pady=2)
        self.speed_slider_frame.grid(row=3, column=1, sticky="ew", padx=5, pady=2)
        self.lux_speed_val_label.grid(row=3, column=2, sticky="w", padx=5, pady=2)

        self.rms_label.grid(row=4, column=0, sticky="w", padx=5, pady=2)
        self.rms_slider.grid(row=4, column=1, sticky="ew", padx=5, pady=2)
        self.rms_val_label.grid(row=4, column=2, sticky="w", padx=5, pady=2)

        self.duration_label.grid(row=5, column=0, sticky="w", padx=5, pady=2)
        self.duration_slider.grid(row=5, column=1, sticky="ew", padx=5, pady=2)
        self.duration_val_label.grid(row=5, column=2, sticky="w", padx=5, pady=2)

        self.steps_label.grid(row=6, column=0, sticky="w", padx=5, pady=2)
        self.steps_entry.grid(row=6, column=1, sticky="ew", padx=5, pady=2)

        self.chunk_label.grid(row=7, column=0, sticky="w", padx=5, pady=2)
        self.chunk_entry.grid(row=7, column=1, sticky="ew", padx=5, pady=2)

        self.smooth_cb.grid(row=8, column=0, columnspan=2, sticky="w", padx=5, pady=5)

        self.seed_label.grid(row=9, column=0, sticky="w", padx=5, pady=2)
        self.seed_entry.grid(row=9, column=1, sticky="ew", padx=(5, 40), pady=2)
        self.seed_lock_btn.grid(row=9, column=1, sticky="e", padx=(0, 5), pady=2)

        # --- Shared Parameters ---
        # Kokoro Speed
        self.speed_label = ctk.CTkLabel(self, text="Speed:")
        self.speed_var = ctk.StringVar(value=str(self.controller.user_settings.get('speed', 1.0)))
        self.speed_entry = ctk.CTkEntry(self, textvariable=self.speed_var)
        self.speed_entry.bind("<KeyRelease>", self.on_speed_change)

        # Custom Rate
        ctk.CTkLabel(self, text="Custom Rate:").grid(row=11, column=0, sticky="w", padx=10, pady=5)
        self.rate_var = ctk.StringVar(value=str(self.controller.user_settings.get('custom_rate', '')))
        self.rate_entry = ctk.CTkEntry(self, textvariable=self.rate_var, placeholder_text="chars/sec (experimental)")
        self.rate_entry.grid(row=11, column=1, sticky="ew", padx=10, pady=5)
        self.rate_entry.bind("<KeyRelease>", self.on_rate_change)

        # Output Folder
        ctk.CTkLabel(self, text="Output:").grid(row=12, column=0, sticky="w", padx=10, pady=5)
        self.output_path = ctk.CTkEntry(self)
        self.output_path.grid(row=12, column=1, sticky="ew", padx=(10, 80), pady=5)
        
        saved_output = self.controller.user_settings.get('output_folder', '')
        if saved_output:
            self.output_path.insert(0, saved_output)
            
        self.output_btn = ctk.CTkButton(self, text="📂", width=60, command=self.select_output)
        self.output_btn.grid(row=12, column=1, sticky="e", padx=(0, 10), pady=5)

        # M4B Assembly
        ctk.CTkLabel(self, text="M4B Assembly:").grid(row=13, column=0, sticky="w", padx=10, pady=5)
        self.m4b_var = ctk.StringVar(value=self.controller.user_settings.get('m4b_assembly_method', 'original'))
        self.m4b_switch = ctk.CTkSegmentedButton(self, values=["Original", "Extra Crispy"], variable=self.m4b_var, command=self.on_m4b_change)
        
        val_to_display = {"original": "Original", "crispy": "Extra Crispy"}
        current_val = self.controller.user_settings.get('m4b_assembly_method', 'original')
        self.m4b_var.set(val_to_display.get(current_val, "Original"))
        self.m4b_switch.grid(row=13, column=1, sticky="ew", padx=10, pady=5)

        # Initialize visibility
        self.refresh_model_visibility()

    def refresh_model_visibility(self):
        model = self.model_var.get()
        # Hide dynamic parts
        self.voice_label.grid_forget()
        self.voice_dropdown.grid_forget()
        self.lux_container.grid_forget()
        self.speed_label.grid_forget()
        self.speed_entry.grid_forget()

        if model == "kokoro":
            self.voice_label.grid(row=3, column=0, sticky="w", padx=10, pady=5)
            self.voice_dropdown.grid(row=3, column=1, sticky="ew", padx=10, pady=5)
            self.speed_label.grid(row=10, column=0, sticky="w", padx=10, pady=5)
            self.speed_entry.grid(row=10, column=1, sticky="ew", padx=10, pady=5)
        else: # luxtts
            self.lux_container.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)

    def on_model_change(self, value):
        db.save_user_setting('tts_model', value)
        self.refresh_model_visibility()

    def on_engine_change(self, value):
        db.save_user_setting('engine', value)
        if value == 'cuda' and not torch.cuda.is_available():
            print("CUDA not available, switching back to CPU")
            self.engine_var.set('cpu')
            db.save_user_setting('engine', 'cpu')

    def on_voice_change(self, value):
        db.save_user_setting('voice', value)

    def on_speed_change(self, event):
        try:
            val = float(self.speed_entry.get())
            db.save_user_setting('speed', val)
        except ValueError:
            pass

    def on_slider_change(self, setting, value):
        db.save_user_setting(setting, value)
        # Update labels
        if setting == 'luxtts_guidance':
            self.guidance_val_label.configure(text=f"{value:.1f}")
        elif setting == 'luxtts_t_shift':
            self.t_shift_val_label.configure(text=f"{value:.1f}")
        elif setting == 'luxtts_speed':
            self.lux_speed_val_label.configure(text=f"{value:.1f}")
        elif setting == 'luxtts_rms':
            self.rms_val_label.configure(text=f"{value:.2f}")
        elif setting == 'luxtts_duration':
            self.duration_val_label.configure(text=f"{int(value)}s")

    def on_steps_change(self, event):
        try:
            val = int(self.steps_entry.get())
            db.save_user_setting('luxtts_num_steps', val)
        except ValueError:
            pass

    def on_chunk_change(self, event):
        try:
            val = int(self.chunk_entry.get())
            db.save_user_setting('luxtts_max_chunk_len', val)
        except ValueError:
            pass

    def on_smooth_change(self):
        db.save_user_setting('luxtts_smooth', self.smooth_var.get())

    def toggle_seed_lock(self):
        locked = not self.seed_locked_var.get()
        self.seed_locked_var.set(locked)
        self.seed_lock_btn.configure(text="🔒" if locked else "🔓")
        db.save_user_setting('luxtts_seed_locked', locked)

    def get_effective_seed(self):
        """Called by preview or synthesis to determine the seed to use."""
        if self.seed_locked_var.get():
            try:
                return int(self.seed_var.get())
            except ValueError:
                return random.randint(0, 2**32 - 1)
        else:
            new_seed = random.randint(0, 2**32 - 1)
            self.seed_var.set(str(new_seed))
            db.save_user_setting('luxtts_seed', new_seed)
            return new_seed

    def select_ref_wav(self):
        file_path = ctk.filedialog.askopenfilename(filetypes=[("WAV files", "*.wav")])
        if file_path:
            self.ref_wav_var.set(file_path)
            db.save_user_setting('luxtts_reference_wav', file_path)

    def select_output(self):
        folder = ctk.filedialog.askdirectory()
        if folder:
            self.output_path.delete(0, "end")
            self.output_path.insert(0, folder)
            db.save_user_setting('output_folder', folder)

    def on_m4b_change(self, value):
        display_to_val = {"Original": "original", "Extra Crispy": "crispy"}
        db_val = display_to_val.get(value, "original")
        db.save_user_setting('m4b_assembly_method', db_val)

    def on_rate_change(self, event):
        try:
            val = int(self.rate_entry.get())
            db.save_user_setting('custom_rate', val)
        except ValueError:
            pass
