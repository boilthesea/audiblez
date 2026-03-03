import customtkinter as ctk
from PIL import Image
import io
from pathlib import Path
import threading
import os
import platform
import subprocess

class BookDetailsPanel(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.label = ctk.CTkLabel(self, text="Book Details", font=("Inter", 16, "bold"))
        self.label.grid(row=0, column=0, sticky="nw", padx=10, pady=5)

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.content.grid_columnconfigure(1, weight=1)

        # Cover Image Placeholder
        self.cover_label = ctk.CTkLabel(self.content, text="No Cover Art", width=120, height=180, fg_color="#333333")
        self.cover_label.grid(row=0, column=0, rowspan=4, padx=(0, 10), pady=10)

        # Metadata
        self.title_label = ctk.CTkLabel(self.content, text="Title: ---", anchor="w")
        self.title_label.grid(row=0, column=1, sticky="ew")

        self.author_label = ctk.CTkLabel(self.content, text="Author: ---", anchor="w")
        self.author_label.grid(row=1, column=1, sticky="ew")

        self.length_label = ctk.CTkLabel(self.content, text="Total Length: ---", anchor="w")
        self.length_label.grid(row=2, column=1, sticky="ew")

        self.debug_btn = ctk.CTkButton(self.content, text="🔍 Debug Structure", command=self.on_debug)
        self.debug_btn.grid(row=3, column=1, sticky="ew", pady=(10, 0))

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
                
                method = getattr(self.controller, 'current_parsing_method', 0) + 1
                
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

    def update_book_info(self, title, author, length, cover_data=None):
        self.title_label.configure(text=f"Title: {title}")
        self.author_label.configure(text=f"Author: {author}")
        self.length_label.configure(text=f"Total Length: {length:,} characters")
        
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
                    # Convert to RGB if necessary
                    if pil_img.mode != "RGB":
                        pil_img = pil_img.convert("RGB")
                    
                    # Calculate size (maintaining aspect ratio, max height 180)
                    h = 180
                    w = int(h * pil_img.width / pil_img.height)
                    
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(w, h))
                    self.cover_label.configure(image=ctk_img, text="")
                else:
                    self.cover_label.configure(image=None, text="No Cover Art")
            except Exception as e:
                print(f"Error loading cover: {e}")
                self.cover_label.configure(image=None, text="Error Loading Cover")
        else:
            self.cover_label.configure(image=None, text="No Cover Art")
