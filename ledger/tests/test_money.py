from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from ledger.services import format_amount_input, format_ars, parse_amount


class ParseAmountTests(SimpleTestCase):
    def test_valid_formats(self):
        cases = {
            "15000": 1500000,
            "15.000": 1500000,
            "15.000,50": 1500050,
            "15000,5": 1500050,
            "$ 1.234,56": 123456,
            "$1.234,56": 123456,
            "  7  ": 700,
            "0,01": 1,
            "1.234.567,89": 123456789,
            "1234567,89": 123456789,
            "12.345.678.901": 1234567890100,
            "98765432109,99": 9876543210999,
            "1.000.000": 100000000,
            "15.5": 1550,
            "15.50": 1550,
            "1.23": 123,
        }
        for text, cents in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_amount(text), cents)

    def test_invalid_inputs(self):
        for text in [
            "",
            "   ",
            "$",
            "0",
            "0,00",
            "-5",
            "-1.000,00",
            "15,505",
            "1.5,00",
            "15.00.0",
            "1,000.50",
            "abc",
            "12a",
            "15,",
            ",50",
            "1.234.56",
            "15.000,5.0",
            "99999999999999999999",
        ]:
            with self.subTest(text=text):
                with self.assertRaises(ValidationError):
                    parse_amount(text)


class FormatTests(SimpleTestCase):
    def test_format_ars(self):
        cases = {
            0: "$ 0,00",
            1: "$ 0,01",
            99: "$ 0,99",
            100: "$ 1,00",
            123456: "$ 1.234,56",
            123456789: "$ 1.234.567,89",
            1234567890123: "$ 12.345.678.901,23",
            -5000: "-$ 50,00",
            -123456789: "-$ 1.234.567,89",
            -1: "-$ 0,01",
        }
        for cents, text in cases.items():
            with self.subTest(cents=cents):
                self.assertEqual(format_ars(cents), text)

    def test_format_amount_input_round_trips(self):
        self.assertEqual(format_amount_input(1500050), "15.000,50")
        self.assertEqual(format_amount_input(1500000), "15.000,00")
        self.assertEqual(format_amount_input(5), "0,05")
        for cents in [1, 99, 100, 123456, 1500050, 123456789, 9876543210999]:
            with self.subTest(cents=cents):
                self.assertEqual(parse_amount(format_amount_input(cents)), cents)
                self.assertEqual(parse_amount(format_ars(cents)), cents)
