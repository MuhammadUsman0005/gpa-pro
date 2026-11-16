# GPA Pro — Academic Performance Tracker
**Muhammad Usman**
A desktop GPA management application built with **Python** and **Tkinter**. GPA Pro helps students record courses across semesters, calculate SGPA and CGPA, monitor academic progress, and plan future results.

> **Important:** The built-in `Custom (University)` grading scale is a default preset, not a guarantee that it matches your institution. Check your university's official grading policy and edit the scale in **Settings & Security** before relying on the results.

## Features

- **Semester management:** Add, rename, and remove semesters.
- **SGPA and CGPA:** Calculate semester and cumulative GPA using course credit hours.
- **Performance dashboard:** View CGPA, total credit hours, latest SGPA, academic standing, and a semester trend chart.
- **Editable grading scales:** Choose the built-in Custom (University) or US 4.0 preset, or define your own mark-to-GPA scale.
- **Retake policies:** Choose to keep all attempts, use the latest attempt, or use the best attempt.
- **Target CGPA planner:** Estimate the average GPA needed across remaining credit hours.
- **What-if calculator:** Simulate how a hypothetical course could affect CGPA.
- **Data import and export:** Import and export course records as CSV.
- **Project files:** Save and reopen GPA Pro project files; saved projects include a SHA-256 integrity checksum.
- **Reports:** Generate an HTML academic report that can be printed or saved as PDF from a browser.
- **Convenience:** Automatic local save, undo (`Ctrl+Z`), dark/light themes, and keyboard shortcuts.
- **Optional encryption:** Password-protect project files using Fernet encryption from the optional `cryptography` package.

## Requirements

- Python **3.9 or newer**
- Tkinter (usually included with standard Python installations)

The core application uses Python's standard library. No third-party package is required to run the basic calculator.

### Optional encryption support

Install `cryptography` to enable password-encrypted project files:

```bash
python -m pip install cryptography
```

Without this optional package, the app still runs and can save normal, unencrypted project files.

## Run the application

1. Install Python 3.9 or newer.
2. Download or clone this repository.
3. Open a terminal in the project folder.
4. Run the application:

**Windows**

```powershell
py gpa_pro.py
```

**macOS / Linux**

```bash
python3 gpa_pro.py
```

If the `py` command is not available on Windows, try `python gpa_pro.py`.

## How GPA is calculated

For each semester, the application calculates the credit-hour-weighted SGPA:

\[
\text{SGPA} = \frac{\sum(\text{Course GPA} \times \text{Credit Hours})}{\sum(\text{Credit Hours})}
\]

CGPA is calculated from the counted course attempts and their credit hours, according to the selected retake policy. Under the **latest** and **best** policies, courses are matched by course name (case-insensitively). Keep semester records in chronological order when using the latest-attempt policy.

## Configure your university's grading scale

1. Open **Settings & Security**.
2. Select **Custom (University)** or **Custom edited**.
3. Edit the mark-to-GPA rules. Use one rule per line in this format:

```text
minimum_marks,gpa
```

Example only — replace these values with your university's official rules:

```text
85,4.0
80,3.5
75,3.0
70,2.5
60,2.0
```

Each rule represents the GPA awarded at or above that minimum mark. Marks below the lowest rule receive `0.0`. Click **Apply custom scale** to use the edited scale.

## Saving and privacy

- Use **Save** to create a GPA Pro project file (`.gpa`) and **Open** to reopen it.
- The app also creates a local autosave in the user's home directory under `.gpa_pro`.
- Project files are saved locally. This application does not provide cloud synchronization.
- Optional password encryption requires `cryptography`. Keep your password safe; an encrypted file cannot be opened without it.
- Do not commit personal GPA records, exported reports, or password-protected project files to a public repository.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl + Z` | Undo |
| `Ctrl + S` | Save project |
| `Ctrl + O` | Open project |
| `Ctrl + N` | Add course |
| `Delete` | Remove selected course(s) when the course table is focused |

## Project structure

```text
gpa-pro/
├── gpa_pro.py
├── README.md
└── .gitignore
```

## Known limits

- Maximum **30 semesters**.
- Maximum **40 courses per semester**.
- Course marks must be between **0 and 100**.
- Course credit hours must be greater than **0** and no more than **12**.
- GPA results depend on the grading scale and retake policy selected by the user. Always verify these settings against your institution's rules.

## Contributing

Bug reports, suggestions, and pull requests are welcome. For substantial changes, describe the problem and proposed behavior before submitting a pull request.
