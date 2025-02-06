import sys
import re
from PyPDF2 import PdfReader

def process_box_score(content):
    rows = []
    current_team = ''
    game_teams = []
    team_index = 0

    lines = content.split('\n')
    for i, line in enumerate(lines):
        match = re.search(r'(\w+)\s+\([WL]-\d+\)\s+vs\s+(\w+)\s+\([WL]-\d+\)', line)
        if match:
            game_teams = [match.group(1), match.group(2)]
            team_index = 0
            continue

        team_match = re.search(r'^\s*(\w+)\s+', line)
        if team_match and team_match.group(1) == "PLAYER":
            team_section = lines[i-1].strip()
            print(lines[i-1])
            team_index = 1 if team_section.lower() == game_teams[1].lower() else 0
            continue

        if re.match(r'^\s*\d', line):
            parts = re.split(r'\s+', line.strip())
            if len(parts) > 10:
                if 'Y' in parts:
                    parts.remove('Y')
                if parts[0] == '0':
                    parts.insert(0, game_teams[team_index])
                    rows.append(parts)

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

        new_rows = process_box_score(content)
        # print(f"Found {len(new_rows)} rows")  # Debug
        all_rows.extend(new_rows)

    cleaned_rows = cleanup_data(all_rows)

    print("\nFinal output:")
    print('\n'.join(','.join(row) for row in cleaned_rows))

if __name__ == "__main__":
    main()
