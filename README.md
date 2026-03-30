# Scouting

Extract basketball box score stats from PDF files and update a Google Sheet with
per-player-per-game data and per-team analysis.

## Setup

Create a Python 3.14+ virtual environment and install dependencies:

    python3 -m venv venv
    venv/bin/pip install -r requirements.txt

You need a Google Cloud service account with the Sheets API enabled. Place the
credentials JSON file at `config/credentials.json`. Share the target Google
Sheet with the service account's email address (Editor access).

## Usage

### Extract stats from PDFs (CSV to stdout)

    venv/bin/python main.py data/2026/o35

Each row is one player's stats for one game:

    Team, Player, Date, Points, ...

### Update Google Sheet

    venv/bin/python update_sheet.py --sheet-name "O35 2026" data/2026/o35

The `--sheet-name` flag specifies which worksheet tab to update. This will:

1. Run `main.py` on the given PDFs to extract per-game stats.
2. Write the raw data to columns A-U of the named sheet, sorted by team
   then date.
3. Generate per-team analysis blocks in columns W-AP, each containing:
   - Team name (bold)
   - Aggregated player stats (games, points, PPG, rebounds, shooting
     percentages, etc.)
   - Team summary row
   - Shooting breakdown table sorted by efficiency

The sheet is cleared and fully regenerated on each run, so it's safe to re-run
whenever new game PDFs are added.

## PDF file naming

PDF filenames should follow the pattern:

    SO35_Team1_Team2_monthday.pdf

For example: `SO35_OMeara_Enoka_feb23.pdf`. The date is extracted from the
filename and the year from the directory path (e.g. `data/2026/`).
