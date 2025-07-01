### Idea 1: Staging and Queuing.
So I want to take the chapters panel and create two more tabbed sections in the same space, the current pane will still be default on top and populated with good chapters as now, but there will be three tabs, the Chapters tab, which is the current content, the Staging tab and the Queue tab. The user should still be able to select chapters and convert as they do now, but they should also have new options, to stage a defined book to the staging tab where a subset can be queued, or to queue the whole book directly to the queue tab. 

On the staging tab, chapters will nest under the book title along with a final compilation checkbox and be expanded or not, individual items or many chapters can be selected and queued on their own using the settings that are in place at the time they are queued, their item on the queue page should display the chosen engine, voice, speed and output folder as well as output type (future feature defined below). 

If another item is queued later with different settings selected, they should be run with those settings and that queued item in the queue should display the settings they'll run with. Items in the queue should summarize what's in the queue (example chapter 1 - 5 if 1, 2 3, 4, and 5 are queued, if non contiguous chapters are queued, there should be maybe 3 lines in the queued item to describe what's in it followed by "..." and if the user wants to see all items they can mouse over for a tooltip that lists all the chapters). Running a queued job should create a new folder to store wav files, it should mark the completed chapters as finished on the staging screen (take away their user interactable checkboxes and just place a checkmark next to them) and the tab should remember incomplete steps (chapters and the completion step for each book) across sessions. 

At the bottom of the queue there should be a button for running the queue and another for scheduling the queue in case the user wants to schedule it overnight or while they're at work.

In order to have persistance we'll need an sqlite implementation, let's make a database.py for that.


### Idea 2: keep current epub reading method and add calibre parsing as an extra option.
*   Keep the open epub button as the default
*   Add Open ebook with calibre button, convert to html as below, use current methods from there.

Converting the EPUB to HTML using `ebook-convert` and then processing the resulting HTML with the existing `BeautifulSoup` logic in [`audiblez/core.py`](audiblez/core.py:224) could indeed be a very sensible approach.

Here's why that makes sense and how it would work:

1.  **Leveraging Calibre's Parsing:** Calibre's `ebook-convert` is highly capable of handling various EPUB complexities and converting them accurately into other formats. Converting to HTML would allow you to benefit from Calibre's parsing engine to produce a well-formed HTML representation of the book's content.
2.  **Retaining Existing Logic:** Your current code in [`find_document_chapters_and_extract_texts`](audiblez/core.py:224) already uses `BeautifulSoup` to parse HTML content and extract text from specific tags (`title`, `p`, `h1`, etc.). If `ebook-convert` outputs HTML, you could potentially feed this output directly into your existing `BeautifulSoup` process.
3.  **Preserving Structure:** Converting to HTML is more likely to preserve the structural elements of the book (like headings, paragraphs, lists) compared to converting to plain text. This structure is what your current `BeautifulSoup` logic relies on to identify and extract meaningful text blocks. It might also preserve chapter divisions, either as separate HTML files or clearly marked sections within a single HTML file.

**How this approach would look:**

*   When an EPUB is opened, `audiblez` would call `ebook-convert` to convert the EPUB to HTML. The command would look something like:
    ```bash
    ebook-convert input.epub output.html
    ```
*   `audiblez` would then read the generated `output.html` file(s).
*   The content of the HTML file(s) would be processed by a function similar to your existing [`find_document_chapters_and_extract_texts`](audiblez/core.py:224), using `BeautifulSoup` to find the relevant text within tags.
*   If `ebook-convert` outputs multiple HTML files corresponding to chapters, you could iterate through these files, treating each one as a chapter, much like you currently iterate through `ITEM_DOCUMENT` items from `ebooklib`. If it outputs a single large HTML file, you might need to adapt the chapter identification logic, perhaps by looking for specific heading tags (`<h1>`, `<h2>`) that `ebook-convert` might generate for chapter titles.

**Feasibility:**

This approach seems highly feasible and potentially less disruptive to the existing codebase than converting to plain text. The main work would involve:

*   Implementing the `subprocess` call to `ebook-convert`.
*   Handling the output file(s) from `ebook-convert`.
*   Potentially making minor adjustments to the `BeautifulSoup` parsing if the structure of the HTML output from Calibre differs significantly from the HTML within the original EPUB items.

This method allows you to leverage Calibre's robust parsing while keeping the core text extraction and processing logic largely intact.

### Idea 3: User editable rate
The current progress meter assumes something like 500 or 50 characters per second depending on whether using cuda acceleration, and that makes it far off for most users. Have a savable (to the sqlite audiblez.db) rate that can be used when calculating the progress to make it more accurate. It won't work the first time but once a user figures out their normal rate they can input it and save it. The field to input this should be located in the Audiobook generation status pane.

### Idea 4: Remember user settings
Store last engine choice, last speed setting and last voice used in the audiblez.db.


### Phased Development Plan

This plan outlines the steps to implement the features described in `audiblez/features.md`.

**Phase 0: Foundation and Settings Persistence**

*   **Phase 0.1: SQLite Database Setup** [DONE]
    *   Create a new file, [`audiblez/database.py`](audiblez/database.py), to handle SQLite database operations.
    *   Implement functions to connect to `audiblez.db`.
    *   Create necessary tables for storing user settings, staged books/chapters, and the synthesis queue.
*   **Phase 0.2: Remember User Settings** [DONE]
    *   Modify the UI ([`audiblez/ui.py`](audiblez/ui.py)) to load the last used engine, voice, and speed settings from the database on startup.
    *   Modify the UI to save the current engine, voice, and speed settings to the database whenever they are changed.
    *   Update [`audiblez/cli.py`](audiblez/cli.py) to potentially load default settings from the database if not provided via command line arguments.
*   **Phase 0.3: User Editable Rate** [DONE]
    *   Add a new input field in the UI ([`audiblez/ui.py`](audiblez/ui.py)) for the user to enter a custom characters-per-second rate.
    *   Store this custom rate in the database.
    *   Modify the progress calculation in [`audiblez/core.py`](audiblez/core.py) to use the user-defined rate if available, falling back to the default if not set.

**Phase 1: Staging and Queuing**

*   **Phase 1.1: UI Tabs and Basic Structure** [DONE]
    *   Modify the UI ([`audiblez/ui.py`](audiblez/ui.py)) to replace the single chapters panel with a tabbed interface containing "Chapters", "Staging", and "Queue" tabs.
    *   The "Chapters" tab will retain the current functionality.
    *   Implement the basic structure for the "Staging" and "Queue" tabs.
*   **Phase 1.2: Staging Functionality** [DONE]
    *   Add a "Stage Book" option (button or context menu) in the "Chapters" tab.
    *   Implement logic to move the currently loaded book and its chapters to the "Staging" tab when "Stage Book" is selected.
    *   Store the staged book and its chapters in the database, including book metadata.
    *   Display staged chapters nested under the book title in the "Staging" tab, with checkboxes for selection.
    *   Add a "Final Compilation" checkbox per book in the "Staging" tab.
*   **Phase 1.3: Queuing Functionality** [DONE]
    *   Add a "Queue Selected Chapters" option in the "Staging" tab.
    *   Implement logic to add selected chapters from the "Staging" tab to the "Queue" tab.
    *   When queuing, capture the current synthesis settings (engine, voice, speed, output folder) and store them with the queued item in the database.
    *   Add an option to "Queue Selected Book Portions" (formerly "Queue Whole Book") directly from the "Chapters" tab, which queues selected chapters from the currently loaded book with current settings.
    *   Database support for storing queue items and their chapters implemented in `database.py`.
*   **Phase 1.4: Queue Display and Management** [DONE]
    *   Display queued items in the "Queue" tab, showing the captured settings for each item (engine, voice, speed, output folder), book title, and a summary of chapters.
    *   Item status (Pending, In Progress, Completed, Error) is displayed for each queue item.
    *   (Minor pending: Tooltip to show all chapters on mouseover if list is very long - current summary is generally sufficient).
*   **Phase 1.5: Queue Processing** [DONE]
    *   Add a "Run Queue" button at the bottom of the "Queue" tab (visible if items are in queue and not currently processing).
    *   Implement logic to process items in the queue sequentially.
    *   For each queued item, retrieve the stored settings and chapters.
    *   Execute the synthesis process for the chapters using the stored settings.
    *   The `core.main` function already handles output folder creation based on its parameters, which are derived from queued item settings.
    *   UI updates to show current item progress via main progress bar.
*   **Phase 1.6: State Persistence and UI Updates** [DONE]
    *   Database persistence for queue items (adding, removing, status updates) is implemented (`database.py`). [DONE]
    *   UI loads queue items from the database on startup. [DONE]
    *   UI updates status of items in the "Queue" tab display during processing. [DONE]
    *   Update the UI to reflect the status of chapters in the "Staging" tab *specifically based on queue completion* (e.g., replace checkbox with a checkmark). Current staging tab shows general status if chapters are processed individually. [DONE]
    *   UI for manually removing items from the "Queue" tab (and thus database). `remove_queue_item` in `database.py` exists. [DONE]
*   **Phase 1.7: Scheduling Functionality** [DONE]
    *   Add a "Schedule Queue" button at the bottom of the "Queue" tab. [DONE]
    *   Implement a mechanism to allow the user to specify a specific date and time to start processing the queue. [DONE]
    *   Implement logic to trigger the queue processing at the specified time. [DONE]

*   **Phase 1.8: Debugging Queue Display Issues** [IN PROGRESS]
    *   Purpose: To trace the flow of data and UI updates related to the queue tab, to identify why queued items are not appearing.
    *   Debugging statements added to `audiblez/ui.py`:
        *   In `on_queue_selected_book_portions` and `on_queue_selected_staged_chapters`:
            *   `print(f"DEBUG: Before DB reload, self.queue_items: {self.queue_items}")`
            *   `print(f"DEBUG: After DB reload, self.queue_items: {self.queue_items}")`
            *   `print("DEBUG: Calling refresh_queue_tab()")`
        *   In `refresh_queue_tab`:
            *   `print(f"DEBUG: refresh_queue_tab called. self.queue_items: {self.queue_items}")`
            *   `print("DEBUG: Called self.queue_tab_sizer.Clear(delete_windows=True)")` (after the call)
            *   If `self.queue_items` is empty: `print("DEBUG: Queue is empty, adding placeholder label.")`
            *   Inside the loop for items:
                *   `print(f"DEBUG: Processing queue item {item_idx}: {item_data.get('book_title')}")`
                *   `print(f"DEBUG: Added item_sizer for {item_data.get('book_title')} to queue_tab_sizer.")` (after adding)
            *   `print("DEBUG: Calling self.queue_tab_panel.SetupScrolling() and .Layout()")` (before the calls)
            *   `print("DEBUG: Calling self.notebook.Layout() and self.splitter_left.Layout()")` (before the calls)
        *   In `create_notebook_and_tabs` (for Queue tab setup):
            *   `print("DEBUG: Creating initial placeholder for Queue tab.")` (when the initial placeholder is added)
    *   Debugging Journey & Findings: [DONE]
        *   Initial issue: Queue items not displayed in UI. UI debug logs showed `self.queue_items` was always empty.
        *   Database debug logs (round 1): Showed items were committed by `add_item_to_queue` but `get_queued_items` found nothing.
        *   Root Cause: The `DROP TABLE IF EXISTS ...` statements for `synthesis_queue` and `queued_chapters` in the `create_tables` function were being executed on every new database connection. Since `connect_db()` (which calls `create_tables()`) was invoked by each high-level database operation (like adding an item, then getting all items), the queue tables were being wiped immediately after creation or before subsequent reads.
        *   Resolution:
            1.  Removed the `DROP TABLE IF EXISTS ...` statements for `synthesis_queue` and `queued_chapters` from `create_tables`.
            2.  Ensured the `CREATE TABLE` statements for `synthesis_queue` and `queued_chapters` correctly included the `IF NOT EXISTS` clause to prevent errors when `create_tables` is called multiple times after the tables already exist.
    *   This resolved the issue, and items now correctly persist in the database and are displayed in the queue tab.

*   **Phase 1.9: Remove Queue Display Debugging Statements** [DONE]
    *   All temporary `print()` statements added for debugging the queue display issue in `audiblez/ui.py` and `audiblez/database.py` have been removed.

**Phase 2: Text Filtering**

*   **Purpose:** To allow users to define custom text replacements (e.g., for abbreviations, Roman numerals) to prevent awkward pauses or mispronunciations by the TTS engine.
*   **Mechanism:**
    *   A `filter.txt` file (located in the `audiblez` directory) will store user-defined filter rules.
    *   Each rule will specify patterns to find (comma-separated) and a replacement string (e.g., "Mr.,mr.|Mister").
    *   Comments (`#`) and empty lines in `filter.txt` will be ignored.
*   **Implementation:**
    *   A function in `audiblez/core.py` will read `filter.txt` (if it exists and is not empty).
    *   This function will apply the defined replacements to the chapter text *before* it is sent to the TTS engine.
    *   If `filter.txt` is not present or is empty, the text will be processed as is.
*   **Benefits:**
    *   Improves the naturalness of the generated audio by handling common text patterns that TTS engines might otherwise misinterpret.
    *   Gives users control over specific text transformations.
    *   Reduces the need for manual audio editing for common issues.

**Phase 3: Calibre Integration**

*   **Phase 3.1: Add Calibre Option to UI**
    *   Add a new button or menu item in the UI ([`audiblez/ui.py`](audiblez/ui.py)) labeled "Open ebook with Calibre".
*   **Phase 3.2: Implement Calibre Conversion**
    *   In [`audiblez/core.py`](audiblez/core.py), create a new function (e.g., `convert_epub_with_calibre`) that takes an EPUB file path and an output directory.
    *   Implement a `subprocess` call within this function to execute the `ebook-convert` command to convert the EPUB to HTML in the specified output directory.
    *   Handle potential errors during the subprocess execution (e.g., Calibre not installed, conversion failure).
*   **Phase 3.3: Process Calibre HTML Output**
    *   Modify the book loading logic in [`audiblez/ui.py`](audiblez/ui.py) and [`audiblez/core.py`](audiblez/core.py) to handle the output from the Calibre conversion.
    *   If `ebook-convert` produces multiple HTML files (one per chapter), adapt the chapter reading logic to iterate through these files.
    *   If `ebook-convert` produces a single large HTML file, potentially adapt the [`find_document_chapters_and_extract_texts`](audiblez/core.py:224) function in [`audiblez/core.py`](audiblez/core.py) to identify chapters based on HTML tags (like `<h1>`, `<h2>`) generated by Calibre.
*   **Phase 3.4: Integrate Calibre Workflow into UI**
    *   Connect the "Open ebook with Calibre" UI action to the new Calibre conversion and processing logic.

**Future Feature (Output Type):**

*   This feature (mentioned in Idea 1) would involve adding an option to select the output file type (e.g., MP3, M4B, WAV) and integrating this into the synthesis process and the queue item settings. This can be planned in detail once the core features are implemented.
