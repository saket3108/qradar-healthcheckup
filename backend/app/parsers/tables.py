"""Tolerant reader for PostgreSQL table exports found in get_logs bundles.

Supported physical formats (auto-detected, may be mixed in one file):
  * ``pg_dump`` plain SQL:   ``COPY schema.table (cols) FROM stdin;`` ... ``\\.``
  * ``pg_dump --inserts``:   ``INSERT INTO table (cols) VALUES (...);``
  * ``psql`` aligned output: header ``a | b | c`` + ``---+---`` separator + rows
  * ``psql -x`` expanded:    ``-[ RECORD 1 ]---`` blocks of ``col | value``
  * CSV / TSV with header row (table name derived from file name)
"""
from __future__ import annotations

import csv
import gzip
import io
import re
from pathlib import Path
from typing import Callable, Iterable, Iterator

csv.field_size_limit(1 << 28)

Row = dict[str, str | None]

_COPY_RE = re.compile(r'^COPY\s+(?P<tbl>[\w\."$]+)\s*\((?P<cols>[^)]*)\)\s+FROM\s+stdin', re.I)
_INSERT_RE = re.compile(r'^INSERT\s+INTO\s+(?P<tbl>[\w\."$]+)\s*(?:\((?P<cols>[^)]*)\))?\s*VALUES\s*(?P<vals>.*)$', re.I)
_RECORD_RE = re.compile(r'^-\[ RECORD (\d+) \]')
_UNESC = {"t": "\t", "n": "\n", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "\\": "\\"}


def norm_table(name: str) -> str:
    name = name.replace('"', "").strip()
    return name.split(".")[-1].lower()


def _split_cols(s: str) -> list[str]:
    return [c.strip().strip('"').lower() for c in s.split(",")]


