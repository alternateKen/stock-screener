"""Offline checks for the worksheet-export reader in bloomberg/bbg_sync.py (no Bloomberg, no network)."""
import os, sys, tempfile, unittest, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bloomberg"))
import bbg_sync as b  # noqa: E402


def xlsx(path, sheets):
    """Write a minimal .xlsx: {sheet name: [rows of strings]} (inline strings, no shared-strings table)."""
    def cell(i, j, v):
        col = chr(65 + j)
        v = v.replace("&", "&amp;").replace("<", "&lt;")
        return f'<c r="{col}{i + 1}" t="inlineStr"><is><t>{v}</t></is></c>' if v else ""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{n}" sheetId="{k + 1}" r:id="rId{k + 1}"/>' for k, n in enumerate(sheets)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{k + 1}" Target="worksheets/sheet{k + 1}.xml"/>' for k in range(len(sheets))) + "</Relationships>")
        for k, rows in enumerate(sheets.values()):
            z.writestr(f"xl/worksheets/sheet{k + 1}.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                       + "".join(f'<row r="{i + 1}">' + "".join(cell(i, j, v) for j, v in enumerate(r)) + "</row>" for i, r in enumerate(rows))
                       + "</sheetData></worksheet>")


class GH:
    """Stands in for the GitHub helper: the site's theme files."""
    files = {"themes/korea.txt": "[Chips]\n005930 KP | Samsung Electronics\n084370 KQ | Eugene Technology\n",
             "themes/asean.txt": "[Singapore]\nD05.SI | DBS Group\nO39.SI | OCBC\n", "themes/inbox.txt": "# inbox\n", "universe.txt": ""}

    def list_dir(self, repo, path):
        return [{"name": p.split("/")[1]} for p in self.files if p.startswith("themes/")]

    def read(self, repo, path):
        return self.files[path]


class BBG:
    """Stands in for Bloomberg: NAME and ID_EXCH_SYMBOL for the securities it knows."""
    known = {"NVDA US Equity": ("NVIDIA CORP", "NVDA"), "000660 KS Equity": ("SK HYNIX INC", "000660"),
             "UOB SP Equity": ("UNITED OVERSEAS BANK LTD", "U11"), "OCBC SP Equity": ("OVERSEA-CHINESE BANKING CORP", "O39"),
             "BHP US Equity": ("BHP GROUP LTD-ADR", "BHP"), "XYZ US Equity": ("SOMETHING ELSE INC", "XYZ")}

    def __init__(self):
        self.secs, self.hits, self.asked = set(), 0, []

    def ref(self, secs, fields):
        self.asked += secs
        return {s: {"NAME": self.known[s][0], "ID_EXCH_SYMBOL": self.known[s][1]} for s in secs if s in self.known}, {}


class Worksheets(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        b.WORKSHEETS = self.dir
        b.REPORT.clear()

    def run_once(self, st=None):
        st = {} if st is None else st
        files, bbg = {}, BBG()
        b.worksheet_inbox(GH(), bbg, st, files)
        return files.get("themes/inbox.txt", ""), st, bbg

    def test_exchange_codes(self):
        xlsx(os.path.join(self.dir, "W99.xlsx"), {"Global": [
            ["Ticker and Exchange Code", "Short Comp Name"], ["Top Performers  (2)", ""],
            ["NVDA US Equity", "NVIDIA Corp"], ["005930 KS Equity", "Samsung Electronics Co Ltd"],   # Samsung: already on the site
            ["UOB SP Equity", "United Overseas Bank Ltd"], ["OCBC SP Equity", "Oversea-Chinese Banking Corp"],   # OCBC: on the site as O39.SI
            ["XYZ US Equity", "Acme Widgets Inc"],   # Bloomberg's name differs: not added
            ["USD Curncy", "#N/A Field Not Applicable"], ["SPY US Equity", "SPDR S&P 500 ETF Trust"]]})
        inbox, st, bbg = self.run_once()
        self.assertIn("NVDA US | NVIDIA Corp", inbox)
        self.assertIn("U11.SI | United Overseas Bank Ltd", inbox)   # Singapore: Yahoo's code from the exchange symbol
        self.assertNotIn("O39", inbox)
        self.assertNotIn("XYZ", inbox)
        self.assertNotIn("005930", inbox)
        self.assertFalse([s for s in bbg.asked if "Curncy" in s or "SPY" in s])
        # a second run adds nothing again, even if the names are later deleted from the site
        inbox2, _, bbg2 = self.run_once(st)
        self.assertEqual(inbox2, "")
        self.assertNotIn("NVDA US Equity", bbg2.asked)

    def test_bare_tickers_need_a_market_or_a_name(self):
        xlsx(os.path.join(self.dir, "W41 Korea.xlsx"), {"Korea": [
            ["Ticker", "Short Comp Name"], ["660", "SK hynix Inc"], ["84370", "Eugene Technology Co Ltd"]]})
        xlsx(os.path.join(self.dir, "W1 Funds.xlsx"), {"Funds": [["Ticker", "Last Price"], ["BHP", "45.1"], ["2330", "1000"]]})
        inbox, _, bbg = self.run_once()
        self.assertIn("000660 KS | SK hynix Inc", inbox)   # Korea tab: zero-padded, KOSPI tried first
        self.assertNotIn("084370", inbox)                  # on the site as a KOSDAQ code
        self.assertNotIn("BHP US Equity", bbg.asked)       # no name and no market: never guessed as a US listing
        self.assertIn("names without an exchange code skipped", "\n".join(b.REPORT))

    def test_name_matching(self):
        self.assertTrue(b.same_company("Commonwealth Bank of Australi", "Commonwealth Bank of Australia"))
        self.assertTrue(b.same_company("DBS Group Holdings Ltd", "DBS Group"))
        self.assertTrue(b.same_company("BHP GROUP LTD-ADR", "BHP Group"))
        self.assertFalse(b.same_company("Keppel REIT", "Keppel"))
        self.assertFalse(b.same_company("Samsung Electronics Co Ltd", "Samsung Electro-Mechanics"))
        self.assertEqual(b.ws_candidates("3308", "CN"), ["3308 HK", "003308 CH"])
        self.assertEqual(b.ws_candidates("600519", "CN"), ["600519 CH"])


if __name__ == "__main__":
    unittest.main()
