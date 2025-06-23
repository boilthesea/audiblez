#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# A simple wxWidgets UI for audiblez

import torch.cuda
import numpy as np
import soundfile
import threading
import platform
import subprocess
import io
import os
import wx
import wx.adv # For DatePickerCtrl, TimePickerCtrl
from datetime import datetime, time as dt_time # For schedule dialog
from wx.lib.newevent import NewEvent
from wx.lib.scrolledpanel import ScrolledPanel
from PIL import Image
from tempfile import NamedTemporaryFile
from pathlib import Path
import audiblez.database as db # Changed import for clarity
import json # For settings

from audiblez.voices import voices, flags
# from audiblez.database import load_all_user_settings, save_user_setting # Now use db. prefix

EVENTS = {
    'CORE_STARTED': NewEvent(),
    'CORE_PROGRESS': NewEvent(),
    'CORE_CHAPTER_STARTED': NewEvent(),
    'CORE_CHAPTER_FINISHED': NewEvent(),
    'CORE_FINISHED': NewEvent()
}

border = 5


class MainWindow(wx.Frame):
    def __init__(self, parent, title):
        screen_width, screen_h = wx.GetDisplaySize()
        self.window_width = int(screen_width * 0.6)
        super().__init__(parent, title=title, size=(self.window_width, self.window_width * 3 // 4))
        self.chapters_panel = None
        self.preview_threads = []
        self.selected_chapter = None
        self.selected_book = None
        self.synthesis_in_progress = False

        self.Bind(EVENTS['CORE_STARTED'][1], self.on_core_started)
        self.Bind(EVENTS['CORE_CHAPTER_STARTED'][1], self.on_core_chapter_started)
        self.Bind(EVENTS['CORE_CHAPTER_FINISHED'][1], self.on_core_chapter_finished)
        self.Bind(EVENTS['CORE_PROGRESS'][1], self.on_core_progress)
        self.Bind(EVENTS['CORE_FINISHED'][1], self.on_core_finished)

        self.create_menu()
        self.create_layout()

        # Load user settings
        self.user_settings = db.load_all_user_settings() # Use db prefix
        if not self.user_settings: # Ensure it's a dict
            self.user_settings = {}

        # Initialize core attributes that will be set by UI controls,
        # potentially using loaded settings or defaults.
        # These will be properly set in create_params_panel and create_synthesis_panel
        self.selected_voice = None
        self.selected_speed = 1.0 # Default speed
        self.custom_rate = None # Default custom rate

        self.queue_processing_active = False
        self.current_queue_item_index = -1 # To track which item in self.queue_items is being processed
        self.run_queue_button = None # To enable/disable run queue button
        self.schedule_queue_button = None # For scheduling
        self.scheduled_time_text = None # To display scheduled time

        # Load queue from database on startup
        self.queue_items = db.get_queued_items()

        self.Centre()
        self.Show(True)

        # Ensure notebook and tabs are created, then refresh them.
        self.create_notebook_and_tabs()
        wx.CallAfter(self._initial_ui_refresh) # Refresh tabs after UI is fully up

        # Initialize and start schedule checker
        self.schedule_check_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_check_schedule_timer, self.schedule_check_timer)
        self.start_schedule_check_timer()

        # Bind close event to stop timer
        self.Bind(wx.EVT_CLOSE, self.on_close_window)

        default_epub_path = Path('../epub/lewis.epub')
        if default_epub_path.exists():
            wx.CallAfter(self.open_epub, str(default_epub_path))


    def on_close_window(self, event):
        if self.schedule_check_timer.IsRunning():
            self.schedule_check_timer.Stop()
        # Add any other cleanup needed before closing
        self.Destroy() # Proceed with closing


    def _initial_ui_refresh(self):
        if not hasattr(self, 'notebook'):
            print("Notebook not created, cannot perform initial UI refresh.")
            return
        self.refresh_queue_tab()
        self.refresh_staging_tab()


    def create_notebook_and_tabs(self):
        if hasattr(self, 'notebook') and self.notebook:
            # Notebook and basic tabs might have been created by a previous call or open_epub
            # Ensure sizers exist if we are re-entering or setting up lazily
            if not hasattr(self, 'queue_tab_sizer') and hasattr(self, 'queue_tab_panel') and self.queue_tab_panel:
                self.queue_tab_sizer = wx.BoxSizer(wx.VERTICAL)
                self.queue_tab_panel.SetSizer(self.queue_tab_sizer)
            if not hasattr(self, 'staging_tab_sizer') and hasattr(self, 'staging_tab_panel') and self.staging_tab_panel:
                self.staging_tab_sizer = wx.BoxSizer(wx.VERTICAL)
                self.staging_tab_panel.SetSizer(self.staging_tab_sizer)
            return

        if not hasattr(self, 'splitter_left') or not self.splitter_left:
            if not hasattr(self, 'splitter') or not self.splitter:
                 print("Error: Main splitter panel does not exist. Cannot create notebook.")
                 return
            self.splitter_left = wx.Panel(self.splitter, -1)
            self.left_sizer = wx.BoxSizer(wx.VERTICAL)
            self.splitter_left.SetSizer(self.left_sizer)
            # Add splitter_left to the main splitter_sizer
            self.splitter_sizer.Add(self.splitter_left, 1, wx.ALL | wx.EXPAND, 5)

        self.notebook = wx.Notebook(self.splitter_left)

        # Chapters Tab
        self.chapters_tab_page = wx.Panel(self.notebook)
        self.notebook.AddPage(self.chapters_tab_page, "Chapters")
        chapters_page_sizer = wx.BoxSizer(wx.VERTICAL) # Create sizer for chapters page
        self.chapters_tab_page.SetSizer(chapters_page_sizer) # Set sizer
        if not hasattr(self, 'chapters_panel'): # If open_epub hasn't run
            placeholder_text = wx.StaticText(self.chapters_tab_page, label="Open an EPUB file to see chapters here.")
            chapters_page_sizer.Add(placeholder_text, 0, wx.ALL | wx.ALIGN_CENTER, 15)
            self.chapters_tab_page.Layout()

        # Staging Tab Panel
        self.staging_tab_panel = ScrolledPanel(self.notebook, -1, style=wx.TAB_TRAVERSAL | wx.SUNKEN_BORDER)
        self.staging_tab_sizer = wx.BoxSizer(wx.VERTICAL)
        self.staging_tab_panel.SetSizer(self.staging_tab_sizer)
        self.notebook.AddPage(self.staging_tab_panel, "Staging")
        if not self.staging_tab_sizer.GetChildren():
            placeholder_staging = wx.StaticText(self.staging_tab_panel, label="Staged books will appear here.")
            self.staging_tab_sizer.Add(placeholder_staging, 0, wx.ALL | wx.ALIGN_CENTER, 15)
            self.staging_tab_panel.Layout()
            self.staging_tab_panel.SetupScrolling()

        # Queue Tab Panel
        self.queue_tab_panel = ScrolledPanel(self.notebook, -1, style=wx.TAB_TRAVERSAL | wx.SUNKEN_BORDER)
        self.queue_tab_sizer = wx.BoxSizer(wx.VERTICAL)
        self.queue_tab_panel.SetSizer(self.queue_tab_sizer)
        self.notebook.AddPage(self.queue_tab_panel, "Queue")
        if not self.queue_tab_sizer.GetChildren():
            print("DEBUG: Creating initial placeholder for Queue tab.")
            placeholder_queue = wx.StaticText(self.queue_tab_panel, label="Queued items will appear here.")
            self.queue_tab_sizer.Add(placeholder_queue, 0, wx.ALL | wx.ALIGN_CENTER, 15)
            self.queue_tab_panel.Layout()
            self.queue_tab_panel.SetupScrolling()

        self.left_sizer.Add(self.notebook, 1, wx.ALL | wx.EXPAND, 5)

        if hasattr(self.splitter_left, 'Layout'): self.splitter_left.Layout()
        if hasattr(self.splitter, 'Layout'): self.splitter.Layout()
        self.Layout()


    def create_menu(self):
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        open_item = wx.MenuItem(file_menu, wx.ID_OPEN, "&Open\tCtrl+O")
        file_menu.Append(open_item)
        self.Bind(wx.EVT_MENU, self.on_open, open_item)  # Bind the event

        exit_item = wx.MenuItem(file_menu, wx.ID_EXIT, "&Exit\tCtrl+Q")
        file_menu.Append(exit_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)

        menubar.Append(file_menu, "&File")
        self.SetMenuBar(menubar)

    def on_core_started(self, event):
        print('CORE_STARTED')
        self.progress_bar_label.Show()
        self.progress_bar.Show()
        self.progress_bar.SetValue(0)
        self.progress_bar.Layout()
        self.eta_label.Show()
        self.params_panel.Layout()
        self.synth_panel.Layout()

    def on_core_chapter_started(self, event):
        # print('CORE_CHAPTER_STARTED', event.chapter_index)
        self.set_table_chapter_status(event.chapter_index, "⏳ In Progress")

    def on_core_chapter_finished(self, event):
        # print('CORE_CHAPTER_FINISHED', event.chapter_index)
        self.set_table_chapter_status(event.chapter_index, "✅ Done")
        self.start_button.Show()

    def on_core_progress(self, event):
        # print('CORE_PROGRESS', event.progress)
        self.progress_bar.SetValue(event.stats.progress)
        self.progress_bar_label.SetLabel(f"Synthesis Progress: {event.stats.progress}%")
        self.eta_label.SetLabel(f"Estimated Time Remaining: {event.stats.eta}")
        self.synth_panel.Layout()

    def on_core_finished(self, event):
        self.synthesis_in_progress = False # This is for single book synthesis
        # For queue, self.queue_processing_active is used.

        # If queue was active, on_core_finished handles the next item or cleanup
        if self.queue_processing_active:
            if self.current_queue_item_index < len(self.queue_items):
                 # Update status of the completed item
                item_data = self.queue_items[self.current_queue_item_index] # This is a reference from self.queue_items
                # Ensure 'id' exists, as it's crucial for DB updates.
                if 'id' in item_data:
                    # Check if CoreThread passed an error status
                    if hasattr(event, 'error_message') and event.error_message:
                        db.update_queue_item_status(item_data['id'], 'error')
                        item_data['status'] = f"⚠️ Error ({event.error_message})"
                        print(f"Error processing queue item {item_data['id']}: {event.error_message}")
                    else:
                        db.update_queue_item_status(item_data['id'], 'completed')
                        item_data['status'] = "✅ Completed"

                        # If completed, update status of staged chapters in DB and refresh staging UI
                        processed_staged_chapter_ids = []
                        for chap_info in item_data.get('chapters', []):
                            staged_chapter_id = chap_info.get('staged_chapter_id')
                            if staged_chapter_id:
                                db.update_staged_chapter_status_in_db(staged_chapter_id, 'completed')
                                processed_staged_chapter_ids.append(staged_chapter_id)
                        if processed_staged_chapter_ids:
                            self.update_staging_tab_for_processed_chapters(processed_staged_chapter_ids)
                else:
                    print(f"Error: Queue item {item_data.get('book_title')} missing 'id', cannot update DB status.")

            # Try to process the next item
            self.current_queue_item_index += 1
            self.process_next_queue_item() # This method will handle actual processing
        else:
            # This was a single synthesis, not from queue
            self.open_folder_with_explorer(self.output_folder_text_ctrl.GetValue())
            # Re-enable start button and params if it was a single synthesis
            self.start_button.Enable()
            self.params_panel.Enable()
            self.table.EnableCheckBoxes(True)


    def create_layout(self):
        # Panels layout looks like this:
        # splitter
        #     splitter_left
        #         chapters_panel
        #     splitter_right
        #         center_panel
        #             text_area
        #         right_panel
        #             book_info_panel_box
        #                 book_info_panel
        #                     cover_bitmap
        #                     book_details_panel
        #             param_panel_box
        #                  param_panel
        #                      ...
        #             synth_panel_box
        #                  synth_panel
        #                      start_button
        #                      ...

        top_panel = wx.Panel(self)
        top_sizer = wx.BoxSizer(wx.HORIZONTAL)
        top_panel.SetSizer(top_sizer)

        # Open Epub button
        open_epub_button = wx.Button(top_panel, label="📁 Open EPUB")
        open_epub_button.Bind(wx.EVT_BUTTON, self.on_open)
        top_sizer.Add(open_epub_button, 0, wx.ALL, 5)

        # Open Markdown .md
        # open_md_button = wx.Button(top_panel, label="📁 Open Markdown (.md)")
        # open_md_button.Bind(wx.EVT_BUTTON, self.on_open)
        # top_sizer.Add(open_md_button, 0, wx.ALL, 5)

        # Open .txt
        # open_txt_button = wx.Button(top_panel, label="📁 Open .txt")
        # open_txt_button.Bind(wx.EVT_BUTTON, self.on_open)
        # top_sizer.Add(open_txt_button, 0, wx.ALL, 5)

        # Open PDF
        # open_pdf_button = wx.Button(top_panel, label="📁 Open PDF")
        # open_pdf_button.Bind(wx.EVT_BUTTON, self.on_open)
        # top_sizer.Add(open_pdf_button, 0, wx.ALL, 5)

        # About button
        help_button = wx.Button(top_panel, label="ℹ️ About")
        help_button.Bind(wx.EVT_BUTTON, lambda event: self.about_dialog())
        top_sizer.Add(help_button, 0, wx.ALL, 5)

        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.main_sizer)

        # self.splitter = wx.SplitterWindow(self, -1)
        # self.splitter.SetSashGravity(0.9)
        self.splitter = wx.Panel(self)
        self.splitter_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.splitter.SetSizer(self.splitter_sizer)

        self.main_sizer.Add(top_panel, 0, wx.ALL | wx.EXPAND, 5)
        self.main_sizer.Add(self.splitter, 1, wx.EXPAND) # self.splitter is a Panel that will be split by self.splitter_sizer

        # self.splitter_left, self.splitter_right, and self.notebook are NOT created here.
        # They will be created in open_epub().
        # The main area (self.splitter) will be empty initially below the top_panel.

    def create_layout_for_ebook(self, splitter_container): # splitter_container is self.splitter (the main one)
        # This function is called from open_epub, after self.splitter_left and self.notebook are created.
        # It populates the "Chapters" tab and creates/populates self.splitter_right.

        # 1. Populate the "Chapters" tab (self.chapters_tab_page)
        # self.chapters_tab_page is a wx.Panel created in open_epub, acting as a container for the chapter list.

        # Clear any old content from this page container
        for child in self.chapters_tab_page.GetChildren():
            child.Destroy()

        # Create the actual chapters list panel (ScrolledPanel) using create_chapters_table_panel.
        # Its parent will be self.chapters_tab_page.
        # self.document_chapters is assumed to be set by open_epub.
        # good_chapters logic is handled within create_chapters_table_panel.
        self.chapters_panel = self.create_chapters_table_panel(self.document_chapters) # This returns the ScrolledPanel

        # Add this ScrolledPanel (self.chapters_panel) to the sizer of self.chapters_tab_page
        chapters_page_sizer = wx.BoxSizer(wx.VERTICAL)
        chapters_page_sizer.Add(self.chapters_panel, 1, wx.EXPAND | wx.ALL) # Add the ScrolledPanel
        self.chapters_tab_page.SetSizer(chapters_page_sizer)
        self.chapters_tab_page.Layout()

        # 2. Create and populate self.splitter_right
        # self.splitter_right should not exist at this point due to cleanup in open_epub
        self.splitter_right = wx.Panel(splitter_container) # Parent is self.splitter
        self.splitter_sizer.Add(self.splitter_right, 2, wx.ALL | wx.EXPAND, 5) # Add to main splitter sizer

        # Now, create the content for self.splitter_right: center_panel and right_panel
        # (These are for text_area, book details, params, synth status)
        self.center_panel = wx.Panel(self.splitter_right) # Parent is self.splitter_right
        self.center_sizer = wx.BoxSizer(wx.VERTICAL)
        self.center_panel.SetSizer(self.center_sizer)
        self.text_area = wx.TextCtrl(self.center_panel, style=wx.TE_MULTILINE, size=(int(self.window_width * 0.4), -1))
        font = wx.Font(14, wx.MODERN, wx.NORMAL, wx.NORMAL)
        self.text_area.SetFont(font)
        # On text change, update the extracted_text attribute of the selected_chapter:
        self.text_area.Bind(wx.EVT_TEXT, lambda event: setattr(self.selected_chapter, 'extracted_text', self.text_area.GetValue()))

        self.chapter_label = wx.StaticText(
            self.center_panel, label=f'Edit / Preview content for section "{self.selected_chapter.short_name}":')
        preview_button = wx.Button(self.center_panel, label="🔊 Preview")
        preview_button.Bind(wx.EVT_BUTTON, self.on_preview_chapter)

        self.center_sizer.Add(self.chapter_label, 0, wx.ALL, 5)
        self.center_sizer.Add(preview_button, 0, wx.ALL, 5)
        self.center_sizer.Add(self.text_area, 1, wx.ALL | wx.EXPAND, 5)

        splitter_right_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.splitter_right.SetSizer(splitter_right_sizer) # Use self.splitter_right

        self.create_right_panel(self.splitter_right) # Use self.splitter_right
        splitter_right_sizer.Add(self.center_panel, 1, wx.ALL | wx.EXPAND, 5)
        splitter_right_sizer.Add(self.right_panel, 1, wx.ALL | wx.EXPAND, 5)

    def about_dialog(self):
        msg = ("A simple tool to generate audiobooks from EPUB files using Kokoro-82M models\n" +
               "Distributed under the MIT License.\n\n" +
               "by Claudio Santini 2025\nand many contributors.\n\n" +
               "https://claudio.uk\n\n")
        wx.MessageBox(msg, "Audiblez")

    def create_right_panel(self, splitter_right):
        self.right_panel = wx.Panel(splitter_right)
        self.right_sizer = wx.BoxSizer(wx.VERTICAL)
        self.right_panel.SetSizer(self.right_sizer)

        self.book_info_panel_box = wx.Panel(self.right_panel, style=wx.SUNKEN_BORDER)
        book_info_panel_box_sizer = wx.StaticBoxSizer(wx.VERTICAL, self.book_info_panel_box, "Book Details")
        self.book_info_panel_box.SetSizer(book_info_panel_box_sizer)
        self.right_sizer.Add(self.book_info_panel_box, 1, wx.ALL | wx.EXPAND, 5)

        self.book_info_panel = wx.Panel(self.book_info_panel_box, style=wx.BORDER_NONE)
        self.book_info_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.book_info_panel.SetSizer(self.book_info_sizer)
        book_info_panel_box_sizer.Add(self.book_info_panel, 1, wx.ALL | wx.EXPAND, 5)

        # Add cover image
        self.cover_bitmap = wx.StaticBitmap(self.book_info_panel, -1)
        self.book_info_sizer.Add(self.cover_bitmap, 0, wx.ALL, 5)

        self.cover_bitmap.Refresh()
        self.book_info_panel.Refresh()
        self.book_info_panel.Layout()
        self.cover_bitmap.Layout()

        self.create_book_details_panel()
        self.create_params_panel()
        self.create_synthesis_panel()

    def create_book_details_panel(self):
        book_details_panel = wx.Panel(self.book_info_panel)
        book_details_sizer = wx.GridBagSizer(10, 10)
        book_details_panel.SetSizer(book_details_sizer)
        self.book_info_sizer.Add(book_details_panel, 1, wx.ALL | wx.EXPAND, 5)

        # Add title
        title_label = wx.StaticText(book_details_panel, label="Title:")
        title_text = wx.StaticText(book_details_panel, label=self.selected_book_title)
        book_details_sizer.Add(title_label, pos=(0, 0), flag=wx.ALL, border=5)
        book_details_sizer.Add(title_text, pos=(0, 1), flag=wx.ALL, border=5)

        # Add Author
        author_label = wx.StaticText(book_details_panel, label="Author:")
        author_text = wx.StaticText(book_details_panel, label=self.selected_book_author)
        book_details_sizer.Add(author_label, pos=(1, 0), flag=wx.ALL, border=5)
        book_details_sizer.Add(author_text, pos=(1, 1), flag=wx.ALL, border=5)

        # Add Total length
        length_label = wx.StaticText(book_details_panel, label="Total Length:")
        if not hasattr(self, 'document_chapters'):
            total_len = 0
        else:
            total_len = sum([len(c.extracted_text) for c in self.document_chapters])
        length_text = wx.StaticText(book_details_panel, label=f'{total_len:,} characters')
        book_details_sizer.Add(length_label, pos=(2, 0), flag=wx.ALL, border=5)
        book_details_sizer.Add(length_text, pos=(2, 1), flag=wx.ALL, border=5)

    def create_params_panel(self):
        panel_box = wx.Panel(self.right_panel, style=wx.SUNKEN_BORDER)
        panel_box_sizer = wx.StaticBoxSizer(wx.VERTICAL, panel_box, "Audiobook Parameters")
        panel_box.SetSizer(panel_box_sizer)

        panel = self.params_panel = wx.Panel(panel_box)
        panel_box_sizer.Add(panel, 1, wx.ALL | wx.EXPAND, 5)
        self.right_sizer.Add(panel_box, 1, wx.ALL | wx.EXPAND, 5)
        sizer = wx.GridBagSizer(10, 10)
        panel.SetSizer(sizer)

        engine_label = wx.StaticText(panel, label="Engine:")
        engine_radio_panel = wx.Panel(panel)
        self.cpu_radio = wx.RadioButton(engine_radio_panel, label="CPU", style=wx.RB_GROUP)
        self.cuda_radio = wx.RadioButton(engine_radio_panel, label="CUDA")

        # Load saved engine or set default
        saved_engine = self.user_settings.get('engine')
        if saved_engine == 'cpu':
            self.cpu_radio.SetValue(True)
            torch.set_default_device('cpu')
        elif saved_engine == 'cuda' and torch.cuda.is_available():
            self.cuda_radio.SetValue(True)
            torch.set_default_device('cuda')
        elif torch.cuda.is_available(): # Default to CUDA if available and no setting
            self.cuda_radio.SetValue(True)
            torch.set_default_device('cuda')
        else: # Default to CPU
            self.cpu_radio.SetValue(True)
            torch.set_default_device('cpu')

        # if not torch.cuda.is_available():
            # self.cuda_radio.Disable() # Optional: disable if no CUDA

        sizer.Add(engine_label, pos=(0, 0), flag=wx.ALL, border=border)
        sizer.Add(engine_radio_panel, pos=(0, 1), flag=wx.ALL, border=border)
        engine_radio_panel_sizer = wx.BoxSizer(wx.HORIZONTAL)
        engine_radio_panel.SetSizer(engine_radio_panel_sizer)
        engine_radio_panel_sizer.Add(self.cpu_radio, 0, wx.ALL, 5)
        engine_radio_panel_sizer.Add(self.cuda_radio, 0, wx.ALL, 5)

        def on_select_engine(event, engine_type):
            torch.set_default_device(engine_type)
            db.save_user_setting('engine', engine_type) # Use db prefix
            print(f"Engine set to {engine_type} and saved.")

        self.cpu_radio.Bind(wx.EVT_RADIOBUTTON, lambda event: on_select_engine(event, 'cpu'))
        self.cuda_radio.Bind(wx.EVT_RADIOBUTTON, lambda event: on_select_engine(event, 'cuda'))

        # Create a list of voices with flags
        flag_and_voice_list = []
        for code, l in voices.items():
            for v in l:
                flag_and_voice_list.append(f'{flags[code]} {v}')

        voice_label = wx.StaticText(panel, label="Voice:")
        # Determine default/saved voice
        saved_voice = self.user_settings.get('voice')
        if saved_voice and saved_voice in flag_and_voice_list:
            self.selected_voice = saved_voice
        else:
            self.selected_voice = flag_and_voice_list[0] if flag_and_voice_list else ""

        self.voice_dropdown = wx.ComboBox(panel, choices=flag_and_voice_list, value=self.selected_voice)
        self.voice_dropdown.Bind(wx.EVT_COMBOBOX, self.on_select_voice)
        sizer.Add(voice_label, pos=(1, 0), flag=wx.ALL, border=border)
        sizer.Add(self.voice_dropdown, pos=(1, 1), flag=wx.ALL, border=border)

        # Add text input for speed
        speed_label = wx.StaticText(panel, label="Speed:")
        saved_speed = self.user_settings.get('speed')
        if saved_speed is not None:
            try:
                self.selected_speed = float(saved_speed)
            except ValueError:
                self.selected_speed = 1.0 # Default if conversion fails
        else:
            self.selected_speed = 1.0 # Default if not set

        self.speed_text_input = wx.TextCtrl(panel, value=str(self.selected_speed))
        self.speed_text_input.Bind(wx.EVT_TEXT, self.on_select_speed)
        sizer.Add(speed_label, pos=(2, 0), flag=wx.ALL, border=border)
        sizer.Add(self.speed_text_input, pos=(2, 1), flag=wx.ALL, border=border)

        # Add file dialog selector to select output folder
        output_folder_label = wx.StaticText(panel, label="Output Folder:")
        self.output_folder_text_ctrl = wx.TextCtrl(panel, value=os.path.abspath('.'))
        self.output_folder_text_ctrl.SetEditable(False)
        # self.output_folder_text_ctrl.SetMinSize((200, -1))
        output_folder_button = wx.Button(panel, label="📂 Select")
        output_folder_button.Bind(wx.EVT_BUTTON, self.open_output_folder_dialog)
        sizer.Add(output_folder_label, pos=(3, 0), flag=wx.ALL, border=border)
        sizer.Add(self.output_folder_text_ctrl, pos=(3, 1), flag=wx.ALL | wx.EXPAND, border=border)
        sizer.Add(output_folder_button, pos=(4, 1), flag=wx.ALL, border=border)

    def create_synthesis_panel(self):
        # Think and identify layout issue with the folling code
        panel_box = wx.Panel(self.right_panel, style=wx.SUNKEN_BORDER)
        panel_box_sizer = wx.StaticBoxSizer(wx.VERTICAL, panel_box, "Audiobook Generation Status")
        panel_box.SetSizer(panel_box_sizer)

        panel = self.synth_panel = wx.Panel(panel_box)
        panel_box_sizer.Add(panel, 1, wx.ALL | wx.EXPAND, 5)
        self.right_sizer.Add(panel_box, 1, wx.ALL | wx.EXPAND, 5)
        sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(sizer)

        # Add Start button
        self.start_button = wx.Button(panel, label="🚀 Start Audiobook Synthesis")
        self.start_button.Bind(wx.EVT_BUTTON, self.on_start)
        sizer.Add(self.start_button, 0, wx.ALL, 5)

        # Add Stop button
        # self.stop_button = wx.Button(panel, label="⏹️ Stop Synthesis")
        # self.stop_button.Bind(wx.EVT_BUTTON, self.on_stop)
        # sizer.Add(self.stop_button, 0, wx.ALL, 5)
        # self.stop_button.Hide()

        # Add Progress Bar label:
        self.progress_bar_label = wx.StaticText(panel, label="Synthesis Progress:")
        sizer.Add(self.progress_bar_label, 0, wx.ALL, 5)
        self.progress_bar = wx.Gauge(panel, range=100, style=wx.GA_PROGRESS)
        self.progress_bar.SetMinSize((-1, 30))
        sizer.Add(self.progress_bar, 0, wx.ALL | wx.EXPAND, 5)
        self.progress_bar_label.Hide()
        self.progress_bar.Hide()

        # Add ETA Label
        self.eta_label = wx.StaticText(panel, label="Estimated Time Remaining: ")
        self.eta_label.Hide()
        sizer.Add(self.eta_label, 0, wx.ALL, 5)

        # Add Custom Rate input
        custom_rate_label = wx.StaticText(panel, label="Custom Rate (chars/sec, experimental):")
        sizer.Add(custom_rate_label, 0, wx.ALL, 5)

        saved_custom_rate = self.user_settings.get('custom_rate')
        initial_custom_rate_value = ""
        if saved_custom_rate is not None:
            try:
                self.custom_rate = int(saved_custom_rate)
                initial_custom_rate_value = str(self.custom_rate)
            except ValueError:
                self.custom_rate = None # Or a default int like 750
                print(f"Warning: Could not parse saved custom_rate '{saved_custom_rate}'")
        else:
            self.custom_rate = None # Default if not set

        self.custom_rate_text_ctrl = wx.TextCtrl(panel, value=initial_custom_rate_value)
        self.custom_rate_text_ctrl.Bind(wx.EVT_TEXT, self.on_set_custom_rate)
        sizer.Add(self.custom_rate_text_ctrl, 0, wx.ALL | wx.EXPAND, 5)

    def open_output_folder_dialog(self, event):
        with wx.DirDialog(self, "Choose a directory:", style=wx.DD_DEFAULT_STYLE) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return
            output_folder = dialog.GetPath()
            print(f"Selected output folder: {output_folder}")
            self.output_folder_text_ctrl.SetValue(output_folder)

    def on_select_voice(self, event):
        self.selected_voice = event.GetString()
        db.save_user_setting('voice', self.selected_voice) # Use db prefix
        print(f"Voice set to {self.selected_voice} and saved.")

    def on_set_custom_rate(self, event):
        rate_str = event.GetString()
        if not rate_str: # Empty input
            self.custom_rate = None
            db.save_user_setting('custom_rate', None) # Use db prefix
            print("Custom rate cleared and saved.")
            return

        try:
            rate = int(rate_str)
            if rate > 0:
                self.custom_rate = rate
                db.save_user_setting('custom_rate', self.custom_rate) # Use db prefix
                print(f"Custom rate set to {self.custom_rate} and saved.")
            # else: # Negative or zero, could show an error or ignore
            #    print(f"Invalid custom rate (must be positive): {rate_str}")
            #    if self.custom_rate is not None: # Reset to last valid or None
            #       self.custom_rate_text_ctrl.SetValue(str(self.custom_rate) if self.custom_rate else "")
            #    else:
            #       self.custom_rate_text_ctrl.SetValue("")

        except ValueError:
            # Non-integer input, ignore for now or show error
            print(f"Invalid custom rate input (must be an integer): {rate_str}")
            # Optionally reset text ctrl to last valid self.custom_rate or empty
            # if self.custom_rate is not None:
            #    self.custom_rate_text_ctrl.SetValue(str(self.custom_rate))
            # else:
            #    self.custom_rate_text_ctrl.SetValue("")


    def on_select_speed(self, event):
        try:
            speed_str = event.GetString()
            # Allow empty string or partial input without immediate error
            if not speed_str:
                # self.selected_speed remains unchanged or you can set a temp invalid state
                return

            speed = float(speed_str)
            if speed > 0: # Basic validation
                self.selected_speed = speed
                db.save_user_setting('speed', self.selected_speed) # Use db prefix
                print(f'Selected speed {self.selected_speed} and saved.')
            # else: provide feedback for invalid speed if desired
        except ValueError:
            # Handle cases like "1.a" - often wx yields char by char
            # For now, just print error or ignore. User will see input not fully numeric.
            print(f"Invalid speed input: {event.GetString()}")
            # Optionally, reset to last valid speed or show error in UI

    def open_epub(self, file_path):
        # Cleanup previous dynamic UI parts if they exist
        if hasattr(self, 'splitter_left') and self.splitter_left:
            self.splitter_left.Destroy()
            self.splitter_left = None # Ensure it's cleared
        if hasattr(self, 'splitter_right') and self.splitter_right:
            self.splitter_right.Destroy()
            self.splitter_right = None # Ensure it's cleared
        # Note: Destroying children of splitter_sizer is implicitly handled by destroying splitter_left/right windows.
        # self.splitter_sizer.Clear(delete_windows=True) # Alternative, but Destroy() above is often better.

        self.selected_file_path = file_path
        print(f"Opening file: {file_path}")

        from ebooklib import epub
        from audiblez.core import find_document_chapters_and_extract_texts, find_good_chapters, find_cover

        # Parse EPUB and extract metadata ONCE
        book = epub.read_epub(file_path)
        meta_title = book.get_metadata('DC', 'title')
        self.selected_book_title = meta_title[0][0] if meta_title else ''
        meta_creator = book.get_metadata('DC', 'creator')
        self.selected_book_author = meta_creator[0][0] if meta_creator else ''
        self.selected_book = book

        # Determine document chapters ONCE
        self.document_chapters = find_document_chapters_and_extract_texts(book)

        # Determine good chapters list ONCE and store as instance variable
        self.good_chapters_list = find_good_chapters(self.document_chapters)

        # Determine selected_chapter based on good_chapters_list or document_chapters
        if self.good_chapters_list:
            self.selected_chapter = self.good_chapters_list[0]
        elif self.document_chapters: # Fallback if no good chapters but document chapters exist
            self.selected_chapter = self.document_chapters[0]
        else:
            self.selected_chapter = None
            # Consider: wx.LogWarning("No chapters found in the EPUB.") or similar feedback.

        # Process all chapters for short_name and initial selection status ONCE
        for chapter in self.document_chapters:
            chapter.short_name = chapter.get_name().replace('.xhtml', '').replace('xhtml/', '').replace('.html', '').replace('Text/', '')
            chapter.is_selected = chapter in self.good_chapters_list # Use instance var for consistency

        # Create/ensure notebook and tab structure exists
        self.create_notebook_and_tabs()

        # Create right panel and populate chapters tab (which is inside the notebook)
        self.create_layout_for_ebook(self.splitter) # self.splitter is the parent for splitter_right

        # Update Cover (ensure self.cover_bitmap exists, created in create_right_panel part of create_layout_for_ebook)
        if hasattr(self, 'cover_bitmap'):
            cover = find_cover(book)
            if cover is not None:
                pil_image = Image.open(io.BytesIO(cover.content))
                wx_img = wx.EmptyImage(pil_image.size[0], pil_image.size[1])
                wx_img.SetData(pil_image.convert("RGB").tobytes())
                cover_h = 200
                cover_w = int(cover_h * pil_image.size[0] / pil_image.size[1])
                wx_img.Rescale(cover_w, cover_h)
                self.cover_bitmap.SetBitmap(wx_img.ConvertToBitmap())
                self.cover_bitmap.SetMaxSize((200, cover_h))
            else:
                self.cover_bitmap.SetBitmap(wx.NullBitmap) # Clear old cover

        self.refresh_staging_tab() # Now that staging_tab_panel exists
        self.refresh_queue_tab() # Initial call to set up the queue tab

        self.splitter.Layout() # Layout the main splitter panel
        self.Layout() # Layout the main frame

    def refresh_queue_tab(self):
        # Clear existing content from the queue_tab_panel's sizer
        print(f"DEBUG: refresh_queue_tab called. self.queue_items: {self.queue_items}")
        if hasattr(self, 'queue_tab_sizer') and self.queue_tab_sizer:
            # Clear the sizer and delete all windows it managed.
            # This is the most common and robust way to reset a sizer's content.
            self.queue_tab_sizer.Clear(delete_windows=True)
            print("DEBUG: Called self.queue_tab_sizer.Clear(delete_windows=True)")
            # Any windows previously in the sizer (like individual queue item boxes,
            # the 'empty queue' text, or the run_queue_button if it was part of it)
            # are now destroyed. They will be recreated as needed below.
            # If self.run_queue_button was a child and was part of this sizer,
            # it is now destroyed, and self.run_queue_button would be a stale reference.
            # The existing logic for creating/showing the button later in this method
            # (e.g., `if not self.run_queue_button:`) should ideally handle
            # the recreation if self.run_queue_button becomes None or if operations on a stale
            # reference lead to expected errors that are gracefully handled.
            # For now, we rely on Clear() to do its job and the subsequent button logic
            # to correctly reconstruct or re-add the button.

        if not self.queue_items:
            no_items_label = wx.StaticText(self.queue_tab_panel, label="The synthesis queue is empty.")
            self.queue_tab_sizer.Add(no_items_label, 0, wx.ALL | wx.ALIGN_CENTER, 15)
            print("DEBUG: Queue is empty, adding placeholder label.")
        else:
            for item_idx, item_data in enumerate(self.queue_items):
                print(f"DEBUG: Processing queue item {item_idx}: {item_data.get('book_title')}")
                # Main container for each queue item
                item_box_label = f"#{item_idx + 1}: {item_data['book_title']}"
                # Add status to the label if present
                current_status = item_data.get('status', 'Pending')
                if self.queue_processing_active and item_idx == self.current_queue_item_index:
                    current_status = item_data.get('status', "⏳ In Progress") # Default to In Progress if it's the current one

                item_display_label = f"{item_box_label} - Status: {current_status}"
                item_box = wx.StaticBox(self.queue_tab_panel, label=item_display_label)
                item_sizer = wx.StaticBoxSizer(item_box, wx.VERTICAL)

                # Chapters information
                chapters_str = "All Chapters" # Default if specific chapters aren't listed (e.g. whole book)
                if 'chapters' in item_data and isinstance(item_data['chapters'], list):
                    if len(item_data['chapters']) > 3:
                        chapters_str = f"Selected chapters ({len(item_data['chapters'])})"
                    else:
                        chapters_str = ", ".join([ch['title'] for ch in item_data['chapters']])
                    if not chapters_str: chapters_str = "No specific chapters selected"
                elif 'selected_chapter_details' in item_data: # From "Queue Whole Book" (legacy or direct chapter objects)
                    if len(item_data['selected_chapter_details']) > 3:
                         chapters_str = f"Selected chapters ({len(item_data['selected_chapter_details'])})"
                    else:
                        chapters_str = ", ".join([ch.short_name for ch in item_data['selected_chapter_details']])


                chapters_label = wx.StaticText(item_box, label=f"Chapters: {chapters_str}")
                item_sizer.Add(chapters_label, 0, wx.ALL | wx.EXPAND, 5)

                # Synthesis settings
                settings = item_data.get('synthesis_settings', {})
                engine_label = wx.StaticText(item_box, label=f"Engine: {settings.get('engine', 'N/A')}")
                voice_label = wx.StaticText(item_box, label=f"Voice: {settings.get('voice', 'N/A')}")
                speed_label = wx.StaticText(item_box, label=f"Speed: {settings.get('speed', 'N/A')}")
                output_label = wx.StaticText(item_box, label=f"Output: {settings.get('output_folder', 'N/A')}")
                output_label.Wrap(self.window_width // 3) # Wrap text if too long

                item_sizer.Add(engine_label, 0, wx.ALL | wx.EXPAND, 2)
                item_sizer.Add(voice_label, 0, wx.ALL | wx.EXPAND, 2)
                item_sizer.Add(speed_label, 0, wx.ALL | wx.EXPAND, 2)
                item_sizer.Add(output_label, 0, wx.ALL | wx.EXPAND, 2)

                # Store a reference to the StaticBox in the item_data if needed for updates
                item_data['_ui_box'] = item_box

                # Add Remove button for each item
                remove_button = wx.Button(item_box, label="❌ Remove")
                # Pass queue_item_id (item_data['id']) to the handler
                # Ensure item_data['id'] exists and is the correct DB ID for the queue item
                if 'id' in item_data:
                    remove_button.Bind(wx.EVT_BUTTON, lambda evt, qid=item_data['id']: self.on_remove_queue_item(evt, qid))
                else:
                    remove_button.Disable() # Should not happen if items are from DB
                    print(f"Warning: Queue item '{item_data.get('book_title')}' is missing an 'id'. Remove button disabled.")
                item_sizer.Add(remove_button, 0, wx.ALL | wx.ALIGN_CENTER, 5)

                self.queue_tab_sizer.Add(item_sizer, 0, wx.ALL | wx.EXPAND, 10)
                print(f"DEBUG: Added item_sizer for {item_data.get('book_title')} to queue_tab_sizer.")

        # Sizer for action buttons (Run, Schedule) and scheduled time text
        action_controls_sizer = wx.BoxSizer(wx.HORIZONTAL)

        if self.queue_items:
            # Create buttons and text FRESHLY each time, as Clear(delete_windows=True) destroyed old ones.
            self.run_queue_button = wx.Button(self.queue_tab_panel, label="🚀 Run Queue")
            self.run_queue_button.Bind(wx.EVT_BUTTON, self.on_run_queue)
            action_controls_sizer.Add(self.run_queue_button, 0, wx.ALL | wx.ALIGN_CENTER, 5)
            self.run_queue_button.Enable(not self.queue_processing_active)

            self.schedule_queue_button = wx.Button(self.queue_tab_panel, label="📅 Schedule Queue")
            self.schedule_queue_button.Bind(wx.EVT_BUTTON, self.on_schedule_queue)
            action_controls_sizer.Add(self.schedule_queue_button, 0, wx.ALL | wx.ALIGN_CENTER, 5)
            self.schedule_queue_button.Enable(not self.queue_processing_active)

            self.scheduled_time_text = wx.StaticText(self.queue_tab_panel, label="")
            action_controls_sizer.Add(self.scheduled_time_text, 0, wx.ALL | wx.ALIGN_CENTER | wx.LEFT, 10)
            self.update_scheduled_time_display() # This will set the label for scheduled_time_text

            if action_controls_sizer.GetItemCount() > 0:
                self.queue_tab_sizer.Add(action_controls_sizer, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        else:
            # Ensure instance variables are None if controls are not created / relevant
            self.run_queue_button = None
            self.schedule_queue_button = None
            self.scheduled_time_text = None
            # Any existing action_controls_sizer (if it was managed at instance level)
            # would have been cleared by self.queue_tab_sizer.Clear(delete_windows=True)
            # if it was added to queue_tab_sizer. Here, action_controls_sizer is local.

        print("DEBUG: Calling self.queue_tab_panel.SetupScrolling() and .Layout()")
        self.queue_tab_panel.SetupScrolling()
        self.queue_tab_panel.Layout()
        if hasattr(self, 'notebook') and self.notebook:
            print("DEBUG: Calling self.notebook.Layout() and self.splitter_left.Layout()")
            self.notebook.Layout()
        if hasattr(self, 'splitter_left') and self.splitter_left:
            self.splitter_left.Layout()
        # self.Layout() # Optionally, layout the whole frame if needed

    def update_scheduled_time_display(self):
        if not hasattr(self, 'scheduled_time_text') or not self.scheduled_time_text:
            return
        scheduled_ts = db.load_schedule_time()
        if scheduled_ts:
            try:
                if scheduled_ts > 0: # Valid timestamp
                    scheduled_dt = datetime.fromtimestamp(scheduled_ts)
                    self.scheduled_time_text.SetLabel(f"Scheduled for: {scheduled_dt.strftime('%Y-%m-%d %H:%M')}")
                else: # Invalid or cleared timestamp
                    self.scheduled_time_text.SetLabel("Not scheduled")
            except (TypeError, ValueError, OSError) as e: # Catch potential errors from invalid timestamp
                self.scheduled_time_text.SetLabel("Scheduled: (Error)")
                print(f"Error formatting scheduled time (ts: {scheduled_ts}): {e}")
        else:
            self.scheduled_time_text.SetLabel("Not scheduled")

        if self.scheduled_time_text.GetContainingSizer():
            self.scheduled_time_text.GetContainingSizer().Layout()
        # self.queue_tab_panel.Layout() # Avoid if too broad, parent sizer should handle

    def on_schedule_queue(self, event):
        dialog = ScheduleDialog(self)
        if dialog.ShowModal() == wx.ID_OK:
            selected_datetime = dialog.get_selected_datetime()
            if selected_datetime: # A specific datetime was chosen
                if selected_datetime < datetime.now():
                    wx.MessageBox("Scheduled time must be in the future.", "Invalid Time", wx.OK | wx.ICON_ERROR)
                    dialog.Destroy()
                    return

                timestamp = int(selected_datetime.timestamp())
                db.save_schedule_time(timestamp)
                wx.MessageBox(f"Queue scheduled to run at: {selected_datetime.strftime('%Y-%m-%d %H:%M')}",
                              "Queue Scheduled", wx.OK | wx.ICON_INFORMATION)
                # self.start_schedule_check_timer() # Call to start timer will be added later
            else: # User explicitly cleared the schedule via the dialog
                db.save_schedule_time(None) # Pass None to clear
                wx.MessageBox("Queue schedule has been cleared.", "Schedule Cleared", wx.OK | wx.ICON_INFORMATION)
                # if hasattr(self, 'schedule_check_timer') and self.schedule_check_timer.IsRunning():
                #     self.schedule_check_timer.Stop()
                #     print("Schedule check timer stopped.")
            self.update_scheduled_time_display() # Update display after any change
        dialog.Destroy()

    def start_schedule_check_timer(self, interval_ms=30000): # Check every 30 seconds
        """Starts or restarts the schedule check timer."""
        if self.schedule_check_timer.IsRunning():
            self.schedule_check_timer.Stop()

        # Only start if there's actually a schedule to check or if we want it always running
        # For now, let's make it always start and on_check_schedule_timer can decide to do nothing
        print(f"Schedule check timer started/restarted (interval: {interval_ms}ms).")
        self.schedule_check_timer.Start(interval_ms)


    def on_check_schedule_timer(self, event):
        # print("Checking schedule...") # For debugging
        if self.queue_processing_active:
            # print("Queue is busy, skipping scheduled check.")
            return

        scheduled_ts = db.load_schedule_time()
        if not scheduled_ts or scheduled_ts <= 0: # No schedule or invalid
            # print("No active schedule found.")
            # self.schedule_check_timer.Stop() # Optional: stop if no schedule
            return

        current_ts = int(datetime.now().timestamp())
        if current_ts >= scheduled_ts:
            print(f"Scheduled time {datetime.fromtimestamp(scheduled_ts)} reached. Starting queue.")
            db.save_schedule_time(None) # Clear the schedule from DB
            self.update_scheduled_time_display() # Update UI

            if not self.queue_items:
                wx.MessageBox("Scheduled time reached, but the queue is empty.",
                              "Queue Empty", wx.OK | wx.ICON_INFORMATION)
                if self.schedule_check_timer.IsRunning(): self.schedule_check_timer.Stop() # Stop timer
                return

            # Check if another synthesis (manual or other) started in the meantime
            if self.synthesis_in_progress or self.queue_processing_active:
                 print("Synthesis/Queue processing started by other means before scheduled time could trigger. Schedule ignored.")
                 return

            self.on_run_queue(event=None) # Trigger queue processing
            # Timer will continue running, or could be stopped if preferred after a run
            # For now, let it run; it won't do anything until a new schedule is set.
        # else:
            # print(f"Scheduled time {datetime.fromtimestamp(scheduled_ts)} not yet reached.")


    def on_remove_queue_item(self, event, queue_item_id):
        """Handles removal of a specific item from the queue."""
        if self.queue_processing_active:
            # Find the item being processed
            if self.current_queue_item_index >= 0 and self.current_queue_item_index < len(self.queue_items):
                currently_processing_item_id = self.queue_items[self.current_queue_item_index].get('id')
                if currently_processing_item_id == queue_item_id:
                    wx.MessageBox("Cannot remove an item that is currently being processed.",
                                  "Action Not Allowed", wx.OK | wx.ICON_WARNING)
                    return

        # Optional: Confirmation dialog
        # confirm = wx.MessageBox(f"Are you sure you want to remove this item from the queue?",
        #                         "Confirm Removal", wx.YES_NO | wx.ICON_QUESTION)
        # if confirm == wx.NO:
        #     return

        db.remove_queue_item(queue_item_id)
        self.queue_items = db.get_queued_items() # Reload queue from DB
        self.refresh_queue_tab() # Refresh the UI display

        # If the removed item was before the currently processing one, adjust index
        # This is a bit tricky if items are reordered or if current_queue_item_index
        # refers to the old list. Simplest is to let process_next_queue_item handle it,
        # or re-evaluate current_queue_item_index based on the new list if processing.
        # For now, if queue is active, it might try to process an item that shifted index.
        # However, remove_queue_item is typically for non-active queues or items not yet processed.

        wx.MessageBox("Item removed from queue.", "Queue Updated", wx.OK | wx.ICON_INFORMATION)


    def on_run_queue(self, event):
        if not self.queue_items:
            wx.MessageBox("Queue is empty. Add items to the queue first.", "Queue Empty", wx.OK | wx.ICON_INFORMATION)
            return

        if self.queue_processing_active:
            wx.MessageBox("Queue processing is already active.", "Queue Running", wx.OK | wx.ICON_INFORMATION)
            return

        # Clear any existing schedule if queue is run manually
        if db.load_schedule_time():
            db.save_schedule_time(None) # Clear schedule from DB
            self.update_scheduled_time_display() # Update UI
            print("Manual queue run initiated, existing schedule cleared.")

        self.queue_processing_active = True
        self.current_queue_item_index = 0 # Start with the first item
        # self.queue_to_process = list(self.queue_items) # Process a copy

        if self.run_queue_button:
            self.run_queue_button.Disable()
        if self.schedule_queue_button: # Also disable schedule button
            self.schedule_queue_button.Disable()


        self.start_button.Disable() # Disable single start button as well
        self.params_panel.Disable() # Disable params panel

        self.process_next_queue_item()

    def process_next_queue_item(self):
        if not self.queue_processing_active: # Stopped externally
            self._finalize_queue_processing()
            return

        if self.current_queue_item_index >= len(self.queue_items):
            wx.MessageBox("All items in the queue have been processed.", "Queue Finished", wx.OK | wx.ICON_INFORMATION)
            self._finalize_queue_processing()
            return

        item_to_process = self.queue_items[self.current_queue_item_index]
        # Update DB status and local status
        db.update_queue_item_status(item_to_process['id'], 'in_progress')
        item_to_process['status'] = "⏳ In Progress"
        self.refresh_queue_tab()

        book_title = item_to_process['book_title']
        # synthesis_settings is already a dict due to db.get_queued_items()
        synthesis_settings = item_to_process['synthesis_settings']
        chapters_to_synthesize = []

        # Prepare chapters for CoreThread: ensure they have 'extracted_text' and 'chapter_index'
        # item_to_process['chapters'] comes from db.get_queued_items which gets from queued_chapters table
        for idx, chap_db_info in enumerate(item_to_process.get('chapters', [])):
            chapter_obj = type('ChapterForCore', (), {})()
            chapter_obj.title = chap_db_info.get('title', 'Unknown Chapter')
            chapter_obj.short_name = chap_db_info.get('title', 'Unknown Chapter') # For consistency if core uses short_name
            chapter_obj.chapter_index = idx # Index within this synthesis job for UI event

            text_content = chap_db_info.get('text_content')
            # If text_content is None or empty, and there's a staged_chapter_id, try fetching it
            if not text_content and chap_db_info.get('staged_chapter_id'):
                print(f"Fetching text for staged chapter ID {chap_db_info['staged_chapter_id']} ('{chapter_obj.title}')...")
                text_content = db.get_chapter_text_content(chap_db_info['staged_chapter_id'])

            if text_content is None: # If still None after trying to fetch
                print(f"Error: Could not find/fetch text for chapter ID {chap_db_info.get('id')} ('{chapter_obj.title}') in book '{book_title}'. Skipping chapter.")
                # Optionally mark chapter or item as error here. For now, just skip this chapter.
                continue
            chapter_obj.extracted_text = text_content
            chapter_obj.is_selected = True # All chapters here are for processing
            chapters_to_synthesize.append(chapter_obj)

        if not chapters_to_synthesize:
            print(f"Skipping '{book_title}': No valid chapters to synthesize after attempting to load text.")
            db.update_queue_item_status(item_to_process['id'], 'error') # Mark as error in DB
            item_to_process['status'] = "⚠️ Error (No Chapters Text)" # Update local status
            self.refresh_queue_tab() # Refresh UI
            self.current_queue_item_index += 1 # Move to next item
            wx.CallAfter(self.process_next_queue_item) # Try next item
            return

        # Prepare parameters for CoreThread
        file_path = item_to_process.get('source_path') # Available if from "Chapters" tab

        if not file_path and 'book_id' in item_to_process: # Staged item
            # Attempt to use current book's path as a fallback for core.main's epub.read_epub.
            # This is primarily so core.main doesn't crash trying to read a non-existent/placeholder path.
            # The actual chapter content for TTS comes from chapters_to_synthesize.
            # Metadata (title, author, cover) in the output file might be from the wrong book if it's not a match.
            # This will be properly fixed when DB stores source_path or metadata for staged items.
            if hasattr(self, 'selected_file_path') and self.selected_file_path and Path(self.selected_file_path).exists():
                file_path = self.selected_file_path
                print(f"Warning: Using currently loaded EPUB '{file_path}' as a source for metadata for staged item '{book_title}'. Output metadata may be incorrect if this is not the original EPUB for the staged item.")
            else:
                # If no current EPUB is loaded, core.main will likely fail.
                # This is an unrecoverable situation for core.main as it's currently written.
                print(f"Error: Cannot process staged item '{book_title}'. Original source_path is missing and no fallback EPUB is currently loaded. Skipping.")
                item_to_process['status'] = "⚠️ Error (Missing EPUB Path)"
                self.current_queue_item_index +=1
                # self.synthesis_in_progress = False # Reset as this item won't run CoreThread
                wx.CallAfter(self.process_next_queue_item)
                return
        elif not file_path: # Should not happen if logic is correct (source_path from Chapters tab)
             print(f"Error: file_path is missing for item '{book_title}' and it's not a staged item. Skipping.")
             item_to_process['status'] = "⚠️ Error (Missing Path)"
             self.current_queue_item_index +=1
             wx.CallAfter(self.process_next_queue_item)
             return


        voice_flagged = synthesis_settings.get('voice', self.voice_dropdown.GetValue())
        voice = voice_flagged.split(' ')[1] if ' ' in voice_flagged else voice_flagged # Remove flag

        try:
            speed = float(synthesis_settings.get('speed', self.speed_text_input.GetValue()))
        except ValueError:
            speed = 1.0

        output_folder = synthesis_settings.get('output_folder', self.output_folder_text_ctrl.GetValue())
        engine = synthesis_settings.get('engine', 'cpu')

        # Set device for this specific core.main call
        torch.set_default_device(engine)
        print(f"Setting engine to: {engine} for book: {book_title}")


        if not chapters_to_synthesize:
             print(f"No chapters to synthesize for '{book_title}'. Skipping.")
             item_to_process['status'] = "⚠️ Skipped (No Chapters)"
             self.current_queue_item_index +=1
             wx.CallAfter(self.process_next_queue_item)
             return

        print(f"Starting synthesis from queue for: {book_title} with {len(chapters_to_synthesize)} chapters.")
        self.synthesis_in_progress = True # General flag for core processing

        # Ensure UI elements like progress bar are visible for the current item
        self.progress_bar_label.SetLabel(f"Progress for: {book_title}")
        self.progress_bar_label.Show()
        self.progress_bar.SetValue(0)
        self.progress_bar.Show()
        self.eta_label.Show()
        self.synth_panel.Layout()


        # Note: CoreThread's post_event uses chapter.chapter_index.
        # Make sure chapters_to_synthesize have this attribute.
        self.core_thread = CoreThread(params=dict(
            file_path=file_path,  # This might be problematic if not correctly resolved
            voice=voice,
            pick_manually=False,
            speed=speed,
            output_folder=output_folder,
            selected_chapters=chapters_to_synthesize,
            # We can add a queue_item_id or book_title to params if CoreThread needs to report it back
            # This would help on_core_finished identify which queue item finished if events become complex.
            # For sequential processing, self.current_queue_item_index is enough for MainWindow.
            # We also need to ensure chapter_index attribute is on each chapter object for progress.
            # For chapters from staging, we added a dummy one.
        ))
        self.core_thread.start()
        # The actual removal from self.queue_items and moving to next happens in on_core_finished

    def _finalize_queue_processing(self):
        self.queue_processing_active = False
        self.synthesis_in_progress = False # Reset general flag
        self.current_queue_item_index = -1
        # self.queue_to_process = [] # Clear the processing copy

        # Ensure schedule display is up-to-date (e.g. if it was cleared by starting queue)
        self.update_scheduled_time_display()

        # Remove items from DB that were successfully processed or errored out
        items_to_remove_from_db = [
            item['id'] for item in self.queue_items
            if 'id' in item and (item.get('status', '').startswith("✅") or \
                                 item.get('status', '').startswith("⚠️"))
        ]
        for item_id_to_remove in items_to_remove_from_db:
            db.remove_queue_item(item_id_to_remove)

        self.queue_items = db.get_queued_items() # Reload to get the current truth from DB
        self.refresh_queue_tab()

        # Re-enable global controls if no more items or queue stopped
        self.start_button.Enable()
        self.params_panel.Enable()
        if hasattr(self, 'table'): self.table.EnableCheckBoxes(True)

        if self.run_queue_button:
            if self.queue_items: # If some items remain (e.g. user added more)
                self.run_queue_button.Enable()
            else: # Queue is now empty
                self.run_queue_button.Disable() # Or remove, handled by refresh_queue_tab

        # Hide progress bar elements related to single/queue item processing
        self.progress_bar_label.Hide()
        self.progress_bar.Hide()
        self.eta_label.Hide()
        self.params_panel.Layout() # Was disabled
        self.synth_panel.Layout()


    def on_table_checked(self, event):
        self.document_chapters[event.GetIndex()].is_selected = True

    def on_table_unchecked(self, event):
        self.document_chapters[event.GetIndex()].is_selected = False

    def on_table_selected(self, event):
        chapter = self.document_chapters[event.GetIndex()]
        print('Selected', event.GetIndex(), chapter.short_name)
        self.selected_chapter = chapter
        self.text_area.SetValue(chapter.extracted_text)
        self.chapter_label.SetLabel(f'Edit / Preview content for section "{chapter.short_name}":')

    def create_chapters_table_panel(self, document_chapters_list):
        # Parent of this ScrolledPanel should be self.chapters_tab_page (the wx.Panel for "Chapters" tab)
        panel = ScrolledPanel(self.chapters_tab_page, -1, style=wx.TAB_TRAVERSAL | wx.SUNKEN_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(sizer)

        self.table = table = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        table.InsertColumn(0, "Included")
        table.InsertColumn(1, "Chapter Name")
        table.InsertColumn(2, "Chapter Length")
        table.InsertColumn(3, "Status")
        table.SetColumnWidth(0, 80)
        table.SetColumnWidth(1, 150)
        table.SetColumnWidth(2, 150)
        table.SetColumnWidth(3, 100)
        table.SetSize((250, -1))
        table.EnableCheckBoxes()
        table.Bind(wx.EVT_LIST_ITEM_CHECKED, self.on_table_checked)
        table.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self.on_table_unchecked)
        table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_table_selected)

        # self.good_chapters_list should be available here, set in open_epub
        for i, chapter in enumerate(document_chapters_list): # Use the passed argument
            auto_selected = chapter in self.good_chapters_list
            table.Append(['', chapter.short_name, f"{len(chapter.extracted_text):,}"])
            if auto_selected:
                table.CheckItem(i)
            # Ensure chapter.is_selected is consistent if it wasn't set by open_epub's loop,
            # though it should be. This is more about table checking.
            # chapter.is_selected = auto_selected # This line is redundant if open_epub already set it.

        title_text = wx.StaticText(panel, label=f"Select chapters to include in the audiobook:")
        sizer.Add(title_text, 0, wx.ALL, 5)
        sizer.Add(table, 1, wx.ALL | wx.EXPAND, 5)

        stage_book_button = wx.Button(panel, label="📚 Stage Book for Batching")
        stage_book_button.Bind(wx.EVT_BUTTON, self.on_stage_book)
        sizer.Add(stage_book_button, 0, wx.ALL | wx.ALIGN_CENTER, 5)

        queue_portions_button = wx.Button(panel, label="▶️ Queue Selected Book Portions")
        queue_portions_button.Bind(wx.EVT_BUTTON, self.on_queue_selected_book_portions)
        sizer.Add(queue_portions_button, 0, wx.ALL | wx.ALIGN_CENTER, 10)

        return panel

    def on_queue_selected_book_portions(self, event):
        if not hasattr(self, 'selected_book') or not self.selected_book:
            wx.MessageBox("Please open an EPUB file first to select and queue book portions.",
                          "No Book Loaded", wx.OK | wx.ICON_INFORMATION)
            return

        selected_chapters_from_table = []
        for i in range(self.table.GetItemCount()):
            if self.table.IsItemChecked(i):
                # self.document_chapters[i] should correspond to the displayed item
                selected_chapters_from_table.append(self.document_chapters[i])

        if not selected_chapters_from_table:
            wx.MessageBox("No chapters selected from the list. Please check the chapters you want to queue.",
                          "No Selection", wx.OK | wx.ICON_INFORMATION)
            return

        # Retrieve current global synthesis settings
        current_engine = 'cuda' if self.cuda_radio.GetValue() else 'cpu'
        current_voice = self.voice_dropdown.GetValue() # This includes the flag
        current_speed = self.speed_text_input.GetValue()
        current_output_folder = self.output_folder_text_ctrl.GetValue()

        synthesis_settings = {
            'engine': current_engine,
            'voice': current_voice,
            'speed': current_speed,
            'output_folder': current_output_folder,
        }

        # Create a new queue entry
        # Note: 'selected_chapter_details' stores the actual chapter objects from self.document_chapters
        # This is different from the Staging tab queue which stores DB IDs and titles.
        # The processor will need to handle this difference.
        queue_entry = {
            'staged_book_id': None, # Not from staging
            'book_title': self.selected_book_title,
            'source_path': self.selected_file_path,
            'synthesis_settings': synthesis_settings, # This is a dict
            'chapters': []
        }
        for i, chap_obj in enumerate(selected_chapters_from_table):
            queue_entry['chapters'].append({
                'staged_chapter_id': None,
                'title': chap_obj.short_name,
                'text_content': chap_obj.extracted_text, # Store text directly for non-staged items
                'order': i
            })

        print(f"DEBUG: Before DB reload, self.queue_items: {self.queue_items}")
        new_item_id = db.add_item_to_queue(queue_entry)
        if new_item_id:
            self.queue_items = db.get_queued_items() # Reload queue
            print(f"DEBUG: After DB reload, self.queue_items: {self.queue_items}")
            print("DEBUG: Calling refresh_queue_tab()")
            self.refresh_queue_tab()
            self.notebook.SetSelection(self.notebook.GetPageCount() - 1)
            wx.MessageBox(f"Added selected portions from '{self.selected_book_title}' (with {len(selected_chapters_from_table)} chapter(s)) to the queue.",
                          "Added to Queue", wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox("Failed to add item to the database queue.", "Error", wx.OK | wx.ICON_ERROR)


    def on_stage_book(self, event):
        if not hasattr(self, 'selected_book') or not self.selected_book:
            wx.MessageBox("Please open an EPUB file first.", "No Book Loaded", wx.OK | wx.ICON_INFORMATION)
            return

        book_title = self.selected_book_title
        book_author = self.selected_book_author
        source_path = self.selected_file_path
        output_folder = self.output_folder_text_ctrl.GetValue()

        chapters_to_stage = []
        for i, chapter_obj in enumerate(self.document_chapters):
            chapters_to_stage.append({
                'chapter_number': i, # or some other persistent chapter identifier if available
                'title': chapter_obj.short_name,
                'text_content': chapter_obj.extracted_text,
                'is_selected_for_synthesis': chapter_obj.is_selected
            })

        from audiblez.database import add_staged_book # Import moved here for clarity
        book_id = add_staged_book(book_title, book_author, source_path, output_folder, chapters_to_stage)

        if book_id is not None:
            wx.MessageBox(f"Book '{book_title}' and its chapters have been staged.", "Book Staged", wx.OK | wx.ICON_INFORMATION)
            self.refresh_staging_tab()
        elif source_path:
             wx.MessageBox(f"Book '{book_title}' (from {source_path}) might already be staged. Cannot add duplicate.", "Staging Failed", wx.OK | wx.ICON_ERROR)
        else:
            wx.MessageBox("Failed to stage the book. Check logs for details.", "Staging Failed", wx.OK | wx.ICON_ERROR)

    def refresh_staging_tab(self):
        # Clear existing content
        for child in self.staging_tab_sizer.GetChildren():
            child.GetWindow().Destroy()

        from audiblez.database import get_staged_books_with_chapters, update_staged_chapter_selection, update_staged_book_final_compilation

        staged_books = get_staged_books_with_chapters()

        if not staged_books:
            no_books_label = wx.StaticText(self.staging_tab_panel, label="No books have been staged yet.")
            self.staging_tab_sizer.Add(no_books_label, 0, wx.ALL | wx.ALIGN_CENTER, 15)
        else:
            for book in staged_books:
                book_box = wx.StaticBox(self.staging_tab_panel, label=f"{book['title']} (Author: {book.get('author', 'N/A')})")
                book_sizer = wx.StaticBoxSizer(book_box, wx.VERTICAL)

                # Final Compilation Checkbox for the book
                # Parent should be book_box for proper visual grouping and lifecycle management with the StaticBox
                final_comp_checkbox = wx.CheckBox(book_box, label="Enable Final Compilation for this Book")
                final_comp_checkbox.SetValue(book['final_compilation'])
                final_comp_checkbox.Bind(wx.EVT_CHECKBOX,
                                         lambda evt, b_id=book['id']:
                                         update_staged_book_final_compilation(b_id, evt.IsChecked()))
                book_sizer.Add(final_comp_checkbox, 0, wx.ALL | wx.ALIGN_LEFT, 5)

                # Chapters list for the book
                if book['chapters']:
                    # Parent of chapters_list_ctrl should be book_box, not self.staging_tab_panel
                    chapters_list_ctrl = wx.ListCtrl(book_box, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
                    chapters_list_ctrl.InsertColumn(0, "Include", width=70)
                    chapters_list_ctrl.InsertColumn(1, "Chapter Title", width=200) # Adjust width as needed
                    chapters_list_ctrl.InsertColumn(2, "Status", width=100)
                    chapters_list_ctrl.EnableCheckBoxes()

                    for i, chap in enumerate(book['chapters']):
                        chapters_list_ctrl.InsertItem(i, "") # Checkbox column
                        chapters_list_ctrl.SetItem(i, 1, chap['title'])

                        status_display = chap['status']
                        is_completed = chap['status'] == 'completed'

                        if is_completed:
                            status_display = "✅ Completed"
                            # chapters_list_ctrl.SetItem(i, 0, "✓") # Show a checkmark, actual disabling is tricky for LC_Report

                        chapters_list_ctrl.SetItem(i, 2, status_display)

                        if chap['is_selected_for_synthesis'] and not is_completed:
                            chapters_list_ctrl.CheckItem(i)

                        # Store chapter_id with the item for the event handler
                        chapters_list_ctrl.SetItemData(i, chap['id'])

                        # Disable checkbox for completed items.
                        # wx.ListCtrl.EnableCheckBoxes() is for the whole control.
                        # Individual checkbox disabling is not directly supported.
                        # A workaround is to handle it in the check event or use a different control.
                        # For now, the status column will indicate completion.
                        # We can prevent re-checking in the event handler.

                    # Define event handler for this specific chapters_list_ctrl
                    def create_chapter_check_handler(list_ctrl_instance, book_chapters_data):
                        def on_chapter_check(event):
                            chapter_idx = event.GetIndex()
                            chapter_id = list_ctrl_instance.GetItemData(chapter_idx)
                            # Find the chapter's original data to check its status
                            original_chapter_data = next((c for c in book_chapters_data if c['id'] == chapter_id), None)

                            if original_chapter_data and original_chapter_data['status'] == 'completed':
                                # If chapter is completed, prevent checking/unchecking by reverting the check state
                                current_ui_checked_state = list_ctrl_instance.IsItemChecked(chapter_idx)
                                list_ctrl_instance.CheckItem(chapter_idx, not current_ui_checked_state) # Revert
                                wx.MessageBox("This chapter has already been processed and its selection cannot be changed here.",
                                              "Chapter Processed", wx.OK | wx.ICON_INFORMATION)
                                return

                            is_checked = list_ctrl_instance.IsItemChecked(chapter_idx)
                            update_staged_chapter_selection(chapter_id, is_checked)
                        return on_chapter_check

                    handler = create_chapter_check_handler(chapters_list_ctrl, book['chapters'])
                    chapters_list_ctrl.Bind(wx.EVT_LIST_ITEM_CHECKED, handler)
                    chapters_list_ctrl.Bind(wx.EVT_LIST_ITEM_UNCHECKED, handler) # Same handler for uncheck
                    book_sizer.Add(chapters_list_ctrl, 1, wx.ALL | wx.EXPAND, 5)
                else:
                    # Parent of no_chapters_label should be book_box
                    no_chapters_label = wx.StaticText(book_box, label="This book has no chapters.")
                    book_sizer.Add(no_chapters_label, 0, wx.ALL, 5)

                # Add "Queue Selected Chapters" button for this book
                queue_selected_button = wx.Button(book_box, label="▶️ Queue Selected Chapters")
                queue_selected_button.Bind(wx.EVT_BUTTON, lambda evt, b_id=book['id'], b_title=book['title'], list_ctrl=chapters_list_ctrl: self.on_queue_selected_staged_chapters(evt, b_id, b_title, list_ctrl))
                book_sizer.Add(queue_selected_button, 0, wx.ALL | wx.ALIGN_CENTER, 10)

                self.staging_tab_sizer.Add(book_sizer, 0, wx.ALL | wx.EXPAND, 10)

        self.staging_tab_panel.SetupScrolling()
        self.staging_tab_panel.Layout()
        # self.Layout() # Main frame layout, might be too broad, staging_tab_panel.Layout() should suffice.
        self.splitter.Layout() # Layout the main splitter that contains left and right
        self.Layout() # Full frame layout might be needed if sizers changed overall frame size.

    def update_staging_tab_for_processed_chapters(self, processed_staged_chapter_ids: list[int]):
        """
        Refreshes the staging tab to reflect the 'completed' status of chapters
        that were processed as part of a queue item.
        """
        # This method will find the relevant book and chapter in the staging tab UI
        # and update its visual representation (e.g., disable checkbox, show checkmark).
        # For now, a full refresh of the staging tab is the simplest way.
        # More granular updates can be implemented if performance becomes an issue.
        print(f"Updating staging tab for processed chapter IDs: {processed_staged_chapter_ids}")
        # Potentially, find the specific book and chapters_list_ctrl to update
        # For now, just trigger a full refresh.
        self.refresh_staging_tab()


    def on_queue_selected_staged_chapters(self, event, book_id, book_title, chapters_list_ctrl):
        raw_selected_chapters_data = []
        if not chapters_list_ctrl: # Should not happen if button is present
            wx.MessageBox("Error: Chapter list not found for this book.", "Error", wx.OK | wx.ICON_ERROR)
            return

        for i in range(chapters_list_ctrl.GetItemCount()):
            if chapters_list_ctrl.IsItemChecked(i):
                chapter_id_in_db = chapters_list_ctrl.GetItemData(i) # This is the DB ID of the chapter
                chapter_title = chapters_list_ctrl.GetItem(i, 1).GetText()
                text = db.get_chapter_text_content(chapter_id_in_db)
                if text is None:
                    # Log warning, but allow queuing. process_next_queue_item will try to re-fetch.
                    print(f"Warning: Could not fetch text for staged chapter ID {chapter_id_in_db} ('{chapter_title}') during queuing. Will attempt fetch during processing.")

                raw_selected_chapters_data.append({
                    'db_id': chapter_id_in_db, # Original DB ID from staged_chapters
                    'title': chapter_title,
                    'text_content': text # Store fetched text (might be None if fetch failed)
                })

        if not raw_selected_chapters_data:
            wx.MessageBox("No chapters selected. Please check the selection.",
                          "No Selection", wx.OK | wx.ICON_INFORMATION)
            return

        # Prepare the 'chapters' list for add_item_to_queue
        final_chapters_for_db = []
        for idx, chap_data in enumerate(raw_selected_chapters_data):
            final_chapters_for_db.append({
                'staged_chapter_id': chap_data['db_id'], # This key is expected by add_item_to_queue
                'title': chap_data['title'],
                'text_content': chap_data['text_content'],
                'order': idx # This provides the chapter_order for queued_chapters
            })

        # Retrieve current global synthesis settings
        current_engine = 'cuda' if self.cuda_radio.GetValue() else 'cpu'
        current_voice = self.voice_dropdown.GetValue()
        current_speed = self.speed_text_input.GetValue()
        current_output_folder = self.output_folder_text_ctrl.GetValue()

        synthesis_settings = { # This is a dict
            'engine': current_engine,
            'voice': current_voice,
            'speed': current_speed,
            'output_folder': current_output_folder,
        }

        db_queue_details = {
            'staged_book_id': book_id,
            'book_title': book_title,
            'source_path': None, # Staged items don't have a direct source_path for the queue item itself
            'synthesis_settings': synthesis_settings,
            'chapters': final_chapters_for_db
        }

        print(f"DEBUG: Before DB reload, self.queue_items: {self.queue_items}")
        new_item_id = db.add_item_to_queue(db_queue_details)
        if new_item_id:
            self.queue_items = db.get_queued_items() # Reload queue
            print(f"DEBUG: After DB reload, self.queue_items: {self.queue_items}")
            print("DEBUG: Calling refresh_queue_tab()")
            self.refresh_queue_tab()
            self.notebook.SetSelection(self.notebook.GetPageCount() - 1)
            wx.MessageBox(f"Added '{book_title}' (with {len(final_chapters_for_db)} selected chapter(s)) to the queue.",
                          "Added to Queue", wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox("Failed to add item to the database queue.", "Error", wx.OK | wx.ICON_ERROR)


    def get_selected_voice(self):
        return self.selected_voice.split(' ')[1]

    def get_selected_speed(self):
        return float(self.selected_speed)

    def on_preview_chapter(self, event):
        lang_code = self.get_selected_voice()[0]
        button = event.GetEventObject()
        button.SetLabel("⏳")
        button.Disable()

        def generate_preview():
            import audiblez.core as core
            from kokoro import KPipeline
            pipeline = KPipeline(lang_code=lang_code)
            core.load_spacy()
            text = self.selected_chapter.extracted_text[:300]
            if len(text) == 0: return
            audio_segments = core.gen_audio_segments(
                pipeline,
                text,
                voice=self.get_selected_voice(),
                speed=self.get_selected_speed())
            final_audio = np.concatenate(audio_segments)
            tmp_preview_wav_file = NamedTemporaryFile(suffix='.wav', delete=False)
            soundfile.write(tmp_preview_wav_file, final_audio, core.sample_rate)
            cmd = ['ffplay', '-autoexit', '-nodisp', tmp_preview_wav_file.name]
            subprocess.run(cmd)
            button.SetLabel("🔊 Preview")
            button.Enable()

        if len(self.preview_threads) > 0:
            for thread in self.preview_threads:
                thread.join()
            self.preview_threads = []
        thread = threading.Thread(target=generate_preview)
        thread.start()
        self.preview_threads.append(thread)

    def on_start(self, event):
        self.synthesis_in_progress = True
        file_path = self.selected_file_path
        voice = self.selected_voice.split(' ')[1]  # Remove the flag
        speed = float(self.selected_speed)
        selected_chapters = [chapter for chapter in self.document_chapters if chapter.is_selected]
        self.start_button.Disable()
        self.params_panel.Disable()

        self.table.EnableCheckBoxes(False)
        for chapter_index, chapter in enumerate(self.document_chapters):
            if chapter in selected_chapters:
                self.set_table_chapter_status(chapter_index, "Planned")
                self.table.SetItem(chapter_index, 0, '✔️')

        # self.stop_button.Show()
        print('Starting Audiobook Synthesis', dict(file_path=file_path, voice=voice, pick_manually=False, speed=speed))
        self.core_thread = CoreThread(params=dict(
            file_path=file_path, voice=voice, pick_manually=False, speed=speed,
            output_folder=self.output_folder_text_ctrl.GetValue(),
            selected_chapters=selected_chapters))
        self.core_thread.start()

    def on_open(self, event):
        with wx.FileDialog(self, "Open EPUB File", wildcard="*.epub", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return
            file_path = dialog.GetPath()
            print(f"Selected file: {file_path}")
            if not file_path:
                print('No filepath?')
                return
            if self.synthesis_in_progress:
                wx.MessageBox("Audiobook synthesis is still in progress. Please wait for it to finish.", "Audiobook Synthesis in Progress")
            else:
                wx.CallAfter(self.open_epub, file_path)

    def on_exit(self, event):
        self.Close()

    def set_table_chapter_status(self, chapter_index, status):
        self.table.SetItem(chapter_index, 3, status)

    def open_folder_with_explorer(self, folder_path):
        try:
            if platform.system() == 'Windows':
                subprocess.Popen(['explorer', folder_path])
            elif platform.system() == 'Linux':
                subprocess.Popen(['xdg-open', folder_path])
            elif platform.system() == 'Darwin':
                subprocess.Popen(['open', folder_path])
        except Exception as e:
            print(e)


class CoreThread(threading.Thread):
    def __init__(self, params):
        super().__init__()
        self.params = params

    def run(self):
        import core
        core.main(**self.params, post_event=self.post_event)

    def post_event(self, event_name, **kwargs):
        # eg. 'EVENT_CORE_PROGRESS' -> EventCoreProgress, EVENT_CORE_PROGRESS
        EventObject, EVENT_CODE = EVENTS[event_name]
        event_object = EventObject()
        for k, v in kwargs.items():
            setattr(event_object, k, v)
        wx.PostEvent(wx.GetApp().GetTopWindow(), event_object)


class ScheduleDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Schedule Queue", size=(400, 250))
        self.selected_datetime = None

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Instruction
        instruction = wx.StaticText(panel, label="Select a date and time for the queue to start:")
        vbox.Add(instruction, 0, wx.ALL | wx.EXPAND, 15)

        # Date Picker
        date_box = wx.BoxSizer(wx.HORIZONTAL)
        date_label = wx.StaticText(panel, label="Date:")
        self.date_picker = wx.adv.DatePickerCtrl(panel, style=wx.adv.DP_DEFAULT | wx.adv.DP_SHOWCENTURY)

        # Initialize with current date or saved schedule
        current_schedule_ts = db.load_schedule_time()
        initial_date = datetime.now()
        if current_schedule_ts and current_schedule_ts > 0:
            try:
                initial_date = datetime.fromtimestamp(current_schedule_ts)
            except ValueError: # Handle potential invalid timestamp from DB
                pass
        self.date_picker.SetValue(wx.DateTime.FromDMY(initial_date.day, initial_date.month - 1, initial_date.year))

        date_box.Add(date_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        date_box.Add(self.date_picker, 1, wx.EXPAND)
        vbox.Add(date_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        # Time Picker
        time_box = wx.BoxSizer(wx.HORIZONTAL)
        time_label = wx.StaticText(panel, label="Time (HH:MM):")
        # Using TimePickerCtrl if available and suitable, otherwise TextCtrl
        # For simplicity and wider compatibility, using TextCtrl with format hint
        self.time_picker = wx.TextCtrl(panel, value=initial_date.strftime("%H:%M"))
        self.time_picker.SetToolTip("Enter time in 24-hour HH:MM format")

        time_box.Add(time_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        time_box.Add(self.time_picker, 1, wx.EXPAND)
        vbox.Add(time_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        # Buttons
        hbox_buttons = wx.BoxSizer(wx.HORIZONTAL)
        ok_button = wx.Button(panel, label="Set Schedule", id=wx.ID_OK)
        ok_button.SetDefault()
        clear_button = wx.Button(panel, label="Clear Schedule")
        cancel_button = wx.Button(panel, label="Cancel", id=wx.ID_CANCEL)

        ok_button.Bind(wx.EVT_BUTTON, self.on_ok)
        clear_button.Bind(wx.EVT_BUTTON, self.on_clear)
        # cancel_button's ID_CANCEL is handled by default dialog behavior

        hbox_buttons.Add(ok_button)
        hbox_buttons.Add(clear_button, 0, wx.LEFT, 5)
        hbox_buttons.Add(cancel_button, 0, wx.LEFT, 5)
        vbox.Add(hbox_buttons, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 10)

        panel.SetSizer(vbox)
        self.CentreOnParent()

    def on_ok(self, event):
        wx_date = self.date_picker.GetValue()
        date_val = datetime(wx_date.GetYear(), wx_date.GetMonth() + 1, wx_date.GetDay())

        time_str = self.time_picker.GetValue()
        try:
            time_val = datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            wx.MessageBox("Invalid time format. Please use HH:MM (24-hour).", "Error", wx.OK | wx.ICON_ERROR, self)
            return

        self.selected_datetime = datetime.combine(date_val.date(), time_val)
        self.EndModal(wx.ID_OK)

    def on_clear(self, event):
        self.selected_datetime = None # Indicate clearance
        self.EndModal(wx.ID_OK) # Still ID_OK to signal dialog was actioned, parent checks selected_datetime

    def get_selected_datetime(self):
        return self.selected_datetime


def main():
    print('Starting GUI...')
    app = wx.App(False)
    frame = MainWindow(None, "Audiblez - Generate Audiobooks from E-books")
    frame.Show(True)
    frame.Layout()
    app.SetTopWindow(frame)
    print('Done.')
    app.MainLoop()


if __name__ == '__main__':
    main()