def _unescape_copy(v: str) -> str | None:
    if v == "\\N":
        return None
    if "\\" not in v:
        return v
    out, i = [], 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            out.append(_UNESC.get(v[i + 1], v[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _open_text(path: Path) -> io.TextIOBase:
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace", newline="")
    return open(path, "r", encoding="utf-8", errors="replace", newline="")


def _parse_sql_values(vals: str) -> list[list[str | None]]:
    """Parse ``(1,'a'),(2,'b');`` → rows. Handles quotes, escaped quotes and NULL."""
    rows: list[list[str | None]] = []
    cur: list[str | None] = []
    buf: list[str] = []
    i, n = 0, len(vals)
    in_q = False
    in_row = False
    was_quoted = False
    while i < n:
        c = vals[i]
        if in_q:
            if c == "'" and i + 1 < n and vals[i + 1] == "'":
                buf.append("'")
                i += 2
                continue
            if c == "'":
                in_q = False
            elif c == "\\" and i + 1 < n:
                buf.append(_UNESC.get(vals[i + 1], vals[i + 1]))
                i += 2
                continue
            else:
                buf.append(c)
        else:
            if c == "'":
                in_q, was_quoted = True, True
            elif c == "(" and not in_row:
                in_row, cur, buf, was_quoted = True, [], [], False
            elif c in ",)" and in_row:
                tok = "".join(buf).strip() if not was_quoted else "".join(buf)
                cur.append(None if (not was_quoted and tok.upper() == "NULL") else tok)
                buf, was_quoted = [], False
                if c == ")":
                    rows.append(cur)
                    in_row = False
            elif in_row:
                buf.append(c)
        i += 1
    return rows


def iter_tables(path: Path, wanted: Callable[[str], bool] | None = None,
                max_rows: int = 2_000_000) -> Iterator[tuple[str, list[str], Iterator[Row]]]:
    """Yield ``(table, columns, rows_iterator)`` for each table found. The row iterator MUST be consumed
    before advancing to the next table (streaming)."""
    name = path.name.lower()
    if name.endswith(".gz"):
        name = name[:-3]
    if name.endswith((".csv", ".tsv")):
        yield from _iter_delimited(path, name, wanted, max_rows)
        return
    yield from _iter_sql_or_psql(path, name, wanted, max_rows)


def _stem_table(fname: str) -> str:
    stem = re.sub(r"\.(sql|dump|copy|csv|tsv|txt|out|log|psql)$", "", fname)
    stem = re.sub(r"^(dump_|pg_|export_)", "", stem)
    return norm_table(stem)


def _iter_delimited(path: Path, name: str, wanted, max_rows):
    tbl = _stem_table(name)
    if wanted and not wanted(tbl):
        return
    fh = _open_text(path)
    head = fh.read(4096)
    fh.seek(0)
    delim = "\t" if head.count("\t") > head.count(",") else ","
    reader = csv.reader(fh, delimiter=delim)
    try:
        cols = [c.strip().lower() for c in next(reader)]
    except StopIteration:
        return

    def rows():
        for i, rec in enumerate(reader):
            if i >= max_rows:
                break
            yield {c: (None if v in ("\\N", "") else v) for c, v in zip(cols, rec)}
    try:
        yield tbl, cols, rows()
    finally:
        fh.close()


def _iter_sql_or_psql(path: Path, fname: str, wanted, max_rows):
    fh = _open_text(path)
    try:
        lines = iter(fh)
        pending: list[str] = []          # one-line lookahead buffer
        guess_tbl = _stem_table(fname)

        def next_line():
            if pending:
                return pending.pop()
            return next(lines, None)

        while True:
            line = next_line()
            if line is None:
                return
            ln = line.rstrip("\r\n")

            m = _COPY_RE.match(ln)
            if m:
                tbl, cols = norm_table(m["tbl"]), _split_cols(m["cols"])
                if wanted and not wanted(tbl):
                    while True:                       # skip block
                        x = next_line()
                        if x is None or x.startswith("\\."):
                            break
                    continue

                def copy_rows(cols=cols):
                    count = 0
                    while True:
                        x = next_line()
                        if x is None or x.startswith("\\."):
                            return
                        if count >= max_rows:
                            continue
                        vals = x.rstrip("\r\n").split("\t")
                        count += 1
                        yield {c: _unescape_copy(v) for c, v in zip(cols, vals)}
                yield tbl, cols, copy_rows()
                continue

            m = _INSERT_RE.match(ln)
            if m:
                tbl = norm_table(m["tbl"])
                cols = _split_cols(m["cols"]) if m["cols"] else []
                stmt = m["vals"]
                while not stmt.rstrip().endswith(";"):
                    x = next_line()
                    if x is None:
                        break
                    stmt += x
                if wanted and not wanted(tbl):
                    continue
                vrows = _parse_sql_values(stmt)
                yield tbl, cols, ({c: v for c, v in zip(cols, r)} for r in vrows[:max_rows])
                continue

            if _RECORD_RE.match(ln):
                if wanted and not wanted(guess_tbl):
                    continue
                pending.append(line)
                yield from _psql_expanded(next_line, pending, guess_tbl, max_rows)
                continue

            # psql aligned: header line with '|' followed by dashed separator
            if "|" in ln and ln.strip():
                nxt = next_line()
                if nxt is not None and re.match(r"^[-+]+$", nxt.strip()) and "-" in nxt:
                    if wanted and not wanted(guess_tbl):
                        continue
                    cols = [c.strip().lower() for c in ln.split("|")]

                    def aligned_rows(cols=cols):
                        count = 0
                        while True:
                            x = next_line()
                            if x is None:
                                return
                            xs = x.rstrip("\r\n")
                            if not xs.strip() or re.match(r"^\(\d+ rows?\)", xs.strip()):
                                return
                            if count >= max_rows:
                                continue
                            parts = [p.strip() for p in xs.split("|")]
                            count += 1
                            yield {c: (v if v != "" else None) for c, v in zip(cols, parts)}
                    yield guess_tbl, cols, aligned_rows()
                    continue
                elif nxt is not None:
                    pending.append(nxt)
    finally:
        fh.close()


def _psql_expanded(next_line, pending, tbl, max_rows):
    cols_seen: list[str] = []
    records: list[Row] = []
    cur: Row = {}
    while True:
        x = next_line()
        if x is None:
            break
        xs = x.rstrip("\r\n")
        if _RECORD_RE.match(xs):
            if cur:
                records.append(cur)
            cur = {}
            continue
        if not xs.strip():
            if cur and records is not None:
                # blank line terminates the table only if next is not a record header
                nxt = next_line()
                if nxt is None:
                    break
                if _RECORD_RE.match(nxt):
                    pending.append(nxt)
                    continue
                pending.append(nxt)
                break
            continue
        if "|" in xs:
            k, _, v = xs.partition("|")
            k = k.strip().lower()
            cur[k] = v.strip() or None
            if k not in cols_seen:
                cols_seen.append(k)
        else:
            pending.append(x)
            break
    if cur:
        records.append(cur)
    yield tbl, cols_seen, iter(records[:max_rows])


# ---------------------------------------------------------------------------
# High-level collector
# ---------------------------------------------------------------------------
class TableStore:
    """Collects the wanted tables from all candidate files in an extraction root."""

    def __init__(self, wanted_names: Iterable[str], max_rows: int = 2_000_000) -> None:
        self.wanted = {w.lower() for w in wanted_names}
        self.max_rows = max_rows
        self.tables: dict[str, list[Row]] = {}
        self.sources: dict[str, list[str]] = {}

    def _is_wanted(self, tbl: str) -> bool:
        return tbl in self.wanted

    def load(self, path: Path, rel: str) -> int:
        n = 0
        try:
            for tbl, cols, rows in iter_tables(path, self._is_wanted, self.max_rows):
                bucket = self.tables.setdefault(tbl, [])
                before = len(bucket)
                for r in rows:
                    if len(bucket) >= self.max_rows:
                        break
                    bucket.append(r)
                n += len(bucket) - before
                self.sources.setdefault(tbl, []).append(rel)
        except (OSError, EOFError, UnicodeError):
            return n
        return n

    def get(self, name: str) -> list[Row]:
        return self.tables.get(name.lower(), [])
