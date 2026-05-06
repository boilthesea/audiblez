import customtkinter as ctk
from PIL import Image
import io
from pathlib import Path
import threading
import os
import platform
import subprocess

class CTKTooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.id = None
        self.widget.bind("<Enter>", self.schedule, add="+")
        self.widget.bind("<Leave>", self.hide, add="+")
        self.widget.bind("<ButtonPress>", self.hide, add="+")

    def schedule(self, event=None):
        self.id = self.widget.after(500, self.show)

    def show(self, event=None):
        if self.tooltip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 20
        self.tooltip_window = tw = ctk.CTkToplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        label = ctk.CTkLabel(tw, text=self.text, corner_radius=5, 
                             fg_color=("#F0F0F0", "#333333"),
                             padx=5, pady=2, font=("Inter", 11))
        label.pack()

    def hide(self, event=None):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

class BookDetailsPanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.full_title = ""
        self.full_author = ""
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0) # Cover column

        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, sticky="nw", padx=10, pady=(5, 0))
        
        self.label = ctk.CTkLabel(self.header_frame, text="Book Details", font=("Inter", 16, "bold"))
        self.label.pack(side="left")

        # Cover Image (Top Right)
        self.cover_label = ctk.CTkLabel(self, text="No Cover", width=90, height=130, fg_color="#333333")
        self.cover_label.grid(row=0, column=1, rowspan=5, padx=10, pady=10, sticky="ne")

        # Metadata (Crunched)
        self.title_label = ctk.CTkLabel(self, text="Title: ---", anchor="w")
        self.title_label.grid(row=1, column=0, sticky="ew", padx=10, pady=0)
        self.title_tooltip = CTKTooltip(self.title_label, "")

        self.author_label = ctk.CTkLabel(self, text="Author: ---", anchor="w")
        self.author_label.grid(row=2, column=0, sticky="ew", padx=10, pady=0)
        self.author_tooltip = CTKTooltip(self.author_label, "")

        self.length_label = ctk.CTkLabel(self, text="Total Length: ---", anchor="w", font=("Inter", 11))
        self.length_label.grid(row=3, column=0, sticky="ew", padx=10, pady=0)

        self.selection_label = ctk.CTkLabel(self, text="Selection: ---", anchor="w", font=("Inter", 11, "bold"))
        self.selection_label.grid(row=4, column=0, sticky="ew", padx=10, pady=0)

        # Compact Debug Button
        self.debug_btn = ctk.CTkButton(self, text="🔍 Structure", width=80, height=22, font=("Inter", 11), command=self.on_debug)
        self.debug_btn.grid(row=5, column=0, sticky="w", padx=10, pady=(5, 10))

        # Reparse Controls (Hidden by default)
        self.reparse_container = ctk.CTkFrame(self, fg_color="transparent")
        # row 6, will be managed via grid/grid_forget
        
        self.reparse_label = ctk.CTkLabel(self.reparse_container, text="Manual Reparse:", font=("Inter", 11, "bold"))
        self.reparse_label.grid(row=0, column=0, sticky="w", padx=10, pady=(5, 2))
        
        self.reparse_frame = ctk.CTkFrame(self.reparse_container, fg_color="transparent")
        self.reparse_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 10))
        self.reparse_frame.grid_columnconfigure((0, 1, 2), weight=1)
        
        self.method1_btn = ctk.CTkButton(self.reparse_frame, text="Method 1", height=22, font=("Inter", 10), command=lambda: self.on_reparse(1))
        self.method1_btn.grid(row=0, column=0, padx=2)
        
        self.method2_btn = ctk.CTkButton(self.reparse_frame, text="Method 2", height=22, font=("Inter", 10), command=lambda: self.on_reparse(2))
        self.method2_btn.grid(row=0, column=1, padx=2)
        
        self.method3_btn = ctk.CTkButton(self.reparse_frame, text="Method 3", height=22, font=("Inter", 10), command=lambda: self.on_reparse(3))
        self.method3_btn.grid(row=0, column=2, padx=2)

        self.refresh_reparse_buttons()

    def on_reparse(self, method):
        if not hasattr(self.controller, 'selected_file_path') or not self.controller.selected_file_path:
            return
        print(f"Manually reparsing with Method {method}...")
        threading.Thread(target=self.controller._load_book_file_threaded, 
                         args=(self.controller.selected_file_path,), 
                         kwargs={'method': method}, daemon=True).start()

    def refresh_reparse_buttons(self):
        current = getattr(self.controller, 'current_parsing_method', 0)
        failed = getattr(self.controller, 'failed_methods', set())
        
        # Determine if we should show reparse buttons
        # They only apply to Experimental Track (non-pure)
        show_reparse = getattr(self.controller, 'experimental_mode_active', False)
        
        if show_reparse:
            self.reparse_container.grid(row=6, column=0, columnspan=2, sticky="ew")
        else:
            self.reparse_container.grid_forget()

        buttons = {1: self.method1_btn, 2: self.method2_btn, 3: self.method3_btn}
        labels = {1: "Standard", 2: "Zip", 3: "Calibre"}
        
        for m, btn in buttons.items():
            if m == current:
                btn.configure(state="disabled", fg_color="green", text=f"{labels[m]} ✓")
            elif m in failed:
                btn.configure(state="disabled", fg_color="#882222", text=f"{labels[m]} ✗")
            else:
                btn.configure(state="normal", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"], text=labels[m])

    def on_debug(self):
        if not hasattr(self.controller, 'selected_file_path') or not self.controller.selected_file_path:
             print("No book loaded.")
             return
        
        file_path = self.controller.selected_file_path
        default_name = f"{Path(file_path).stem}_skeleton.html"
        
        save_path = ctk.filedialog.asksaveasfilename(
            defaultextension=".html",
            initialfile=default_name,
            filetypes=[("HTML files", "*.html")]
        )
        
        if not save_path:
            return

        def run_debug():
            try:
                from audiblez.calibre_handler import open_book_experimental
                from audiblez.inspector import generate_report
                
                method = getattr(self.controller, 'current_parsing_method', 0)
                
                result, msg, chapters, metadata, cover = open_book_experimental(
                    file_path,
                    self.controller._ask_user_for_calibre_path_generic,
                    method=method,
                    include_skeleton=True
                )
                
                if chapters:
                    section_data = []
                    for ch in chapters:
                        if isinstance(ch, dict):
                            section_data.append(ch)
                        else:
                             section_data.append({
                                'title': getattr(ch, 'title', 'Chapter'),
                                'src': getattr(ch, 'src', 'N/A'),
                                'pre_chars': getattr(ch, 'pre_chars', 0),
                                'post_chars': getattr(ch, 'post_chars', 0),
                                'skeleton': getattr(ch, 'skeleton', '')
                            })
                    
                    meta_dict = {}
                    if isinstance(metadata, dict):
                        meta_dict = metadata
                    else:
                        meta_dict = {'title': str(metadata), 'creator': 'Unknown'}

                    generate_report(meta_dict, section_data, save_path)
                    print(f"Report generated: {save_path}")
                    self.open_folder(save_path)
                else:
                    print(f"Debug failed: {msg}")
            except Exception as e:
                print(f"Debug Error: {e}")

        threading.Thread(target=run_debug, daemon=True).start()

    def open_folder(self, path):
        folder = os.path.dirname(path)
        if platform.system() == "Windows":
            os.startfile(folder)
        elif platform.system() == "Darwin":
            subprocess.run(["open", folder])
        else:
            subprocess.run(["xdg-open", folder])

    def _truncate_text(self, text, max_chars=35):
        if not text: return "---"
        if len(text) <= max_chars:
            return text
        return text[:max_chars-3] + "..."

    def update_book_info(self, title, author, length, cover_data=None):
        self.full_title = title
        self.full_author = author
        
        self.title_label.configure(text=f"Title: {self._truncate_text(title)}")
        self.title_tooltip.text = title if len(title) > 32 else ""
        
        self.author_label.configure(text=f"Author: {self._truncate_text(author)}")
        self.author_tooltip.text = author if len(author) > 32 else ""
        
        self.length_label.configure(text=f"Total Length: {length:,} chars")
        
        if cover_data:
            try:
                pil_img = None
                if cover_data.get('type') == 'epub_cover' and cover_data.get('content'):
                    pil_img = Image.open(io.BytesIO(cover_data['content']))
                elif cover_data.get('type') == 'path' and cover_data.get('content'):
                    p = Path(cover_data['content'])
                    if p.exists():
                        pil_img = Image.open(p)
                
                if pil_img:
                    if pil_img.mode != "RGB":
                        pil_img = pil_img.convert("RGB")
                    
                    # Target width 90, calc height
                    w = 90
                    h = int(w * pil_img.height / pil_img.width)
                    if h > 130: # Cap height
                        h = 130
                        w = int(h * pil_img.width / pil_img.height)
                    
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(w, h))
                    self.cover_label.configure(image=ctk_img, text="", width=w, height=h)
                else:
                    self.cover_label.configure(image=None, text="No Cover")
            except Exception as e:
                print(f"Error loading cover: {e}")
                self.cover_label.configure(image=None, text="Error")
        else:
            self.cover_label.configure(image=None, text="No Cover")

    def update_selection_total(self, length):
        self.selection_label.configure(text=f"Selection: {length:,} chars")
