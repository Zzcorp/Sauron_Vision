# Sauron: export of every trade record, READ-ONLY.
# Writes /tmp/sauron_export/ in the container: one Excel workbook (one sheet
# per table) and the same tables as CSV files. Changes nothing, calls nothing
# outside the server, and never exports a broker key or any secret.
import csv, datetime, decimal, io, json, math, os, re, zipfile
from xml.sax.saxutils import escape
from django.apps import apps
from django.db import connection, transaction
from django.utils import timezone

OUT = "/tmp/sauron_export"
STAMP = timezone.now().strftime("%Y-%m-%d_%H%M")
TABLES = [
    ("Trades", "bot_program.AssetBotTrade"),
    ("Bots and lanes", "bot_program.AssetBotConfig"),
    ("Crypto bot trades", "bot_program.BotTrade"),
    ("Portfolio positions", "portfolio.Position"),
    ("Position reviews", "brain.PositionReview"),
    ("Trade journal", "ai_agents.TradeJournalEntry"),
    ("Equity readings", "bot_program.BrokerEquityReading"),
    ("Orc legs", "OrcLeg"),
    ("Tax lots", "TaxLot"),
    ("Tax lot consumptions", "TaxLotConsumption"),
]
# Never exported, whatever the table: anything that could hold a secret.
SECRET = re.compile(r"(_enc$|secret|password|passwd|passphrase|api[_-]?key|user[_-]?key|"
                    r"access[_-]?token|refresh[_-]?token|auth[_-]?token|^token$|bearer|"
                    r"authorization|session[_-]?key|sessionid|cookie|credential|"
                    r"pin_hash|^pin$|private[_-]?key)", re.I)
MAX_CELL = 32000
BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def text(v):
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        if timezone.is_aware(v):
            v = v.astimezone(datetime.timezone.utc)
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, (datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str, sort_keys=True)
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, decimal.Decimal) and v.is_finite():
        return format(v, "f")  # 0.00000010, never 1.0E-7 or 0E-8
    return str(v)


def number(v):
    """The <v> text of a finite number, else None (the cell is then text)."""
    if isinstance(v, bool) or not isinstance(v, (int, float, decimal.Decimal)):
        return None
    if isinstance(v, float):
        return repr(v) if math.isfinite(v) else None
    if isinstance(v, decimal.Decimal):
        return format(v, "f") if v.is_finite() else None
    return str(v)


def scrub(v):
    """Drop secret-looking keys from a JSON value (metadata), at any depth."""
    if isinstance(v, dict):
        return {k: scrub(x) for k, x in v.items() if not SECRET.search(str(k))}
    if isinstance(v, list):
        return [scrub(x) for x in v]
    return v


def world(row):
    """Real, demo or simulated: the platform's own reading
    (dashboard/position_summary.world_of), with its silent case said out loud."""
    md = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    carrier = str(md.get("broker") or "").strip().lower()
    env = str(md.get("broker_env") or "").strip().lower()
    if row.get("paper") or carrier == "paper":
        return "SIMULATED (paper)"
    if env == "paper":
        return "DEMO (broker demo account)"
    if env == "live":
        return "REAL"
    return "REAL? (no world stamp)"


def col_name(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


class Book:
    """A minimal .xlsx writer (the standard library only): one sheet per table,
    text as inline strings, numbers as numbers."""

    def __init__(self, path):
        self.z = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED)
        self.sheets = []

    def add(self, name, header, rows):
        """Write one sheet from an ITERABLE of rows (never held in memory);
        return how many rows it wrote."""
        n = len(self.sheets) + 1
        self.sheets.append(re.sub(r"[\[\]:*?/\\]", " ", name)[:31])
        count = 0
        with self.z.open("xl/worksheets/sheet%d.xml" % n, "w") as f:
            w = io.TextIOWrapper(f, encoding="utf-8")
            w.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
                    'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetData>')
            w.write(self.row(1, header))
            for r, row in enumerate(rows, start=2):
                w.write(self.row(r, row))
                count += 1
            w.write("</sheetData></worksheet>")
            w.flush()
            w.detach()
        return count

    @staticmethod
    def row(r, row):
        cells = []
        for c, v in enumerate(row):
            ref = "%s%d" % (col_name(c), r)
            num = number(v) if r > 1 else None
            if num is not None:
                cells.append('<c r="%s"><v>%s</v></c>' % (ref, num))
            else:
                s = BAD_XML.sub("", text(v))[:MAX_CELL]
                if s:
                    st = ' s="1"' if r == 1 else ""
                    cells.append('<c r="%s" t="inlineStr"%s><is><t xml:space="preserve">%s</t></is></c>'
                                 % (ref, st, escape(s)))
        return '<row r="%d">%s</row>' % (r, "".join(cells))

    def close(self):
        n = len(self.sheets)
        z = self.z
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % i
                             for i in range(1, n + 1)) + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(s, {'"': "&quot;"}), i, i)
                             for i, s in enumerate(self.sheets, start=1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, i)
                             for i in range(1, n + 1))
                   + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' % (n + 1)
                   + "</Relationships>")
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                   '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
                   '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                   '</styleSheet>')
        z.close()


