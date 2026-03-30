#!/usr/bin/env python3
"""Update Google Sheet with scouting data from PDFs.

Usage: update_sheet.py --sheet-name "O35 2026" <pdf_directory_or_files...>

Writes raw per-game player stats to columns A-U of the named sheet,
then generates per-team analysis blocks in columns W-AP.
"""

import argparse
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import gspread

from main import expand_pdf_inputs, parse_date_from_filename

SPREADSHEET_ID = '1eQjM2vG4t6aASjxoRgW_83EVyk1xBu85nrLxHsRcg0U'
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


def parse_matchups(pdf_args):
    """Parse team matchups from PDF filenames.

    Filename pattern: SO35_Team1_Team2_date.pdf
    Returns dict mapping (date_str, team) -> opponent.
    """
    matchups = {}
    for pdf_path in expand_pdf_inputs(pdf_args):
        parts = Path(pdf_path).stem.split('_')
        team1, team2 = parts[1], parts[2]
        date_str = parse_date_from_filename(pdf_path)
        matchups[(date_str, team1)] = team2
        matchups[(date_str, team2)] = team1
    return matchups


def compute_opponent_stats(raw_rows, matchups):
    """Compute per-team-per-game stats and opponent stats.

    Raw CSV column indices (after team, player, date):
        5=OR (F), 6=DR (G), 8=TO (I), 9=Steals (J),
        13=FGM (N), 14=FGA (O), 15=3PM (P), 16=3PA (Q),
        17=FTM (R), 18=FTA (S)

    Returns (header, rows) where each row is:
        [team, date, team_or, opp_dr, opp_fgm, opp_fga, opp_3pm, opp_3pa]
    """
    # Stat indices in the CSV
    STATS = {'or': 5, 'dr': 6, 'fgm': 13, 'fga': 14, 'tpm': 15, 'tpa': 16}

    # Accumulate per-team-per-game
    totals = defaultdict(lambda: defaultdict(int))
    for row in raw_rows:
        key = (row[0], row[2])  # (team, date)
        for stat, idx in STATS.items():
            totals[key][stat] += int(float(row[idx]))

    header = ['Team', 'Date', 'OR', 'Opp DR',
              'Opp FGM', 'Opp FGA', 'Opp 3PM', 'Opp 3PA',
              'DR', 'Opp OR']

    rows = []
    for (team, date) in sorted(totals):
        t = totals[(team, date)]
        opponent = matchups.get((date, team))
        opp = totals.get((opponent, date), defaultdict(int)) if opponent else defaultdict(int)
        rows.append([
            team, date,
            str(t['or']), str(opp['dr']),
            str(opp['fgm']), str(opp['fga']),
            str(opp['tpm']), str(opp['tpa']),
            str(t['dr']), str(opp['or']),
        ])

    return header, rows


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


