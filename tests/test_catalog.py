import copy
import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook
from waiterbot.catalog import Catalog, HEADERS, ROLES


class CatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.row = ["Меню", "Вопрос?", "А", "Б", "В", "Г", 1, "Пояснение"]
        for role in ROLES:
            self.write(role, [self.row])
        self.catalog = Catalog(self.directory)

    def write(self, role, rows):
        book = Workbook()
        sheet = book.active
        sheet.append(HEADERS + ["Объяснение"])
        for row in rows:
            sheet.append(row)
        book.save(self.directory / ROLES[role]["file"])
        book.close()

    def test_real_workbooks_are_compatible(self):
        catalog = Catalog(Path(__file__).resolve().parents[1])
        counts = catalog.reload()
        self.assertTrue(all(counts[role] > 0 for role in ROLES))

    def test_invalid_reload_preserves_existing_catalog(self):
        self.catalog.reload()
        before = copy.deepcopy(self.catalog.questions)
        bad = self.row.copy()
        bad[6] = 9
        self.write("waiter", [bad])
        with self.assertRaisesRegex(ValueError, "строка 2"):
            self.catalog.reload()
        self.assertEqual(self.catalog.questions, before)

    def test_duplicates_and_edited_questions(self):
        self.write("waiter", [self.row, self.row])
        self.catalog.reload()
        old = self.catalog.questions["waiter"]
        self.assertEqual(len(old), 1)
        changed = self.row.copy()
        changed[6] = 2
        self.write("waiter", [changed])
        self.catalog.reload()
        self.assertEqual(self.catalog.mistakes("waiter", old), [])

    def test_bad_options_formulas_and_answers_are_rejected(self):
        for column, value in [(2, None), (2, "=1+1"), (3, "А"), (6, True), (6, "oops")]:
            with self.subTest(column=column, value=value):
                row = self.row.copy()
                row[column] = value
                self.write("waiter", [row])
                with self.assertRaises(ValueError):
                    self.catalog.reload()
