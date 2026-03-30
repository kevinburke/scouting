import sys
import re
import hashlib
from datetime import date
from pathlib import Path
from PyPDF2 import PdfReader

MONTH_ABBREVS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}


def parse_date_from_filename(filepath):
    """Extract game date from filename like SO35_Team1_Team2_mar2.pdf.

    Looks for a year in the directory path (e.g. data/2026/o35/).
    Returns a date string like '2026-03-02'.
    """
    path = Path(filepath)
    year = None
    for parent in path.parents:
        try:
            y = int(parent.name)
            if 2020 <= y <= 2040:
                year = y
                break
        except ValueError:
            continue
    if year is None:
        year = date.today().year

    date_part = path.stem.split('_')[-1]
    m = re.match(r'([a-zA-Z]+)(\d+)$', date_part)
    if not m:
        raise ValueError(f"cannot parse date from filename: {filepath}")
    month_str, day_str = m.group(1).lower(), m.group(2)
    month = MONTH_ABBREVS.get(month_str)
    if month is None:
        raise ValueError(f"unknown month abbreviation {month_str!r} in {filepath}")
    return f'{month}/{int(day_str)}/{year}'


def process_box_score(content):
    rows = []
    game_teams = []
    team_index = 0
    player_header_count = 0

    lines = content.split('\n')
    for i, line in enumerate(lines):
        # 1) Detect the teams line
        m = re.search(
            r'([\w/]+)\s+\([WL]-\d+\)\s+(vs|va)\s+([\w/\' ]+)\s+\([WL]-\d+\)',
            line
        )
        if m:
            game_teams = [m.group(1), m.group(3)]
            team_index = 0
            player_header_count = 0
            print(f"[Line {i}] Teams → {game_teams}", file=sys.stderr)
            continue

        # 2) On PLAYER header, pick team by count or by contains-match
        if re.match(r'^\s*PLAYER\s+', line):
            if len(game_teams) < 2:
                raise ValueError(f"[Line {i}] PLAYER but no game_teams yet!")
            prev = lines[i-1].strip()
            # Try partial‐string match first
            if game_teams[1].lower() in prev.lower():
                team_index = 1
            elif game_teams[0].lower() in prev.lower():
                team_index = 0
            else:
                # fallback to “first header → team 0, second → team 1”
                team_index = min(player_header_count, 1)
            print(f"[Line {i}] PLAYER header; prev line \"{prev}\" → team_index={team_index}", file=sys.stderr)
            player_header_count += 1
            continue

        # 3) Collect stat lines
        if re.match(r'^\s*\d', line):
            parts = re.split(r'\s+', line.strip())
            if 'Y' in parts:
                parts.remove('Y')
            if len(parts) > 25 and parts[0] == '0':
                # Try to find where the second player starts
                # Look for a pattern like: number followed by letters (player name)
                split_index = None
                for i in range(10, len(parts) - 10):  # Don't split too early or too late
                    # Look for a part that looks like a player name (contains letters)
                    if re.match(r'^[A-Za-z]', parts[i]):
                        # Check if the previous part looks like the end of stats (number or percentage)
                        prev_part = parts[i-1]
                        if re.match(r'^\d+(\.\d+)?$', prev_part):
                            split_index = i
                            break

                if split_index:
                    print(f"Detected double line, splitting at index {split_index}", file=sys.stderr)
                    first_player = parts[:split_index]
                    second_player = parts[split_index:]

                    # Process first player
                    name1 = game_teams[team_index] if game_teams else "<NO TEAM>"
                    first_player.insert(0, name1)
                    rows.append(first_player)
                    print(f"[Line {i}] Row[{team_index}] for {name1}: {first_player}", file=sys.stderr)

                    # Process second player (same team)
                    if 'Y' in second_player:
                        second_player.remove('Y')
                    name2 = game_teams[team_index] if game_teams else "<NO TEAM>"
                    second_player.insert(0, name2)
                    rows.append(second_player)
                    print(f"[Line {i}] Row[{team_index}] for {name2}: {second_player}", file=sys.stderr)
                else:
                    print("Could not find split point for double line", file=sys.stderr)
            elif len(parts) > 10 and parts[0] == '0':
                name = game_teams[team_index] if game_teams else "<NO TEAM>"
                parts.insert(0, name)
                rows.append(parts)
                print(f"[Line {i}] Row[{team_index}] for {name}: {parts}", file=sys.stderr)

    print(f"Done, total rows = {len(rows)}", file=sys.stderr)
    return rows

def cleanup_data(all_rows):
   cleaned_rows = []
   for row in all_rows:
       # Create new row without unwanted columns
       new_row = row[:1]  # Keep team name
       new_row.extend(row[2:15])  # Stats before FG%
       new_row.extend(row[16:18])  # Between FG% and 3FG%
       new_row.extend(row[19:21])  # Between 3FG% and FT%
       new_row.extend(row[22:])    # After FT% to end
       cleaned_rows.append(new_row)
   return cleaned_rows


def expand_pdf_inputs(args):
    pdf_files = []
    for arg in args:
        path = Path(arg)
        if path.is_dir():
            pdf_files.extend(
                sorted(
                    (child for child in path.iterdir() if child.is_file() and child.suffix.lower() == ".pdf"),
                    key=lambda child: child.name.lower(),
                )
            )
        else:
            pdf_files.append(path)
    return [str(path) for path in pdf_files]

def main():
    if len(sys.argv) < 2:
        print("Usage: script.py <pdf_file_or_directory1> <pdf_file_or_directory2> ...", file=sys.stderr)
        sys.exit(1)

    pdf_files = expand_pdf_inputs(sys.argv[1:])
    if not pdf_files:
        print("Error: no PDF files found", file=sys.stderr)
        sys.exit(1)

    # Check for duplicate files (same content, possibly different names)
    file_hashes = {}  # hash -> filename
    for pdf_file in pdf_files:
        with open(pdf_file, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        if file_hash in file_hashes:
            print(f"Error: duplicate file detected: '{pdf_file}' has the same content as '{file_hashes[file_hash]}'", file=sys.stderr)
            sys.exit(1)
        file_hashes[file_hash] = pdf_file

    all_rows = []
    for pdf_file in pdf_files:
        reader = PdfReader(pdf_file)
        content = ''
        for page in reader.pages:
            content += page.extract_text() + '\n'

        try:
            game_date = parse_date_from_filename(pdf_file)
            new_rows = process_box_score(content)
            for row in new_rows:
                row.append(game_date)
            all_rows.extend(new_rows)
        except Exception as e:
            print(f"Error processing {pdf_file}: {e}", file=sys.stderr, flush=True)
            raise

    cleaned_rows = cleanup_data(all_rows)

    # The date was appended to the end of each row before cleanup.
    # Move it to index 2 (after team, player) for output.
    for row in cleaned_rows:
        game_date = row.pop()
        row.insert(2, game_date)

    # Sort by team (col 0), then date (col 2), then player (col 1)
    def sort_key(row):
        # Parse m/d/yyyy for proper date sorting
        parts = row[2].split('/')
        return (row[0], (int(parts[2]), int(parts[0]), int(parts[1])), row[1])
    cleaned_rows.sort(key=sort_key)

    print('\n'.join(','.join(row) for row in cleaned_rows))

if __name__ == "__main__":
    main()
