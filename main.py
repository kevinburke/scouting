import sys
import re
from PyPDF2 import PdfReader


def process_box_score(content):
    rows = []
    game_teams = []
    team_index = 0
    player_header_count = 0

    lines = content.split('\n')
    for i, line in enumerate(lines):
        # 1) Detect the teams line
        m = re.search(
            r'([\w/]+)\s+\([WL]-\d+\)\s+(vs|va)\s+([\w/ ]+)\s+\([WL]-\d+\)',
            line
        )
        if m:
            game_teams = [m.group(1), m.group(3)]
            team_index = 0
            player_header_count = 0
            print(f"[Line {i}] Teams → {game_teams}")
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
            print(f"[Line {i}] PLAYER header; prev line “{prev}” → team_index={team_index}")
            player_header_count += 1
            continue

        # 3) Collect stat lines
        if re.match(r'^\s*\d', line):
            parts = re.split(r'\s+', line.strip())
            if 'Y' in parts:
                parts.remove('Y')
            if len(parts) > 10 and parts[0] == '0':
                name = game_teams[team_index] if game_teams else "<NO TEAM>"
                parts.insert(0, name)
                rows.append(parts)
                print(f"[Line {i}] Row[{team_index}] for {name}: {parts}")

    print(f"Done, total rows = {len(rows)}")
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

def main():
    if len(sys.argv) < 2:
        print("Usage: script.py <pdf_file1> <pdf_file2> ...")
        sys.exit(1)

    all_rows = []
    for pdf_file in sys.argv[1:]:
        # print(f"\nProcessing {pdf_file}")  # Debug
        reader = PdfReader(pdf_file)
        content = ''
        for page in reader.pages:
            content += page.extract_text() + '\n'

        try:
            new_rows = process_box_score(content)
            # print(f"Found {len(new_rows)} rows")  # Debug
            all_rows.extend(new_rows)
        except Exception as e:
            print(f"Error processing {pdf_file}: {e}", file=sys.stderr, flush=True)
            raise

    cleaned_rows = cleanup_data(all_rows)

    # print("\nFinal output:")
    print('\n'.join(','.join(row) for row in cleaned_rows))

if __name__ == "__main__":
    main()
