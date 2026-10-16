"""Lightweight self-tests for LedgerLab's accounting engine. Run: python test_accounting_engine.py"""
from pathlib import Path
from decimal import Decimal

from accounting_engine import parse_chart_csv_text, parse_journal_csv_text, compute_financials, audit_checks

BASE_DIR = Path(__file__).resolve().parent
chart = parse_chart_csv_text((BASE_DIR / "chart_of_accounts.csv").read_text(encoding="utf-8-sig"))
rows = parse_journal_csv_text((BASE_DIR / "journal_entries.csv").read_text(encoding="utf-8-sig"), chart)
reports = compute_financials(rows, chart)
checks = audit_checks(rows, chart, reports)

assert len(chart) == 36, f"Expected 36 chart accounts, found {len(chart)}"
assert reports["transaction_count"] == 75, f"Expected 75 transactions, found {reports['transaction_count']}"
assert reports["line_count"] == 210, f"Expected 210 journal lines, found {reports['line_count']}"
assert reports["journal_total_debits"] == reports["journal_total_credits"]
assert reports["total_income"] == Decimal("644000.00")
assert reports["total_expenses"] == Decimal("592350.00")
assert reports["net_profit"] == Decimal("51650.00")
assert reports["total_assets"] == Decimal("897250.00")
assert reports["balance_sheet_difference"] == Decimal("0.00")
assert all(check["passed"] for check in checks), [check for check in checks if not check["passed"]]

try:
    parse_journal_csv_text(
        "date,entry_id,description,account,debit,credit\n"
        "2025-01-01,BAD01,Unbalanced test,Cash,100,0\n", chart
    )
except ValueError as exc:
    assert "debits" in str(exc).lower() and "credits" in str(exc).lower()
else:
    raise AssertionError("Unbalanced journal transaction should be rejected.")

print("All LedgerLab accounting-engine tests passed.")
print(f"Demo: {reports['transaction_count']} transactions; net profit ₹{reports['net_profit']:,.2f}; Balance Sheet difference ₹{reports['balance_sheet_difference']:,.2f}.")
