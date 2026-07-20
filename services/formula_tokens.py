"""
Token vocabulary and built-in definitions for the ExternalImport Formula Builder.

A formula is a list of tokens, not a free-text string — this is what lets the
builder UI work like Strategy Builder's click-to-insert formula editor instead
of an editable spreadsheet cell. Token shapes:

  {"type": "field", "value": "HIGH"}
      A raw uploaded field (see RAW_FIELDS) or a reference to another
      formula's code (e.g. "PWC", "DR6") — displayed as "[HIGH]" / "[PWC]".
  {"type": "num", "value": "1.1"}
      A numeric constant.
  {"type": "op", "value": "+"}  /  {"type": "paren", "value": "("}
      Arithmetic operator or parenthesis.
  {"type": "func", "value": "MAX_OF(", "field": "HIGH", "window": "CURRENT_MONTH"}
      A window aggregate: MAX_OF/MIN_OF/AVG_OF/SUM_OF a field over a named
      window (see WINDOWS) — displayed as "MAX_OF([HIGH], CURRENT_MONTH)".
  {"type": "func", "value": "AT(", "field": "CLOSE", "timepoint": "LAST_TRADING_DAY_OF_PREVIOUS_WEEK"}
      A point lookup: a field's value at a named timepoint (see TIMEPOINTS) —
      displayed as "AT([CLOSE], LAST_TRADING_DAY_OF_PREVIOUS_WEEK)".
  {"type": "func", "value": "ABS("}
      A plain wrapping function — the user must add its argument and a
      closing ")" token, same as Strategy Builder's MIN(/MAX(/ROUND(.

This vocabulary intentionally mirrors services.formula_engine.py's actual
implementation (window/timepoint names line up 1:1) so a formula shown here
is a faithful description of what the engine computes — but the engine itself
is NOT driven by these tokens; it's the separately hand-written, tested
per-code functions in formula_engine.py. Editing a formula's tokens here is
documentation/customization only and does not change what gets calculated.
"""

RAW_FIELDS = [
    "OPEN", "HIGH", "LOW", "CLOSE",
    "AVGRATE", "QUANTITY", "DIFFPCNT",
]

WINDOWS = [
    "CURRENT_WEEK", "CURRENT_MONTH", "PREVIOUS_WEEK", "PREVIOUS_MONTH",
    "EXPIRY_WEEK", "ROLLOVER_WEEK",
    "LAST_5_TRADING_DAYS", "LAST_3_WEEKS", "LAST_2_MONTHS",
]

TIMEPOINTS = [
    "PREVIOUS_TRADING_DAY",
    "FIRST_TRADING_DAY_OF_WEEK", "FIRST_TRADING_DAY_OF_MONTH",
    "LAST_TRADING_DAY_OF_PREVIOUS_WEEK", "LAST_TRADING_DAY_OF_PREVIOUS_MONTH",
]

AGG_FUNCS = ["MAX_OF(", "MIN_OF(", "AVG_OF(", "SUM_OF("]
POINT_FUNC = "AT("
WRAP_FUNCS = ["ABS("]
OPERATORS = ["+", "-", "*", "/"]


def tokens_to_display(tokens: list) -> str:
    parts = []
    for tok in tokens:
        kind = tok.get("type")
        value = tok.get("value", "")
        if kind == "field":
            parts.append(f"[{value}]")
        elif kind == "num" or kind == "paren":
            parts.append(value)
        elif kind == "op":
            parts.append(f" {value} ")
        elif kind == "func":
            fname = value.rstrip("(")
            if "window" in tok:
                parts.append(f"{fname}([{tok.get('field', '')}], {tok.get('window', '')})")
            elif "timepoint" in tok:
                parts.append(f"{fname}([{tok.get('field', '')}], {tok.get('timepoint', '')})")
            else:
                parts.append(f"{fname}(")
        else:
            parts.append(str(value))
    return "".join(parts).strip() or "\u2014"


