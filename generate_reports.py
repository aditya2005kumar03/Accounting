"""Generate static CSV reports from a journal and Chart of Accounts.

Usage:
    python generate_reports.py
    python generate_reports.py --journal another_journal.csv --chart chart_of_accounts.csv --output-dir reports
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from decimal import Decimal

from accounting_engine import parse_chart_csv_text, parse_journal_csv_text, compute_financials, audit_checks, chart_to_csv

BASE_DIR = Path(__file__).resolve().parent


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: f"{row[key]:.2f}" if isinstance(row.get(key), Decimal) else row.get(key, "") for key in headers})


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate LedgerLab accounting reports from a CSV journal.")
    parser.add_argument("--journal", type=Path, default=BASE_DIR / "journal_entries.csv", help="Journal CSV input")
    parser.add_argument("--chart", type=Path, default=BASE_DIR / "chart_of_accounts.csv", help="Chart of Accounts CSV input")
    parser.add_argument("--output-dir", type=Path, default=BASE_DIR / "sample_reports", help="Folder for output CSV files")
    args = parser.parse_args()

    chart = parse_chart_csv_text(args.chart.read_text(encoding="utf-8-sig"))
    rows = parse_journal_csv_text(args.journal.read_text(encoding="utf-8-sig"), chart)
    reports = compute_financials(rows, chart)
    checks = audit_checks(rows, chart, reports)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    with (out / "journal_entries.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "entry_id", "description", "account", "debit", "credit"])
        writer.writeheader()
        writer.writerows(rows)
    (out / "chart_of_accounts.csv").write_text(chart_to_csv(chart), encoding="utf-8-sig")

    write_csv(out / "trial_balance.csv", ["account", "category", "total_debits", "total_credits", "debit_balance", "credit_balance"], reports["trial_balance"])
    write_csv(out / "account_balances.csv", ["account", "category", "normal_balance_side", "total_debits", "total_credits", "closing_balance"], reports["account_balances"])

    pl_rows = ([{"section": "Income", **x} for x in reports["income_rows"]]
               + [{"section": "Total income", "account": "", "amount": reports["total_income"]}]
               + [{"section": "Expenses", **x} for x in reports["expense_rows"]]
               + [{"section": "Total expenses", "account": "", "amount": reports["total_expenses"]},
                  {"section": "Net profit / (loss)", "account": "", "amount": reports["net_profit"]}])
    write_csv(out / "profit_and_loss.csv", ["section", "account", "amount"], pl_rows)

    bs_rows = []
    for key, label in [("current_assets", "Current assets"), ("fixed_assets", "Fixed assets"), ("contra_assets", "Less: accumulated depreciation / contra assets")]:
        bs_rows.extend({"section": label, **item} for item in reports[key])
    bs_rows.append({"section": "Total assets", "account": "", "amount": reports["total_assets"]})
    bs_rows.extend({"section": "Liabilities", **item} for item in reports["liabilities"])
    bs_rows.extend({"section": "Equity", **item} for item in reports["equity_accounts"])
    bs_rows.extend([
        {"section": "Current-period profit / (loss)", "account": "", "amount": reports["net_profit"]},
        {"section": "Total liabilities and equity", "account": "", "amount": reports["liabilities_and_equity"]},
        {"section": "Balance Sheet difference", "account": "", "amount": reports["balance_sheet_difference"]},
    ])
    write_csv(out / "balance_sheet.csv", ["section", "account", "amount"], bs_rows)
    write_csv(out / "audit_checks.csv", ["check", "status", "details"], checks)

    summary = [
        "LedgerLab demo accounting report",
        f"Business dataset: {args.journal.name}",
        f"Reporting period covered by journal: {reports['min_date']} to {reports['max_date']}",
        f"Transactions: {reports['transaction_count']}",
        f"Journal lines: {reports['line_count']}",
        f"Journal debits: ₹{reports['journal_total_debits']:,.2f}",
        f"Journal credits: ₹{reports['journal_total_credits']:,.2f}",
        f"Total income: ₹{reports['total_income']:,.2f}",
        f"Total expenses: ₹{reports['total_expenses']:,.2f}",
        f"Net profit / (loss): ₹{reports['net_profit']:,.2f}",
        f"Total assets: ₹{reports['total_assets']:,.2f}",
        f"Total liabilities and equity: ₹{reports['liabilities_and_equity']:,.2f}",
        f"Balance Sheet difference: ₹{reports['balance_sheet_difference']:,.2f}",
        f"Checks passed: {sum(1 for check in checks if check['passed'])}/{len(checks)}",
        "",
        "Audit checks are automated assignment checks, not a professional audit opinion.",
    ]
    (out / "accounting_report.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(f"Reports saved to: {out}")
    print(f"Transactions: {reports['transaction_count']} | Journal lines: {reports['line_count']}")
    print(f"Net profit: ₹{reports['net_profit']:,.2f} | Balance Sheet difference: ₹{reports['balance_sheet_difference']:,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
