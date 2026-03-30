#!/usr/bin/env python3
"""Update Google Sheet with scouting data from PDFs.

Usage: update_sheet.py <pdf_directory_or_files...>

Writes raw per-game player stats to columns A-U of the "O35 2026" sheet,
then generates per-team analysis blocks in columns W-AP.
"""

import subprocess
import sys
from collections import defaultdict

import gspread

SPREADSHEET_ID = '1eQjM2vG4t6aASjxoRgW_83EVyk1xBu85nrLxHsRcg0U'
SHEET_NAME = 'O35 2026'
CREDENTIALS_FILE = 'config/credentials.json'

# Raw data columns (A-U):
#   A=Team, B=Player, C=Date, D-U=Stats
# With date in C, stat columns shift +1 vs the old layout:
#   D=Points (was C), F=OR (was E), G=DR (was F), I=TO (was H),
#   J=Steals (was I), N=FGM (was M), O=FGA (was N), P=3PM (was O),
#   Q=3PA (was P), R=FTM (was Q), S=FTA (was R)


def get_csv_data(args):
    """Run main.py and return parsed CSV rows."""
    result = subprocess.run(
        [sys.executable, 'main.py'] + args,
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    rows = []
    for line in result.stdout.strip().split('\n'):
        if line:
            rows.append(line.split(','))
    return rows


def build_team_rosters(raw_rows):
    """Return {team: [player, ...]} from raw data, sorted alphabetically."""
    team_players = defaultdict(set)
    for row in raw_rows:
        team, player = row[0], row[1]
        team_players[team].add(player)
    return {
        team: sorted(players)
        for team, players in sorted(team_players.items())
    }


def build_analysis_block(team, players, start_row, num_raw_rows):
    """Build analysis rows for one team starting at start_row (1-indexed).

    Returns a list of rows for columns W-AP (20 columns each).
    Row layout: team name, header, player rows, blank, summary, blank, shooting.
    """
    n = len(players)
    pr = start_row + 2  # first player row (after team name + header)
    lr = start_row + 1 + n  # last player row
    R = num_raw_rows     # raw data ends at this row

    rows = []

    # Team name row
    team_row = [''] * 20
    team_row[0] = team
    rows.append(team_row)

    # Header — prefix '2PM' etc. with apostrophe so Sheets doesn't parse as time
    rows.append([
        '', 'Games', 'Points', 'PPG', 'OR', 'DR', 'Rebounds', 'Steals',
        "'2PM", "'2PA", "'2%", "'3PM", "'3PA", 'Volume', "'3%", 'EFG',
        'TO', 'FTM', 'FTA', 'FT Pct',
    ])

    # Player rows — column references shifted +1 for date column C
    for i, player in enumerate(players):
        r = pr + i
        rows.append([
            player,
            # X: Games (count rows where player has any nonzero stat)
            f'=SUMPRODUCT(($B$1:$B${R}=W{r})'
            f'*(MMULT(($D$1:$U${R}<>0)*1,'
            f'TRANSPOSE(COLUMN($D$1:$U$1)^0))>0))',
            # Y: Points (col D)
            f'=SUMIF($B$1:$B${R},W{r},D$1:D${R})',
            # Z: PPG
            f'=IFERROR(Y{r}/X{r},0)',
            # AA: OR (col F)
            f'=SUMIF($B$1:$B${R},W{r},F$1:F${R})',
            # AB: DR (col G)
            f'=SUMIF($B$1:$B${R},W{r},G$1:G${R})',
            # AC: Rebounds per game
            f'=IFERROR((AA{r}+AB{r})/X{r},0)',
            # AD: Steals (col J)
            f'=SUMIF($B$1:$B${R},W{r},J$1:J${R})',
            # AE: 2PM = FGM - 3PM (cols N, P)
            f'=SUMIF($B$1:$B${R},W{r},N$1:N${R})-AH{r}',
            # AF: 2PA = FGA - 3PA (cols O, Q)
            f'=SUMIF($B$1:$B${R},W{r},O$1:O${R})-AI{r}',
            # AG: 2%
            f'=IFERROR(AE{r}/AF{r},0)',
            # AH: 3PM (col P)
            f'=SUMIF($B$1:$B${R},W{r},P$1:P${R})',
            # AI: 3PA (col Q)
            f'=SUMIF($B$1:$B${R},W{r},Q$1:Q${R})',
            # AJ: Volume (3PA per game)
            f'=IFERROR(AI{r}/X{r},0)',
            # AK: 3%
            f'=IFERROR(AH{r}/AI{r},0)',
            # AL: EFG
            f'=AK{r}*1.5',
            # AM: TO (col I)
            f'=SUMIF($B$1:$B${R},W{r},I$1:I${R})',
            # AN: FTM (col R)
            f'=SUMIF($B$1:$B${R},W{r},R$1:R${R})',
            # AO: FTA (col S)
            f'=SUMIF($B$1:$B${R},W{r},S$1:S${R})',
            # AP: FT%
            f'=IFERROR(AN{r}/AO{r},0)',
        ])

    # Blank row
    rows.append([''] * 20)

    # Summary row
    sr = lr + 2  # summary row number (blank row in between, after last player)
    summary = [''] * 20
    summary[4] = f'=SUM(AA{pr}:AA{lr})'                          # AA: OR total
    summary[5] = f'=SUM(AB{pr}:AB{lr})'                          # AB: DR total
    summary[7] = f'=SUM(AD{pr}:AD{lr})/MAX(X{pr}:X{lr})'        # AD: Steals/gm
    summary[9] = f'=SUM(AF{pr}:AF{lr})'                          # AF: 2PA total
    summary[10] = f'=SUM(AE{pr}:AE{lr})/SUM(AF{pr}:AF{lr})'     # AG: 2%
    summary[12] = f'=SUM(AI{pr}:AI{lr})'                         # AI: 3PA total
    summary[13] = f'=AI{sr}/MAX(X{pr}:X{lr})'                    # AJ: Volume
    summary[14] = f'=SUM(AH{pr}:AH{lr})/SUM(AI{pr}:AI{lr})'     # AK: 3%
    summary[15] = f'=AK{sr}*1.5'                                  # AL: EFG
    summary[16] = f'=SUM(AM{pr}:AM{lr})/MAX(X{pr}:X{lr})'       # AM: TO/gm
    rows.append(summary)

    # Blank row
    rows.append([''] * 20)

    # Shooting table (ARRAYFORMULA that spills 2*N rows)
    shooting = [''] * 20
    shooting[0] = (
        f'=ARRAYFORMULA(SORT({{'
        f'W{pr}:W{lr},'
        f'IF(LEN(W{pr}:W{lr}),"2PT",""),'
        f'AF{pr}:AF{lr},'
        f'AG{pr}:AG{lr};'
        f'W{pr}:W{lr},'
        f'IF(LEN(W{pr}:W{lr}),"3PT",""),'
        f'AI{pr}:AI{lr},'
        f'AL{pr}:AL{lr}'
        f'}},4,FALSE))'
    )
    rows.append(shooting)

    # Total block height: 1 (team name) + 1 (header) + N (players) + 1 (blank)
    #   + 1 (summary) + 1 (blank) + 1 (shooting formula) + (2*N - 1) (spill)
    #   + 2 (padding)
    # = 3*N + 7
    return rows, 3 * n + 7


def clear_formatting(sh, ws):
    """Clear number formatting and text formatting (bold/italic) from the
    analysis area (columns W onward)."""
    sh.batch_update({
        "requests": [{
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 0,
                    "endRowIndex": ws.row_count,
                    "startColumnIndex": 22,  # column W
                    "endColumnIndex": ws.col_count,
                },
                "cell": {"userEnteredFormat": {}},
                "fields": "userEnteredFormat.numberFormat,"
                          "userEnteredFormat.textFormat.bold,"
                          "userEnteredFormat.textFormat.italic",
            }
        }]
    })