def build_efg_table(teams, num_raw_rows):
    """Build a team-level EFG comparison table.

    EFG = 2PT% + 1.5 * 3PT%

    Returns (rows, height) where rows is a list of 20-element lists
    for columns W-AP, and height is the total rows including padding.
    """
    R = num_raw_rows

    def pad(row):
        return row + [''] * (20 - len(row))

    rows = []

    # Title row
    rows.append(pad(['Four Factors']))

    # Header row
    rows.append(pad(['', "'2PT%", "'3PT%", 'EFG', 'Def EFG', 'Poss/G',
                      'TO%', 'FTA/FGA', 'FT Pts%', 'OR%', 'DR%']))

    # One row per team, sorted alphabetically
    for i, team in enumerate(teams):
        r = len(rows) + 1  # 1-indexed row this will land on
        # Helper aliases for readability:
        #   FGM=col N, FGA=col O, 3PM=col P, 3PA=col Q
        #   2PM = FGM - 3PM, 2PA = FGA - 3PA
        fgm = f'SUMIF($A$1:$A${R},W{r},$N$1:$N${R})'
        tpm = f'SUMIF($A$1:$A${R},W{r},$P$1:$P${R})'
        fga = f'SUMIF($A$1:$A${R},W{r},$O$1:$O${R})'
        tpa = f'SUMIF($A$1:$A${R},W{r},$Q$1:$Q${R})'
        # Possessions = FGA + 0.44*FTA + TO - OR
        # Raw data cols: O=FGA, S=FTA, I=TO, F=OR
        fta = f'SUMIF($A$1:$A${R},W{r},$S$1:$S${R})'
        to = f'SUMIF($A$1:$A${R},W{r},$I$1:$I${R})'
        oreb = f'SUMIF($A$1:$A${R},W{r},$F$1:$F${R})'
        games = f'COUNTA(UNIQUE(FILTER($C$1:$C${R},$A$1:$A${R}=W{r})))'
        rows.append(pad([
            team,
            # X: 2PT%
            f'=IFERROR(({fgm}-{tpm})/({fga}-{tpa}),0)',
            # Y: 3PT%
            f'=IFERROR({tpm}/{tpa},0)',
            # Z: EFG
            f'=IFERROR(({fgm}+0.5*{tpm})/{fga},0)',
            # AA: Def EFG = (opp FGM + 0.5*opp 3PM) / opp FGA
            f'=IFERROR((SUMIF($AR:$AR,W{r},$AV:$AV)+0.5*SUMIF($AR:$AR,W{r},$AX:$AX))'
            f'/SUMIF($AR:$AR,W{r},$AW:$AW),0)',
            # AB: Poss/G
            f'=IFERROR(({fga}+0.44*{fta}+{to}-{oreb})/{games},0)',
            # AC: TO%
            f'=IFERROR({to}/({fga}+0.44*{fta}+{to}-{oreb}),0)',
            # AD: FTA/FGA
            f'=IFERROR({fta}/{fga},0)',
            # AE: FT Pts%
            f'=IFERROR(SUMIF($A$1:$A${R},W{r},$R$1:$R${R})'
            f'/SUMIF($A$1:$A${R},W{r},$D$1:$D${R}),0)',
            # AF: OR%
            f'=IFERROR(SUMIF($AR:$AR,W{r},$AT:$AT)'
            f'/(SUMIF($AR:$AR,W{r},$AT:$AT)+SUMIF($AR:$AR,W{r},$AU:$AU)),0)',
            # AG: DR% = team DR / (team DR + opp OR)
            f'=IFERROR(SUMIF($AR:$AR,W{r},$AZ:$AZ)'
            f'/(SUMIF($AR:$AR,W{r},$AZ:$AZ)+SUMIF($AR:$AR,W{r},$BA:$BA)),0)',
        ]))

    # League average row
    first_team_row = 3
    last_team_row = 2 + len(teams)
    rows.append(pad([
        'League Avg',
        *[f'=AVERAGE({col}{first_team_row}:{col}{last_team_row})'
          for col in ['X', 'Y', 'Z', 'AA', 'AB', 'AC', 'AD', 'AE', 'AF', 'AG']],
    ]))

    # Blank padding row
    rows.append([''] * 20)

    # height: 1 (title) + 1 (header) + len(teams) + 1 (avg) + 1 (blank)
    return rows, len(teams) + 4


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

    # Summary row (immediately after last player)
    sr = lr + 1
    summary = [''] * 20
    summary[1] = f'=MAX(X{pr}:X{lr})'                                # X: Games (max)
    summary[2] = f'=SUM(Y{pr}:Y{lr})'                                # Y: Points total
    summary[3] = f'=IFERROR(Y{sr}/X{sr},0)'                          # Z: PPG (team)
    summary[4] = f'=SUM(AA{pr}:AA{lr})'                              # AA: OR total
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

    # Shooting table header + ARRAYFORMULA (spills 2*N rows)
    shoot_header = [''] * 20
    shoot_header[0] = 'Shot'
    shoot_header[1] = 'Attempts'
    shoot_header[2] = 'EFG'
    shoot_header[3] = 'Exp Pts/Shot'
    rows.append(shoot_header)

    shooting = [''] * 20
    # Pad player names to align "2 pointer" / "3 pointer" labels
    maxlen = f'MAX(LEN(W{pr}:W{lr}))'
    pad2 = f'W{pr}:W{lr}&REPT(" ",{maxlen}-LEN(W{pr}:W{lr}))&" 2 pointer"'
    pad3 = f'W{pr}:W{lr}&REPT(" ",{maxlen}-LEN(W{pr}:W{lr}))&" 3 pointer"'
    shooting[0] = (
        f'=ARRAYFORMULA(SORT({{'
        f'IF(LEN(W{pr}:W{lr}),{pad2},""),'
        f'AF{pr}:AF{lr},'
        f'AG{pr}:AG{lr},'
        f'2*AG{pr}:AG{lr};'
        f'IF(LEN(W{pr}:W{lr}),{pad3},""),'
        f'AI{pr}:AI{lr},'
        f'AL{pr}:AL{lr},'
        f'3*AK{pr}:AK{lr}'
        f'}},3,FALSE))'
    )
    rows.append(shooting)

    # Total block height: 1 (team name) + 1 (header) + N (players)
    #   + 1 (summary) + 1 (blank) + 1 (shoot header) + 1 (shooting formula)
    #   + (2*N - 1) (spill) + 2 (padding)
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


