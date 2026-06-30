"""
Stateful live data reader + merger for the Live Master View.

Pulls the three broker sources and merges them exactly like
``master_generator.generate_master`` (same join keys and column layout), but
optimised for the live polling loop:

  * Sharekhan is the fast-moving source (live DDE prices) — re-read every tick.
  * ReliableSoftware and NiftyInvest change slowly — re-read only every
    ``slow_interval_s`` seconds and cached in between.
  * On Windows a cached-handle :class:`~services.com_reader.ExcelLiveReader`
    avoids re-acquiring the Excel COM handle on every tick.

This object is designed to run on a worker thread.  Call :meth:`start` once on
that thread (initialises COM), :meth:`read_merged` per tick, and :meth:`stop`
when finished.  It carries no Qt dependency so it is trivially testable.
"""

import time


class LiveDataReader:
    def __init__(self, sharekhan_path, reliable_path, nifty_path,
                 script_name_data, expiry_date=None,
                 use_com=False, slow_interval_s: float = 1.0,
                 clock=time.monotonic, external_path=None):
        self._sharekhan_path   = sharekhan_path
        self._reliable_path    = reliable_path
        self._nifty_path       = nifty_path
        self._external_path    = external_path
        self._script_name_data = script_name_data
        self._expiry_date      = expiry_date
        self._use_com          = use_com
        self._slow_interval_s  = slow_interval_s
        self._clock            = clock   # injectable for tests

        # Cached slow-source results: (headers, rows)
        self._rs_cache = None
        self._ni_cache = None
        self._ext_cache = None
        self._slow_stamp = None   # monotonic time of last slow refresh

        # Cached symbol-resolution map (rebuilt only when script data changes).
        self._name_to_symbol = None

        # Cached COM reader (created lazily on the worker thread).
        self._excel = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Initialise COM on the calling thread, if available."""
        if self._use_com:
            from services.com_reader import ExcelLiveReader
            self._excel = ExcelLiveReader()
            self._excel.init_thread()

    def stop(self) -> None:
        """Release COM handles on the calling thread."""
        if self._excel is not None:
            self._excel.close()
            self._excel = None

    # ── Reading ───────────────────────────────────────────────────────────────

    def _read_sharekhan(self):
        from services.file_reader import (
            read_sharekhan, _SHAREKHAN_COLS, _SHAREKHAN_HEADER_ROW,
        )
        if self._use_com and self._excel is not None:
            result = self._excel.read_workbook_sheet(
                self._sharekhan_path, _SHAREKHAN_COLS, _SHAREKHAN_HEADER_ROW
            )
            if result is not None:
                return result
        return read_sharekhan(self._sharekhan_path)

    def _read_reliable(self):
        from services.file_reader import (
            read_reliable_software, _RELIABLE_COLS, _RELIABLE_HEADER_ROW,
        )
        if self._use_com and self._excel is not None:
            result = self._excel.read_workbook_sheet(
                self._reliable_path, _RELIABLE_COLS, _RELIABLE_HEADER_ROW
            )
            if result is not None:
                return result
        return read_reliable_software(self._reliable_path)

    def _read_slow_sources(self, force: bool = False):
        """Refresh Reliable + Nifty + External if the slow interval has elapsed."""
        from services.file_reader import read_nifty_invest, read_external_import

        now = self._clock()
        due = (
            force
            or self._slow_stamp is None
            or (now - self._slow_stamp) >= self._slow_interval_s
        )
        if due:
            self._rs_cache  = self._read_reliable()
            self._ni_cache  = read_nifty_invest(self._nifty_path)
            self._ext_cache = (read_external_import(self._external_path)
                               if self._external_path else ([], []))
            self._slow_stamp = now

    def read_merged(self, force_slow: bool = False) -> tuple[list, list[list]]:
        """
        Read the sources and return (headers, merged_rows).

        Sharekhan is always re-read; Reliable/Nifty come from the slow cache
        unless ``force_slow`` is set or the slow interval has elapsed.
        """
        from services.master_generator import (
            _build_script_name_lookup, _normalise, _strip_date_suffix,
            _strip_rolling_suffix,
            _RS_DATA_INDICES, _NI_DATA_INDICES,
            _SK_PK_IDX, _RS_FK_IDX, _NI_FK_IDX,
        )

        sk_headers, sk_rows = self._read_sharekhan()
        self._read_slow_sources(force=force_slow)
        rs_headers, rs_rows = self._rs_cache
        ni_headers, ni_rows = self._ni_cache
        ext_headers, ext_rows = self._ext_cache if self._ext_cache else ([], [])

        # Strip expiry date suffix from Sharekhan Scrip Names
        if self._expiry_date is not None:
            expiry_str = self._expiry_date.strftime("%d-%b-%Y").upper()
            for sk_row in sk_rows:
                scrip = _normalise(sk_row[_SK_PK_IDX])
                if scrip.upper().endswith(expiry_str):
                    sk_row[_SK_PK_IDX] = scrip[:-len(expiry_str)].strip()

        if self._name_to_symbol is None:
            self._name_to_symbol = _build_script_name_lookup(self._script_name_data)
        name_to_symbol = self._name_to_symbol

        rs_lookup = {}
        for row in rs_rows:
            full_name = _strip_rolling_suffix(_normalise(row[_RS_FK_IDX]))
            sym = name_to_symbol.get(full_name.lower())
            if sym:
                rs_lookup[_normalise(sym).upper()] = row

        ni_lookup = {}
        for row in ni_rows:
            ni_lookup[_normalise(row[_NI_FK_IDX]).upper()] = row

        # External import: join on first column (must be symbol / scrip name)
        ext_data_indices = list(range(1, len(ext_headers))) if len(ext_headers) > 1 else []
        ext_lookup: dict = {}
        if ext_rows and ext_headers:
            for row in ext_rows:
                key = _strip_date_suffix(_normalise(row[0])).upper() if row else ""
                if key:
                    ext_lookup[key] = row

        out_headers = list(sk_headers)
        for i in _RS_DATA_INDICES:
            out_headers.append(rs_headers[i] if i < len(rs_headers) else "")
        for i in _NI_DATA_INDICES:
            out_headers.append(ni_headers[i] if i < len(ni_headers) else "")
        for i in ext_data_indices:
            out_headers.append(ext_headers[i] if i < len(ext_headers) else "")

        merged = []
        for sk_row in sk_rows:
            pk = _normalise(sk_row[_SK_PK_IDX]).upper()
            out_row = list(sk_row)
            rs_row = rs_lookup.get(pk)
            for i in _RS_DATA_INDICES:
                out_row.append(rs_row[i] if rs_row and i < len(rs_row) else None)
            ni_row = ni_lookup.get(pk)
            for i in _NI_DATA_INDICES:
                out_row.append(ni_row[i] if ni_row and i < len(ni_row) else None)
            ext_row = ext_lookup.get(pk)
            for i in ext_data_indices:
                out_row.append(ext_row[i] if ext_row and i < len(ext_row) else None)
            merged.append(out_row)

        return out_headers, merged