def format_analysis(ws, block_infos, end_row):
    """Apply number formatting to all analysis blocks.

    block_infos: list of (start_row, n_players) for each team.
    """
    pct = {"numberFormat": {"type": "PERCENT", "pattern": "0.00%"}}
    dec2 = {"numberFormat": {"type": "NUMBER", "pattern": "0.00"}}
    dec1 = {"numberFormat": {"type": "NUMBER", "pattern": "0.0"}}

    bold = {"textFormat": {"bold": True}}

    formats = []
    for start_row, n_players in block_infos:
        pr = start_row + 2  # first player row (team name + header above)
        lr = start_row + 1 + n_players
        sr = lr + 2  # summary row

        # Bold team name
        formats.append({"range": f'W{start_row}', "format": bold})

        # Player + summary rows: decimal columns
        for col in ['Z', 'AC']:
            formats.append({"range": f'{col}{pr}:{col}{sr}', "format": dec2})
        formats.append({"range": f'AJ{pr}:AJ{sr}', "format": dec1})

        # Player + summary rows: percentage columns
        for col in ['AG', 'AK', 'AL', 'AP']:
            formats.append({"range": f'{col}{pr}:{col}{sr}', "format": pct})

        # Shooting table: col Z has percentages
        shoot_start = sr + 2
        shoot_end = shoot_start + 2 * n_players - 1
        formats.append({"range": f'Z{shoot_start}:Z{shoot_end}', "format": pct})

    ws.batch_format(formats)


def main():
    if len(sys.argv) < 2:
        print("Usage: update_sheet.py <pdf_directory_or_files...>", file=sys.stderr)
        sys.exit(1)

    print("Running main.py to extract data...", file=sys.stderr)
    raw_rows = get_csv_data(sys.argv[1:])
    print(f"Got {len(raw_rows)} player-game rows", file=sys.stderr)

    rosters = build_team_rosters(raw_rows)
    print(f"Teams: {', '.join(rosters.keys())}", file=sys.stderr)

    print("Connecting to Google Sheets...", file=sys.stderr)
    gc = gspread.service_account(filename=CREDENTIALS_FILE)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(SHEET_NAME)

    # Clear values and formatting
    ws.clear()
    clear_formatting(sh, ws)

    # Write raw data to A1:U{n}
    print(f"Writing {len(raw_rows)} rows of raw data to A-U...", file=sys.stderr)
    ws.update(range_name=f'A1:U{len(raw_rows)}', values=raw_rows, raw=False)

    # Build and write analysis blocks for each team
    current_row = 1  # 1-indexed; first block header goes here
    all_analysis_rows = []
    block_infos = []
    for team, players in rosters.items():
        print(f"  {team}: {len(players)} players (row {current_row})", file=sys.stderr)
        block_rows, block_height = build_analysis_block(
            team, players, current_row, len(raw_rows),
        )
        block_infos.append((current_row, len(players)))
        # Pad to full block height
        while len(block_rows) < block_height:
            block_rows.append([''] * 20)
        all_analysis_rows.extend(block_rows)
        current_row += block_height

    # Write all analysis at once (columns W-AP)
    end_row = len(all_analysis_rows)
    print(f"Writing analysis to W1:AP{end_row}...", file=sys.stderr)
    ws.update(
        range_name=f'W1:AP{end_row}',
        values=all_analysis_rows,
        raw=False,
    )

    # Apply number formatting
    print("Applying formatting...", file=sys.stderr)
    format_analysis(ws, block_infos, end_row)

    print("Done.", file=sys.stderr)


if __name__ == '__main__':
    main()