def format_analysis(ws, block_infos, efg_height, n_teams, end_row):
    """Apply number formatting to the EFG table and all analysis blocks.

    block_infos: list of (start_row, n_players) for each team.
    efg_height: number of rows the EFG table occupies.
    n_teams: number of teams in the EFG table.
    """
    pct = {"numberFormat": {"type": "PERCENT", "pattern": "0.00%"}}
    dec2 = {"numberFormat": {"type": "NUMBER", "pattern": "0.00"}}
    dec1 = {"numberFormat": {"type": "NUMBER", "pattern": "0.0"}}

    bold = {"textFormat": {"bold": True}}

    formats = []

    # EFG table: bold title, percentage formatting on data rows
    formats.append({"range": "W1", "format": bold})
    efg_first_data = 3  # row 3 is first team row (title=1, header=2)
    efg_last_data = 2 + n_teams
    efg_avg_row = efg_last_data + 1
    for col in ['X', 'Y', 'Z', 'AA', 'AC', 'AD', 'AE', 'AF', 'AG']:
        formats.append({
            "range": f'{col}{efg_first_data}:{col}{efg_avg_row}',
            "format": pct,
        })
    formats.append({
        "range": f'AB{efg_first_data}:AB{efg_avg_row}', "format": dec1,
    })
    formats.append({"range": f'W{efg_avg_row}:AG{efg_avg_row}', "format": bold})

    for start_row, n_players in block_infos:
        pr = start_row + 2  # first player row (team name + header above)
        lr = start_row + 1 + n_players
        sr = lr + 1  # summary row (immediately after last player)

        # Bold team name and summary row
        formats.append({"range": f'W{start_row}', "format": bold})
        formats.append({"range": f'W{sr}:AP{sr}', "format": bold})

        # Player + summary rows: decimal columns
        for col in ['Z', 'AC']:
            formats.append({"range": f'{col}{pr}:{col}{sr}', "format": dec2})
        formats.append({"range": f'AJ{pr}:AJ{sr}', "format": dec1})

        # Player + summary rows: percentage columns
        for col in ['AG', 'AK', 'AL', 'AP']:
            formats.append({"range": f'{col}{pr}:{col}{sr}', "format": pct})

        # Shooting table: header + data rows
        shoot_header_row = sr + 2
        shoot_start = shoot_header_row + 1  # first data row (after header)
        shoot_end = shoot_start + 2 * n_players - 1
        mono = {"textFormat": {"fontFamily": "Roboto Mono"}}
        formats.append({"range": f'W{shoot_header_row}:Z{shoot_header_row}', "format": bold})
        formats.append({"range": f'W{shoot_start}:W{shoot_end}', "format": mono})
        formats.append({"range": f'Y{shoot_start}:Y{shoot_end}', "format": pct})
        formats.append({"range": f'Z{shoot_start}:Z{shoot_end}', "format": dec2})

    ws.batch_format(formats)


