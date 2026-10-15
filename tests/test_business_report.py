import importlib.util
import unittest
from datetime import date
from pathlib import Path

spec = importlib.util.spec_from_file_location('report', Path(__file__).resolve().parents[1] / 'skills/erp-business-report/scripts/report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def snapshot(orders=(), bins=(), items=()):
    return {'queried_at': '2026-10-14T10:00:00+00:00',
            **{kind: {'rows': list(rows), 'complete': True, 'error': None}
               for kind, rows in [('Sales Order', orders), ('Bin', bins), ('Item', items)]}}


def order(name='SO-1', amount='0.1', currency='CNY', status='To Bill', docstatus=1, day='2026-10-14'):
    return dict(name=name, grand_total=amount, currency=currency, status=status, docstatus=docstatus,
                transaction_date=day, per_delivered=100)


class ReportTests(unittest.TestCase):
    def test_date_boundaries(self):
        today = date(2026, 1, 1)
        self.assertEqual(report.dates('last7', today=today), (date(2025, 12, 26), today))
        self.assertEqual(report.dates('yesterday', today=today), (date(2025, 12, 31),)*2)
        with self.assertRaises(ValueError):
            report.dates('range', '2026-10-15', '2026-10-14')
        with self.assertRaises(ValueError):
            report.dates('range', '2026-02-30', '2026-03-01')

    def test_amounts_decimal_separate_currency_exclude_cancel_draft(self):
        data = snapshot([order(), order('SO2', '0.2'), order('SO3', '4.5', 'USD'),
                         order('D', '99', docstatus=0), order('C', '99', docstatus=2)])
        result = report.analyze(data)
        self.assertEqual(result['amounts'], {'CNY': '0.3', 'USD': '4.5'})
        self.assertEqual(result['order_count'], 5)

    def test_today_does_not_use_historical_orders(self):
        data = snapshot([order(day='2026-10-13')])
        result = report.analyze(data, date(2026, 10, 14), date(2026, 10, 14))
        self.assertEqual(result['order_count'], 0)
        self.assertTrue(result['issues'])  # Detect server returning a row outside its date filter.
        self.assertEqual(report.analyze(snapshot())['order_count'], 0)

    def test_missing_fields_and_http_failure_not_zero(self):
        data = snapshot([order(amount=None, currency=None)])
        data['Bin'] = {'complete': False, 'rows': [], 'error': 'HTTP_403'}
        result = report.analyze(data)
        self.assertTrue(result['amount_incomplete'])
        self.assertTrue(any('HTTP_403' in issue for issue in result['issues']))
        self.assertIn('全量风险数未知', report.render(data, result, None, None))
        data['Sales Order'] = {'complete': False, 'rows': [], 'error': 'NETWORK_OR_TIMEOUT'}
        result = report.analyze(data)
        self.assertFalse(result['order_query_complete'])
        self.assertIn('总数未知', report.render(data, result, None, None))

    def test_threshold_multiwarehouse_and_missing_qty(self):
        bins = [dict(item_code='A', warehouse='W1', actual_qty=20, reserved_qty=4),
                dict(item_code='A', warehouse='W2', actual_qty=0, reserved_qty=0),
                dict(item_code='B', warehouse='W1', actual_qty=58, reserved_qty=0),
                dict(item_code='X', warehouse='W1', actual_qty=None, reserved_qty=None)]
        data = snapshot(bins=bins, items=[{'item_code': x, 'item_name': x} for x in ['A', 'B', 'X']])
        normal = report.analyze(data)
        high = report.analyze(data, threshold=60)
        self.assertFalse(normal['inventory'][0]['low'])
        self.assertEqual(normal['low_skus'], ['A'])
        self.assertEqual(normal['zero_skus'], ['A'])
        self.assertEqual(high['low_skus'], ['A', 'B'])
        self.assertEqual(normal['sku_totals']['A']['actual'], '20')
        self.assertFalse(normal['inventory'][-1]['zero'])
        self.assertEqual(normal['sku_totals']['X']['actual'], '未知')
        self.assertTrue(normal['issues'])
        with self.assertRaises(ValueError):
            report.analyze(data, threshold='NaN')

    def test_to_bill_only_requires_invoicing_check(self):
        result = report.analyze(snapshot([order()]))
        self.assertIn('待开票', result['concerns'][0]['reason'])
        self.assertNotIn('未发货', result['concerns'][0]['reason'])
        self.assertNotIn('未交付', result['concerns'][0]['reason'])

    def test_duplicate_bin_not_counted_twice(self):
        row = dict(item_code='A', warehouse='W', actual_qty=7, reserved_qty=0)
        result = report.analyze(snapshot(bins=[row, row], items=[{'item_code': 'A', 'item_name': 'A'}]))
        self.assertEqual(result['sku_totals']['A']['actual'], '7')
        self.assertTrue(result['issues'])


if __name__ == '__main__':
    unittest.main()
