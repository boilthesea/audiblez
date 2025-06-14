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

*   **Phase 0.1: SQLite Database Setup**
    *   Create a new file, [`audiblez/database.py`](audiblez/database.py), to handle SQLite database operations.
    *   Implement functions to connect to `audiblez.db`.
    *   Create necessary tables for storing user settings, staged books/chapters, and the synthesis queue.
*   **Phase 0.2: Remember User Settings**
    *   Modify the UI ([`audiblez/ui.py`](audiblez/ui.py)) to load the last used engine, voice, and speed settings from the database on startup.
    *   Modify the UI to save the current engine, voice, and speed settings to the database whenever they are changed.
    *   Update [`audiblez/cli.py`](audiblez/cli.py) to potentially load default settings from the database if not provided via command line arguments.
*   **Phase 0.3: User Editable Rate**
    *   Add a new input field in the UI ([`audiblez/ui.py`](audiblez/ui.py)) for the user to enter a custom characters-per-second rate.
    *   Store this custom rate in the database.
    *   Modify the progress calculation in [`audiblez/core.py`](audiblez/core.py) to use the user-defined rate if available, falling back to the default if not set.

**Phase 1: Calibre Integration**

*   **Phase 1.1: Add Calibre Option to UI**
    *   Add a new button or menu item in the UI ([`audiblez/ui.py`](audiblez/ui.py)) labeled "Open ebook with Calibre".
*   **Phase 1.2: Implement Calibre Conversion**
    *   In [`audiblez/core.py`](audiblez/core.py), create a new function (e.g., `convert_epub_with_calibre`) that takes an EPUB file path and an output directory.
    *   Implement a `subprocess` call within this function to execute the `ebook-convert` command to convert the EPUB to HTML in the specified output directory.
    *   Handle potential errors during the subprocess execution (e.g., Calibre not installed, conversion failure).
*   **Phase 1.3: Process Calibre HTML Output**
    *   Modify the book loading logic in [`audiblez/ui.py`](audiblez/ui.py) and [`audiblez/core.py`](audiblez/core.py) to handle the output from the Calibre conversion.
    *   If `ebook-convert` produces multiple HTML files (one per chapter), adapt the chapter reading logic to iterate through these files.
    *   If `ebook-convert` produces a single large HTML file, potentially adapt the [`find_document_chapters_and_extract_texts`](audiblez/core.py:224) function in [`audiblez/core.py`](audiblez/core.py) to identify chapters based on HTML tags (like `<h1>`, `<h2>`) generated by Calibre.
*   **Phase 1.4: Integrate Calibre Workflow into UI**
    *   Connect the "Open ebook with Calibre" UI action to the new Calibre conversion and processing logic.

**Phase 2: Staging and Queuing**

*   **Phase 2.1: UI Tabs and Basic Structure**
    *   Modify the UI ([`audiblez/ui.py`](audiblez/ui.py)) to replace the single chapters panel with a tabbed interface containing "Chapters", "Staging", and "Queue" tabs.
    *   The "Chapters" tab will retain the current functionality.
    *   Implement the basic structure for the "Staging" and "Queue" tabs.
*   **Phase 2.2: Staging Functionality**
    *   Add a "Stage Book" option (button or context menu) in the "Chapters" tab.
    *   Implement logic to move the currently loaded book and its chapters to the "Staging" tab when "Stage Book" is selected.
    *   Store the staged book and its chapters in the database, including book metadata.
    *   Display staged chapters nested under the book title in the "Staging" tab, with checkboxes for selection.
    *   Add a "Final Compilation" checkbox per book in the "Staging" tab.
*   **Phase 2.3: Queuing Functionality**
    *   Add a "Queue Selected Chapters" option in the "Staging" tab.
    *   Implement logic to add selected chapters from the "Staging" tab to the "Queue" tab.
    *   When queuing, capture the current synthesis settings (engine, voice, speed, output folder, output type - assuming output type is added later) and store them with the queued item in the database.
    *   Add an option to "Queue Whole Book" directly from the "Chapters" tab, which stages the book and then queues all its chapters with current settings.
*   **Phase 2.4: Queue Display and Management**
    *   Display queued items in the "Queue" tab, showing the captured settings for each item.
    *   Implement the summary display for queued chapters (e.g., "Chapter 1-5", "Chapter 1, 3, 5...").
    *   Implement the tooltip functionality to show all chapters in a queued item on mouseover.
*   **Phase 2.5: Queue Processing**
    *   Add a "Run Queue" button at the bottom of the "Queue" tab.
    *   Implement logic to process items in the queue sequentially.
    *   For each queued item, retrieve the stored settings and chapters.
    *   Execute the synthesis process for the chapters using the stored settings.
    *   Create a new folder for the WAV files for each queued book synthesis job.
*   **Phase 2.6: State Persistence and UI Updates**
    *   Modify the synthesis process to update the status of chapters in the database as they are completed.
    *   Update the UI to reflect the status of chapters in the "Staging" tab (e.g., replace checkbox with a checkmark for completed chapters).
    *   Implement loading the state of staged books, chapters, and the queue from the database on application startup.
*   **Phase 2.7: Scheduling Functionality**
    *   Add a "Schedule Queue" button at the bottom of the "Queue" tab.
    *   Implement a mechanism to allow the user to specify a specific date and time to start processing the queue.
    *   Implement logic to trigger the queue processing at the specified time.

**Future Feature (Output Type):**

*   This feature (mentioned in Idea 1) would involve adding an option to select the output file type (e.g., MP3, M4B, WAV) and integrating this into the synthesis process and the queue item settings. This can be planned in detail once the core features are implemented.