def apply_conditional_formatting(sh, ws, end_row):
    """Highlight free throw columns based on attempt volume and accuracy.

    - Light yellow: player has attempted FTs but fewer than 5 total (small sample)
    - Light red: 5+ FTA and under 60% FT shooting
    """
    # Delete any existing conditional format rules on this sheet
    metadata = sh.fetch_sheet_metadata(
        params={"fields": "sheets(properties.sheetId,conditionalFormats)"},
    )
    n_rules = 0
    for sheet_data in metadata.get('sheets', []):
        if sheet_data['properties']['sheetId'] == ws.id:
            n_rules = len(sheet_data.get('conditionalFormats', []))
            break

    requests = []
    for i in range(n_rules - 1, -1, -1):
        requests.append({
            "deleteConditionalFormatRule": {
                "sheetId": ws.id,
                "index": i,
            }
        })

    # AN=39, AO=40, AP=41 (0-indexed column numbers)
    ft_range = {
        "sheetId": ws.id,
        "startRowIndex": 0,
        "endRowIndex": end_row,
        "startColumnIndex": 39,   # AN (FTM)
        "endColumnIndex": 42,     # through AP (FT%), exclusive
    }

    # Light yellow (#FFF2CC): 0 < FTA < 5
    requests.append({
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [ft_range],
                "booleanRule": {
                    "condition": {
                        "type": "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": "=AND($AO1>0,$AO1<5)"}],
                    },
                    "format": {
                        "backgroundColor": {
                            "red": 1.0, "green": 0.949, "blue": 0.8,
                        },
                    },
                },
            },
            "index": 0,
        }
    })

    # Light red (#F4CCCC): FTA >= 5 and FT% < 60%
    requests.append({
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [ft_range],
                "booleanRule": {
                    "condition": {
                        "type": "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": "=AND($AO1>=5,$AP1<0.6)"}],
                    },
                    "format": {
                        "backgroundColor": {
                            "red": 0.957, "green": 0.8, "blue": 0.8,
                        },
                    },
                },
            },
            "index": 1,
        }
    })

    sh.batch_update({"requests": requests})


def main():
    parser = argparse.ArgumentParser(
        description="Update a Google Sheet with scouting data from PDFs.",
    )
    parser.add_argument(
        '--sheet-name', required=True,
        help='Name of the worksheet tab to update (e.g. "O35 2026")',
    )
    parser.add_argument(
        'pdfs', nargs='+', metavar='PDF',
        help='PDF files or directories containing PDFs',
    )
    args = parser.parse_args()

    print("Running main.py to extract data...", file=sys.stderr)
    raw_rows = get_csv_data(args.pdfs)
    print(f"Got {len(raw_rows)} player-game rows", file=sys.stderr)

    rosters = build_team_rosters(raw_rows)
    print(f"Teams: {', '.join(rosters.keys())}", file=sys.stderr)

    print(f"Connecting to Google Sheets (sheet: {args.sheet_name!r})...",
          file=sys.stderr)
    gc = gspread.service_account(filename=CREDENTIALS_FILE)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(args.sheet_name)

    # Ensure sheet has enough columns for opponent stats (AR-AY = col 51)
    if ws.col_count < 53:
        ws.resize(cols=53)

    # Clear values and formatting
    ws.clear()
    clear_formatting(sh, ws)

    # Compute opponent stats from PDF filenames + raw data
    print("Computing opponent stats...", file=sys.stderr)
    matchups = parse_matchups(args.pdfs)
    opp_header, opp_rows = compute_opponent_stats(raw_rows, matchups)
    print(f"  {len(opp_rows)} team-game rows", file=sys.stderr)

    # Write raw data to A1:U{n}
    print(f"Writing {len(raw_rows)} rows of raw data to A-U...", file=sys.stderr)
    ws.update(range_name=f'A1:U{len(raw_rows)}', values=raw_rows, raw=False)

    # Write opponent stats helper table to AR-AY
    ws.update(
        range_name=f'AR1:BA1',
        values=[opp_header],
        raw=True,
    )
    ws.update(
        range_name=f'AR2:BA{len(opp_rows) + 1}',
        values=opp_rows,
        raw=False,
    )

    # Build EFG table, then per-team analysis blocks
    teams = list(rosters.keys())
    efg_rows, efg_height = build_efg_table(teams, len(raw_rows))
    all_analysis_rows = list(efg_rows)

    current_row = efg_height + 1  # 1-indexed; first team block starts here
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

    # Apply number formatting and conditional formatting
    print("Applying formatting...", file=sys.stderr)
    format_analysis(ws, block_infos, efg_height, len(teams), end_row)
    apply_conditional_formatting(sh, ws, end_row)

    print("Done.", file=sys.stderr)


if __name__ == '__main__':
    main()