def find_model(label):
    """An 'app.Model' label, or a bare model class name looked up in every app."""
    if "." in label:
        return apps.get_model(label)
    for m in apps.get_models():
        if m.__name__ == label:
            return m
    raise LookupError(label)


def columns(model):
    return [f.attname for f in model._meta.concrete_fields if not SECRET.search(f.name)]


def read(model, names):
    """One row at a time (2000 per fetch): memory stays flat however long the history."""
    for vals in model.objects.order_by("pk").values_list(*names).iterator(chunk_size=2000):
        yield dict(zip(names, [scrub(v) for v in vals]))


def export():
    os.makedirs(OUT, exist_ok=True)
    book_path = os.path.join(OUT, "sauron_trades_%s.xlsx" % STAMP)
    book = Book(book_path)
    readme = [["Sheet", "Rows", "What one row is"]]
    about = {
        "Trades": "One trade Sauron opened or tracked (bots and manual tickets), real, broker demo or simulated: see the column 'world'. P&L columns are Sauron's records; eToro's own figures, when stored, are inside 'metadata'.",
        "Bots and lanes": "One bot or manual lane (config_id in Trades points here).",
        "Crypto bot trades": "One trade of the older crypto bots.",
        "Portfolio positions": "One position of the manual portfolio pages.",
        "Position reviews": "One AI review of an open position.",
        "Trade journal": "One journal entry written about a trade or a signal.",
        "Equity readings": "One reading of a broker account's equity over time.",
        "Orc legs": "Which trade (trade_id in Trades) belongs to which Orc idea: its root, an add or a re-entry.",
        "Tax lots": "One tax lot derived from a trade (long positions only).",
        "Tax lot consumptions": "How a closing trade consumed a tax lot.",
    }
    names_by_config = {}
    try:
        names_by_config = dict(apps.get_model("bot_program.AssetBotConfig").objects.values_list("id", "name"))
    except Exception:
        pass
    summary = []
    for sheet, label in TABLES:
        try:
            model = find_model(label)
        except LookupError:
            summary.append((sheet, "absent in this version"))
            continue
        cols = columns(model)
        trades = label == "bot_program.AssetBotTrade"
        header = (["world", "bot_or_lane"] if trades else []) + cols
        csv_path = os.path.join(OUT, "%s_%s.csv" % (re.sub(r"\W+", "_", sheet.lower()).strip("_"), STAMP))
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(header)

            def table():
                # Each row goes to the CSV and to the sheet in the same pass.
                for r in read(model, cols):
                    row = [r[c] for c in cols]
                    if trades:
                        row = [world(r), names_by_config.get(r.get("config_id"), "")] + row
                    w.writerow([text(v) for v in row])
                    yield row
            n = book.add(sheet, header, table())
        readme.append([sheet, n, about.get(sheet, "")])
        summary.append((sheet, n))
    readme.append(["", "", ""])
    readme.append(["Note", "", "Times are UTC. Positions opened directly in the eToro app, outside Sauron, are not in Sauron's records: eToro's own account statement has them."])
    readme.append(["Note", "", "Column 'world' in Trades: REAL = real money at the broker; DEMO = the broker's demo account; SIMULATED = Sauron's paper trading; 'REAL? (no world stamp)' = a broker trade whose row does not record real or demo (older rows, IBKR rows): Sauron's screens count it as real money, check it against the broker's statement."])
    readme.append(["Note", "", "A cell of this workbook holds at most 32,000 characters: longer texts (some 'metadata') are cut here and whole in the CSV files. Open this .xlsx in Excel; the CSV files use '.' decimals and ',' separators, for other tools."])
    readme.append(["Note", "", "Portfolio positions: rows the portfolio page's eToro sync created carry the time of that sync in 'opened_at', not the time of the trade."])
    readme.append(["Note", "", "Private data: keep these files for yourself, never on GitHub or in a public place."])
    book.add("README", readme[0], readme[1:])
    book.close()
    return book_path, summary


# Every read happens inside ONE read-only transaction: the database itself
# refuses any write from here on (Postgres) or the connection does (SQLite).
with transaction.atomic():
    with connection.cursor() as cur:
        if connection.vendor == "postgresql":
            # REPEATABLE READ: every sheet is the same instant, even while bots trade.
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SHOW transaction_read_only")
            ro = cur.fetchone()[0]
        elif connection.vendor == "sqlite":
            cur.execute("PRAGMA query_only = ON")
            cur.execute("PRAGMA query_only")
            ro = "on" if cur.fetchone()[0] else "off"
        else:
            ro = "unknown"
    if ro != "on":
        raise SystemExit("Stopped: the database session is not read-only (%s). Nothing was exported." % ro)
    path, summary = export()
print("Read-only export done (database read-only: on). Folder in the container:", OUT)
for sheet, n in summary:
    print("  %-22s %s" % (sheet, n))
for name in sorted(os.listdir(OUT)):
    if STAMP in name:
        print("  file:", name, os.path.getsize(os.path.join(OUT, name)), "bytes")
