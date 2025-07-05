# Dark Mode Implementation Plan for Audiblez

This document outlines a two-phased plan to refactor the Audiblez UI for themeability and then implement a comprehensive dark mode. The approach is designed to first replace theme-resistant native widgets with generic, stylable alternatives and then apply the new theme, ensuring a clean and maintainable result without adding external dependencies.

---

## Phase 1: UI Refactoring for Themeability

**Objective:** Replace native `wx` widgets with their generic, stylable counterparts from the standard `wxPython` library. The application's appearance and functionality should remain as close to the original as possible at the end of this phase.

### Action Items

1.  **Replace `wx.Notebook` with `FlatNotebook`**
    *   **Target:** `self.notebook` created in `create_notebook_and_tabs`.
    *   **Action:** Change the widget class from `wx.Notebook` to `wx.lib.agw.flatnotebook.FlatNotebook`.
    *   **Details:** The API is very similar, making this a low-impact change. Import `from wx.lib.agw import flatnotebook as fnb` and instantiate `fnb.FlatNotebook`.

2.  **Replace `wx.ListCtrl` with `UltimateListCtrl`**
    *   **Targets:** `self.table` in `create_chapters_table_panel` and `chapters_list_ctrl` in `refresh_staging_tab`.
    *   **Action:** Replace `wx.ListCtrl` with `wx.lib.agw.ultimatelistctrl.UltimateListCtrl`.
    *   **Details:** This is a significant but necessary change. The API for adding items and enabling checkboxes (`ULC_CHECKBOX` style) differs from `wx.ListCtrl`. Event handlers like `EVT_LIST_ITEM_CHECKED` will remain the same.

3.  **Replace `wx.StaticBoxSizer` with Styled Panels**
    *   **Targets:** All instances of `wx.StaticBoxSizer` (e.g., in `create_right_panel`, `create_params_panel`).
    *   **Action:** Replace the `StaticBoxSizer` with a standard `wx.BoxSizer` containing a `wx.Panel`. The panel will have a `wx.STATIC_BORDER` style, and a `wx.StaticText` label will be placed inside or above it to mimic the labeled box.
    *   **Details:** This requires restructuring the sizers in the right-hand panel to use nested panels and sizers instead of `StaticBoxSizer`.

4.  **Replace `wx.ComboBox` with `ComboCtrl`**
    *   **Target:** `self.voice_dropdown` in `create_params_panel`.
    *   **Action:** Replace `wx.ComboBox` with `wx.combo.ComboCtrl`.
    *   **Details:** A `wx.ListBox` will be used as the popup control for the `ComboCtrl`. The logic for populating the list and handling selections will need to be adapted.

5.  **Replace `wx.RadioButton` with `ToggleButton` Groups**
    *   **Targets:** The "Engine" and "M4B Assembly" radio buttons.
    *   **Action:** Replace `wx.RadioButton` groups with groups of `wx.ToggleButton`.
    *   **Details:** An event handler will be created for each group to enforce radio button behavior (i.e., only one button can be toggled "on" at a time).

6.  **Replace `wx.CheckBox` with `GenCheckBox`**
    *   **Target:** `final_comp_checkbox` in `refresh_staging_tab`.
    *   **Action:** Replace `wx.CheckBox` with `wx.lib.checkbox.GenCheckBox`.
    *   **Details:** This is a mostly drop-in replacement with a similar API.

7.  **Replace `wx.Gauge` with a Custom Panel**
    *   **Target:** `self.progress_bar` in `create_synthesis_panel`.
    *   **Action:** Create a new `CustomGauge(wx.Panel)` class. This class will handle its own `OnPaint` event to draw two rectangles: one for the background and one for the progress fill, based on its current value.
    *   **Details:** The class will need methods like `SetValue` and `SetRange` to mimic the `wx.Gauge` API for seamless integration.

8.  **Replace `DatePickerCtrl` with `CalendarCtrl`**
    *   **Target:** `self.date_picker` in the `ScheduleDialog`.
    *   **Action:** Replace `wx.adv.DatePickerCtrl` with `wx.lib.calendar.CalendarCtrl`.
    *   **Details:** The dialog's layout will be adjusted to accommodate the larger, fully stylable calendar widget.

---

## Phase 2: Dark Mode Implementation

**Objective:** Implement the dark mode theme, add a UI toggle, and persist the user's preference.

### Theme Application Flow

```mermaid
graph TD
    subgraph "App Startup / User Action"
        A[App Init] --> B{Load 'dark_mode' setting};
        C[User Clicks 'Dark Mode' Checkbox] --> D{Save 'dark_mode' setting};
    end

    subgraph "Theme Application Logic"
        B --> E[apply_theme(theme)];
        D --> E;
        E --> F[Get Theme Colors from Palette];
        F --> G[Set Main Window Colors];
        F --> H[Set All Panel Colors];
        F --> I[Style All Generic Widgets];
    end

    subgraph "Styling Generic Widgets (from Phase 1)"
        I --> J(Style FlatNotebook);
        I --> K(Style UltimateListCtrl);
        I --> L(Style ToggleButtons);
        I --> M(Style CustomGauge);
        I --> N(Style GenCheckBox);
    end
```

### Action Items

1.  **Create a Central Theme Manager**
    *   **Action:** Create a global dictionary or a simple class to define color palettes for "light" and "dark" modes. This will centralize all color definitions.
    *   **Details:** Define key colors for backgrounds, foregrounds (text), panel surfaces, borders, and highlights.

2.  **Add "Dark Mode" Toggle to UI**
    *   **Target:** The `top_sizer` in the `create_layout` function.
    *   **Action:** Add a `wx.lib.checkbox.GenCheckBox` labeled "🌙 Dark Mode" to the top panel, next to the "About" button.

3.  **Implement Theme Switching Logic**
    *   **Action:** Create a primary method, `apply_theme(self, dark_mode_enabled)`. This method will be the engine for all visual changes.
    *   **Details:** The method will read from the theme manager and recursively apply `SetBackgroundColour` and `SetForegroundColour` to the main frame and all its children panels. It will then call specific styling functions for the complex generic widgets.

4.  **Apply Theme to Generic Widgets**
    *   **Action:** Within `apply_theme`, call helper methods to style the widgets replaced in Phase 1.
    *   **Details:**
        *   **FlatNotebook:** Use methods like `SetActiveTabColour`, `SetTabAreaColour`, and `SetForegroundColour`.
        *   **UltimateListCtrl:** Use methods to set the colors for headers, rows (including alternating row colors), and text.
        *   **CustomGauge:** Simply call `Refresh()` on the gauge panel. Its `OnPaint` handler will use the theme colors to redraw itself.
        *   **ToggleButton/GenCheckBox:** Use `SetBackgroundColour` and `SetForegroundColour`.

5.  **Persist User Preference**
    *   **Action:** Save the dark mode state in the application's database.
    *   **Details:**
        *   In the "Dark Mode" checkbox event handler, call `db.save_user_setting('dark_mode', is_checked)`.
        *   In `MainWindow.__init__`, load the `'dark_mode'` setting from `db.load_all_user_settings()` and call `apply_theme` on startup to reflect the saved preference.

6.  **Final Polish**
    *   **Action:** Thoroughly review the entire application in both light and dark modes.
    *   **Details:** Check all dialogs (`ScheduleDialog`, `about_dialog`), message boxes, and text controls for any unstyled elements and apply theme colors as needed.