# code -> {"name", "tokens", "description", "frequency"} for the 56 built-in
# formulas. User-confirmed 2026-07-18: this is the complete/final set of
# codes; blank frequencies filled in (PWATP/WEEK % CHANGE=WEEKLY,
# CMATP/MONTH % CHANGE/PMATP=MONTHLY); weeks run Monday..Sunday.
BUILTIN_FORMULAS = {
    'CMH': {'name': 'CMH IS CURRENT MONTH HIGH & WILL BE RESET TO ZERO ON THE FIRST TRADING DAY OF THE MONTH', 'tokens': [{'type': 'func', 'value': 'MAX_OF(', 'field': 'HIGH', 'window': 'CURRENT_MONTH'}], 'description': '', 'frequency': 'DAILY'},
    'CML': {'name': 'CML IS CURRENT MONTH LOW & WILL BE RESET TO ZERO ON THE FIRST TRADING DAY OF THE MONTH', 'tokens': [{'type': 'func', 'value': 'MIN_OF(', 'field': 'LOW', 'window': 'CURRENT_MONTH'}], 'description': '', 'frequency': 'DAILY'},
    'CWH': {'name': 'CWH IS CURRENT WEEK HIGH & WILL BE RESET TO ZERO ON THE FIRST TRADING DAY OF THE WEEK', 'tokens': [{'type': 'func', 'value': 'MAX_OF(', 'field': 'HIGH', 'window': 'CURRENT_WEEK'}], 'description': '', 'frequency': 'DAILY'},
    'CWL': {'name': 'CWL IS CURRENT WEEK LOW & WILL BE RESET TO ZERO ON THE FIRST TRADING DAY OF THE WEEK', 'tokens': [{'type': 'func', 'value': 'MIN_OF(', 'field': 'LOW', 'window': 'CURRENT_WEEK'}], 'description': '', 'frequency': 'DAILY'},
    'EWH': {'name': 'EWH IS EXPIRY WEEK HIGH', 'tokens': [{'type': 'func', 'value': 'MAX_OF(', 'field': 'HIGH', 'window': 'EXPIRY_WEEK'}], 'description': 'EWH IS THE MAXIMUM HIGH CALCULATED AT THE EXPIRY WEEK(WEEK WHERE THE LAST TUESDAY  OF THE MONTH FALLS ON)', 'frequency': 'MONTHLY'},
    'EWL': {'name': 'EWL IS EXPIRY WEEK LOW', 'tokens': [{'type': 'func', 'value': 'MIN_OF(', 'field': 'LOW', 'window': 'EXPIRY_WEEK'}], 'description': 'EWL IS THE MINIMUM LOW CALCULATED AT THE EXPIRY WEEK(WEEK WHERE THE LAST TUESDAY  OF THE MONTH FALLS ON)', 'frequency': 'MONTHLY'},
    'RWH': {'name': 'RWH IS ROLLOVER WEEK HIGH', 'tokens': [{'type': 'func', 'value': 'MAX_OF(', 'field': 'HIGH', 'window': 'ROLLOVER_WEEK'}], 'description': 'RWH IS THE MAXIMUM HIGH CALCULATED AFTER EXPIRY WEEK  OF THE MONTH', 'frequency': 'MONTHLY'},
    'RWL': {'name': 'RWL IS ROLLOVER WEEK LOW', 'tokens': [{'type': 'func', 'value': 'MIN_OF(', 'field': 'LOW', 'window': 'ROLLOVER_WEEK'}], 'description': 'RWL IS THE MINIMUM LOW CALCULATED AFTER EXPIRY WEEK  OF THE MONTH', 'frequency': 'MONTHLY'},
    'CWO': {'name': 'CWO IS THE OPEN OF CURRENT RUNNING CALENDAR WEEK', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'OPEN', 'timepoint': 'FIRST_TRADING_DAY_OF_WEEK'}], 'description': 'WOPEN IS THE OPEN PRICE TAKEN FROM  THE FIRST TRADING DAY OF THE CURRENT CALENDAR WEEK', 'frequency': 'WEEKLY'},
    'FH': {'name': 'FRIDAY HIGH', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'HIGH', 'timepoint': 'LAST_TRADING_DAY_OF_PREVIOUS_WEEK'}], 'description': 'FRIDAY HIGH IS THE HIGH PRICE TAKEN ON THE LAST WORKING DAY OF THE WEEK. (IF FRIDAY HAS NSE HOLIDAY ,THEN THURSDAY HIGH WILL BE FRIDAY HIGH)', 'frequency': 'WEEKLY'},
    'FL': {'name': 'FRIDAY LOW', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'LOW', 'timepoint': 'LAST_TRADING_DAY_OF_PREVIOUS_WEEK'}], 'description': 'FRIDAY LOW IS THE LOW PRICE TAKEN ON THE LAST WORKING DAY OF THE WEEK. (IF FRIDAY HAS NSE HOLIDAY ,THEN THURSDAY LOW WILL BE FRIDAY LOW)', 'frequency': 'WEEKLY'},
    'DT': {'name': 'DAY TOP', 'tokens': [{'type': 'func', 'value': 'MAX_OF(', 'field': 'CLOSE', 'window': 'LAST_5_TRADING_DAYS'}], 'description': 'DAY TOP IS THE MAXIMUM CLOSE OF LAST 5 DAYS CLOSE', 'frequency': 'DAILY'},
    'DB': {'name': 'DAY BOTTOM', 'tokens': [{'type': 'func', 'value': 'MIN_OF(', 'field': 'CLOSE', 'window': 'LAST_5_TRADING_DAYS'}], 'description': 'DAY BOTTOM  IS THE MINIMUM CLOSE OF LAST 5 DAYS CLOSE', 'frequency': 'DAILY'},
    'PMH': {'name': 'PREVIOUS MONTH HIGH', 'tokens': [{'type': 'func', 'value': 'MAX_OF(', 'field': 'HIGH', 'window': 'PREVIOUS_MONTH'}], 'description': 'PREVIOUS MONTH HIGH IS THE HIGHEST HIGH OF WORKING DAYS OF PREVIOUS CALENDAR MONTH', 'frequency': 'MONTHLY'},
    'PML': {'name': 'PREVIOUS MONTH LOW', 'tokens': [{'type': 'func', 'value': 'MIN_OF(', 'field': 'LOW', 'window': 'PREVIOUS_MONTH'}], 'description': 'PREVIOUS MONTH LOW IS THE LOWEST LOW OF WORKING DAYS OF PREVIOUS CALENDAR MONTH', 'frequency': 'MONTHLY'},
    'PMC': {'name': 'PREVIOUS MONTH CLOSE', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'CLOSE', 'timepoint': 'LAST_TRADING_DAY_OF_PREVIOUS_MONTH'}], 'description': 'CLOSE PRICE TAKEN ON THE LAST WORKING DAY OF PREVIOUS CALENDAR MONTH', 'frequency': 'MONTHLY'},
    'PWH': {'name': 'PREVIOUS WEEK HIGH', 'tokens': [{'type': 'func', 'value': 'MAX_OF(', 'field': 'HIGH', 'window': 'PREVIOUS_WEEK'}], 'description': 'PREVIOUS WEEK HIGH IS THE HIGHEST HIGH OF WORKING DAYS OF PREVIOUS CALENDAR WEEK', 'frequency': 'WEEKLY'},
    'PWL': {'name': 'PREVIOUS WEEK LOW', 'tokens': [{'type': 'func', 'value': 'MIN_OF(', 'field': 'LOW', 'window': 'PREVIOUS_WEEK'}], 'description': 'PREVIOUS WEEK LOW IS THE LOWEST LOW OF WORKING DAYS OF PREVIOUS CALENDAR WEEK', 'frequency': 'WEEKLY'},
    'PWC': {'name': 'PREVIOUS WEEK CLOSE', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'CLOSE', 'timepoint': 'LAST_TRADING_DAY_OF_PREVIOUS_WEEK'}], 'description': 'CLOSE PRICE TAKEN ON THE LAST WORKING DAY OF PREVIOUS CALENDAR WEEK', 'frequency': 'WEEKLY'},
    'WT': {'name': 'WEEK TOP', 'tokens': [{'type': 'func', 'value': 'MAX_OF(', 'field': 'CLOSE', 'window': 'LAST_3_WEEKS'}], 'description': 'WEEK TOP IS THE MAXIMUM CLOSE OF PREVIOUS 3 WEEKS', 'frequency': 'WEEKLY'},
    'WB': {'name': 'WEEK BOTTOM', 'tokens': [{'type': 'func', 'value': 'MIN_OF(', 'field': 'CLOSE', 'window': 'LAST_3_WEEKS'}], 'description': 'WEEK BOTTOM IS THE MINIMUM CLOSE OF PREVIOUS 3 WEEKS', 'frequency': 'WEEKLY'},
    'MT': {'name': 'MONTH TOP', 'tokens': [{'type': 'func', 'value': 'MAX_OF(', 'field': 'CLOSE', 'window': 'LAST_2_MONTHS'}], 'description': 'MONTH TOP IS THE MAXIMUM CLOSE OF PREVIOUS 2 MONTHS', 'frequency': 'MONTHLY'},
    'MB': {'name': 'MONTH BOTTOM', 'tokens': [{'type': 'func', 'value': 'MIN_OF(', 'field': 'CLOSE', 'window': 'LAST_2_MONTHS'}], 'description': 'MONTH BOTTOM IS THE MINIMUM CLOSE OF PREVIOUS 2 MONTHS', 'frequency': 'MONTHLY'},
    'CMO': {'name': 'CMO IS THE OPEN OF CURRENT RUNNING CALENDAR MONTH', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'OPEN', 'timepoint': 'FIRST_TRADING_DAY_OF_MONTH'}], 'description': 'MOPEN IS THE OPEN PRICE TAKEN FROM  THE FIRST TRADING DAY OF THE CURRENT CALENDAR MONTH', 'frequency': 'MONTHLY'},
    'DR3': {'name': 'DAILY R3', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'CLOSE', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '+'}, {'type': 'paren', 'value': '('}, {'type': 'func', 'value': 'AT(', 'field': 'HIGH', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '-'}, {'type': 'func', 'value': 'AT(', 'field': 'LOW', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '4'}], 'description': 'DAILY R3 IS CALCULATED EVERY DAY USING PREVIOUS DAY CLOSE,PREVIOUS DAY HIGH AND PREVIOUS DAY LOW', 'frequency': 'DAILY'},
    'DR4': {'name': 'DAILY R4', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'CLOSE', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '+'}, {'type': 'paren', 'value': '('}, {'type': 'func', 'value': 'AT(', 'field': 'HIGH', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '-'}, {'type': 'func', 'value': 'AT(', 'field': 'LOW', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '2'}], 'description': 'DAILY R4 IS CALCULATED EVERY DAY USING PREVIOUS DAY CLOSE,PREVIOUS DAY HIGH AND PREVIOUS DAY LOW', 'frequency': 'DAILY'},
    'DR6': {'name': 'DAILY R6', 'tokens': [{'type': 'paren', 'value': '('}, {'type': 'func', 'value': 'AT(', 'field': 'HIGH', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '/'}, {'type': 'func', 'value': 'AT(', 'field': 'LOW', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'func', 'value': 'AT(', 'field': 'CLOSE', 'timepoint': 'PREVIOUS_TRADING_DAY'}], 'description': 'DAILY R6 IS CALCULATED EVERY DAY USING PREVIOUS DAY CLOSE,PREVIOUS DAY HIGH AND PREVIOUS DAY LOW', 'frequency': 'DAILY'},
    'DS3': {'name': 'DAILY S3', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'CLOSE', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '-'}, {'type': 'paren', 'value': '('}, {'type': 'func', 'value': 'AT(', 'field': 'HIGH', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '-'}, {'type': 'func', 'value': 'AT(', 'field': 'LOW', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '4'}], 'description': 'DAILY S3 IS CALCULATED EVERY DAY USING PREVIOUS DAY CLOSE,PREVIOUS DAY HIGH AND PREVIOUS DAY LOW', 'frequency': 'DAILY'},
    'DS4': {'name': 'DAILY S4', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'CLOSE', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '-'}, {'type': 'paren', 'value': '('}, {'type': 'func', 'value': 'AT(', 'field': 'HIGH', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '-'}, {'type': 'func', 'value': 'AT(', 'field': 'LOW', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '2'}], 'description': 'DAILY S6 IS CALCULATED EVERY DAY USING PREVIOUS DAY CLOSE,PREVIOUS DAY HIGH AND PREVIOUS DAY LOW', 'frequency': 'DAILY'},
    'DS6': {'name': 'DAILY S6', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'CLOSE', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '-'}, {'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'DR6'}, {'type': 'op', 'value': '-'}, {'type': 'func', 'value': 'AT(', 'field': 'CLOSE', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'paren', 'value': ')'}], 'description': 'DAILY S4 IS CALCULATED EVERY DAY USING PREVIOUS DAY CLOSE,PREVIOUS DAY HIGH AND PREVIOUS DAY LOW', 'frequency': 'DAILY'},
    'WR3': {'name': 'WEEKLY R3', 'tokens': [{'type': 'field', 'value': 'PWC'}, {'type': 'op', 'value': '+'}, {'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PWH'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PWL'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '4'}], 'description': 'WEEKLY R3 IS CALCULATED EVERY WEEK USING PREVIOUS WEEK CLOSE,PREVIOUS WEEK HIGH AND PREVIOUS WEEK LOW', 'frequency': 'WEEKLY'},
    'WR4': {'name': 'WEEKLY R4', 'tokens': [{'type': 'field', 'value': 'PWC'}, {'type': 'op', 'value': '+'}, {'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PWH'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PWL'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '2'}], 'description': 'WEEKLY R4 IS CALCULATED EVERY WEEK USING PREVIOUS WEEK CLOSE,PREVIOUS WEEK HIGH AND PREVIOUS WEEK LOW', 'frequency': 'WEEKLY'},
    'WR6': {'name': 'WEEKLY R6', 'tokens': [{'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PWH'}, {'type': 'op', 'value': '/'}, {'type': 'field', 'value': 'PWL'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'field', 'value': 'PWC'}], 'description': 'WEEKLY R6 IS CALCULATED EVERY WEEK USING PREVIOUS WEEK CLOSE,PREVIOUS WEEK HIGH AND PREVIOUS WEEK LOW', 'frequency': 'WEEKLY'},
    'WS3': {'name': 'WEEKLY S3', 'tokens': [{'type': 'field', 'value': 'PWC'}, {'type': 'op', 'value': '-'}, {'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PWH'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PWL'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '4'}], 'description': 'WEEKLY S3 IS CALCULATED EVERY WEEK USING PREVIOUS WEEK CLOSE,PREVIOUS WEEK HIGH AND PREVIOUS WEEK LOW', 'frequency': 'WEEKLY'},
    'WS4': {'name': 'WEEKLY S4', 'tokens': [{'type': 'field', 'value': 'PWC'}, {'type': 'op', 'value': '-'}, {'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PWH'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PWL'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '2'}], 'description': 'WEEKLY S4 IS CALCULATED EVERY WEEK USING PREVIOUS WEEK CLOSE,PREVIOUS WEEK HIGH AND PREVIOUS WEEK LOW', 'frequency': 'WEEKLY'},
    'WS6': {'name': 'WEEKLY S6', 'tokens': [{'type': 'field', 'value': 'PWC'}, {'type': 'op', 'value': '-'}, {'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'WR6'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PWC'}, {'type': 'paren', 'value': ')'}], 'description': 'WEEKLY S6 IS CALCULATED EVERY WEEK USING PREVIOUS WEEK CLOSE,PREVIOUS WEEK HIGH AND PREVIOUS WEEK LOW', 'frequency': 'WEEKLY'},
    'MR3': {'name': 'MONTHLY R3', 'tokens': [{'type': 'field', 'value': 'PMC'}, {'type': 'op', 'value': '+'}, {'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PMH'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PML'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '4'}], 'description': 'MONTHLY R3 IS CALCULATED EVERY MONTH USING PREVIOUS MONTH CLOSE,PREVIOUS MONTH HIGH AND PREVIOUS MONTH LOW', 'frequency': 'MONTHLY'},
    'MR4': {'name': 'MONTHLY R4', 'tokens': [{'type': 'field', 'value': 'PMC'}, {'type': 'op', 'value': '+'}, {'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PMH'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PML'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '2'}], 'description': 'MONTHLY R4 IS CALCULATED EVERY MONTH USING PREVIOUS MONTH CLOSE,PREVIOUS MONTH HIGH AND PREVIOUS MONTH LOW', 'frequency': 'MONTHLY'},
    'MR6': {'name': 'MONTHLY R6', 'tokens': [{'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PMH'}, {'type': 'op', 'value': '/'}, {'type': 'field', 'value': 'PML'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'field', 'value': 'PMC'}], 'description': 'MONTHLY R6 IS CALCULATED EVERY MONTH USING PREVIOUS MONTH CLOSE,PREVIOUS MONTH HIGH AND PREVIOUS MONTH LOW', 'frequency': 'MONTHLY'},
    'MS3': {'name': 'MONTHLY S3', 'tokens': [{'type': 'field', 'value': 'PMC'}, {'type': 'op', 'value': '-'}, {'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PMH'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PML'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '4'}], 'description': 'MONTHLY S3 IS CALCULATED EVERY MONTH USING PREVIOUS MONTH CLOSE,PREVIOUS MONTH HIGH AND PREVIOUS MONTH LOW', 'frequency': 'MONTHLY'},
    'MS4': {'name': 'MONTHLY S4', 'tokens': [{'type': 'field', 'value': 'PMC'}, {'type': 'op', 'value': '-'}, {'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PMH'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PML'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '1.1'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '2'}], 'description': 'MONTHLY S4 IS CALCULATED EVERY MONTH USING PREVIOUS MONTH CLOSE,PREVIOUS MONTH HIGH AND PREVIOUS MONTH LOW', 'frequency': 'MONTHLY'},
    'MS6': {'name': 'MONTHLY S6', 'tokens': [{'type': 'field', 'value': 'PMC'}, {'type': 'op', 'value': '-'}, {'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'MR6'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PMC'}, {'type': 'paren', 'value': ')'}], 'description': 'MONTHLY S6 IS CALCULATED EVERY MONTH USING PREVIOUS MONTH CLOSE,PREVIOUS MONTH HIGH AND PREVIOUS MONTH LOW', 'frequency': 'MONTHLY'},
    'PATP': {'name': 'PREVIOUS DAY ATP', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'AVGRATE', 'timepoint': 'PREVIOUS_TRADING_DAY'}], 'description': "CURRENT DAY'S ATP WILL BE STORED AND DISPLAYED AS PREVIOUS DAY'S ATP THE NEXT DAY", 'frequency': 'DAILY'},
    'CWATP': {'name': 'CURRENT WEEK ATP', 'tokens': [{'type': 'func', 'value': 'AVG_OF(', 'field': 'AVGRATE', 'window': 'CURRENT_WEEK'}], 'description': '', 'frequency': 'DAILY'},
    'PWATP': {'name': 'PREVIOUS WEEK ATP', 'tokens': [{'type': 'func', 'value': 'AVG_OF(', 'field': 'AVGRATE', 'window': 'PREVIOUS_WEEK'}], 'description': 'CURRENT WEEK ATP CALCULATED ON THE LAST WORKING DAY OF A CALENDAR WEEK WILL BE STORED AND DISPLAYED AS PREVIOUS WEEK ATP THE NEXT WEEK', 'frequency': 'WEEKLY'},
    'CMATP': {'name': 'CURRENT MONTH ATP', 'tokens': [{'type': 'func', 'value': 'AVG_OF(', 'field': 'AVGRATE', 'window': 'CURRENT_MONTH'}], 'description': '', 'frequency': 'MONTHLY'},
    'WEEK % CHANGE': {'name': 'WEEKLY PERCENTAGE CHANGE', 'tokens': [{'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'CLOSE'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PWC'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '/'}, {'type': 'field', 'value': 'PWC'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '100'}], 'description': '', 'frequency': 'WEEKLY'},
    'MONTH % CHANGE': {'name': 'MONTHLY PERCENTAGE CHANGE', 'tokens': [{'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'CLOSE'}, {'type': 'op', 'value': '-'}, {'type': 'field', 'value': 'PMC'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '/'}, {'type': 'field', 'value': 'PMC'}, {'type': 'op', 'value': '*'}, {'type': 'num', 'value': '100'}], 'description': '', 'frequency': 'MONTHLY'},
    'PMATP': {'name': 'PREVIOUS MONTH ATP', 'tokens': [{'type': 'func', 'value': 'AVG_OF(', 'field': 'AVGRATE', 'window': 'PREVIOUS_MONTH'}], 'description': 'CURRENT MONTH ATP CALCULATED ON THE LAST WORKING DAY OF A CALENDAR MONTH WILL BE STORED AND DISPLAYED AS PREVIOUS MONTH ATP THE NEXT MONTH', 'frequency': 'MONTHLY'},
    'DAY TO': {'name': 'DAILY TURNOVER', 'tokens': [{'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'QUANTITY'}, {'type': 'op', 'value': '*'}, {'type': 'field', 'value': 'AVGRATE'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '10000000'}, {'type': 'op', 'value': '*'}, {'type': 'paren', 'value': '('}, {'type': 'func', 'value': 'ABS('}, {'type': 'field', 'value': 'DIFFPCNT'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '100'}, {'type': 'paren', 'value': ')'}], 'description': 'DAILY TURNOVER IS CALCULATED USING THE QUANTITY,AVGRATE AND DIFFPCNT', 'frequency': 'DAILY'},
    'PDTO': {'name': 'PREVIOUS DAY TURNOVER', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'DAY TO', 'timepoint': 'PREVIOUS_TRADING_DAY'}], 'description': "CURRENT DAY'S DAY TO WILL BE STORED AND DISPLAYED AS PREVIOUS DAY TURNOVER THE NEXT DAY", 'frequency': 'DAILY'},
    'CWTO': {'name': 'CURRENT WEEK TURNOVER', 'tokens': [{'type': 'paren', 'value': '('}, {'type': 'func', 'value': 'SUM_OF(', 'field': 'QUANTITY', 'window': 'CURRENT_WEEK'}, {'type': 'op', 'value': '*'}, {'type': 'field', 'value': 'CWATP'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '10000000'}, {'type': 'op', 'value': '*'}, {'type': 'paren', 'value': '('}, {'type': 'func', 'value': 'ABS('}, {'type': 'field', 'value': 'WEEK % CHANGE'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '100'}, {'type': 'paren', 'value': ')'}], 'description': 'CURRENT WEEK TURNOVER IS CALCULATED USING THE SUM OF QUANTITY FROM BOTH STORED PREVIOUS DAY QUANTITIES OF THE CURRENT CALENDAR WEEK AND CURRENT DAY QUANTITY OF THE SAME WEEK ,CALCULATED CWATP AND CALCULATED WEEK %  CHANGE', 'frequency': 'DAILY'},
    'PWTO': {'name': 'PREVIOUS WEEK TURNOVER', 'tokens': [{'type': 'func', 'value': 'AT(', 'field': 'CWTO', 'timepoint': 'LAST_TRADING_DAY_OF_PREVIOUS_WEEK'}], 'description': 'CURRENT WEEK TURNOVER CALCULATED ON THE LAST WORKING DAY OF A CALENDAR WEEK WILL BE STORED AND DISPLAYED AS PREVIOUS WEEK TURNOVER THE NEXT WEEK', 'frequency': 'WEEKLY'},
    'DAY PIVOT': {'name': 'DAY PIVOT', 'tokens': [{'type': 'paren', 'value': '('}, {'type': 'func', 'value': 'AT(', 'field': 'HIGH', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '+'}, {'type': 'func', 'value': 'AT(', 'field': 'LOW', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'op', 'value': '+'}, {'type': 'func', 'value': 'AT(', 'field': 'CLOSE', 'timepoint': 'PREVIOUS_TRADING_DAY'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '3'}], 'description': '', 'frequency': 'DAILY'},
    'WEEK PIVOT': {'name': 'WEEK PIVOT', 'tokens': [{'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PWH'}, {'type': 'op', 'value': '+'}, {'type': 'field', 'value': 'PWL'}, {'type': 'op', 'value': '+'}, {'type': 'field', 'value': 'PWC'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '3'}], 'description': '', 'frequency': 'WEEKLY'},
    'MONTH PIVOT': {'name': 'MONTH PIVOT', 'tokens': [{'type': 'paren', 'value': '('}, {'type': 'field', 'value': 'PMH'}, {'type': 'op', 'value': '+'}, {'type': 'field', 'value': 'PML'}, {'type': 'op', 'value': '+'}, {'type': 'field', 'value': 'PMC'}, {'type': 'paren', 'value': ')'}, {'type': 'op', 'value': '/'}, {'type': 'num', 'value': '3'}], 'description': '', 'frequency': 'MONTHLY'},
}

BUILTIN_CODES = list(BUILTIN_FORMULAS.keys())
