"""Reusable double-entry accounting engine for LedgerLab.

The engine accepts a journal CSV and a configurable chart of accounts. It uses
Decimal for monetary arithmetic and classifies financial statements by account
category instead of hard-coding a particular business's account names.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

ALLOWED_CATEGORIES = {
    "Asset", "Current Asset", "Non-current Asset", "Fixed Asset", "Contra Asset",
    "Liability", "Current Liability", "Non-current Liability", "Equity", "Income", "Expense",
}
ALLOWED_NORMAL_SIDES = {"Debit", "Credit"}
REQUIRED_JOURNAL_COLUMNS = {"date", "entry_id", "description", "account", "debit", "credit"}
REQUIRED_CHART_COLUMNS = {"account", "category", "normal_balance_side"}


def money(value) -> Decimal:
    """Parse a money value and round to two decimal places."""
    text = str(value if value is not None else "0").strip().replace(",", "")
    if text == "":
        text = "0"
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"'{value}' is not a valid amount.") from exc
    if not number.is_finite():
        raise ValueError("Amounts must be finite numbers.")
    return number.quantize(CENT, rounding=ROUND_HALF_UP)


def amount_text(value) -> str:
    return f"{money(value):.2f}"


def _csv_reader(text: str) -> csv.DictReader:
    stream = io.StringIO(text.lstrip("\ufeff"), newline="")
    return csv.DictReader(stream)


def parse_chart_csv_text(text: str) -> list[dict]:
    """Parse and validate a chart-of-accounts CSV string."""
    reader = _csv_reader(text)
    headers = {str(c or "").strip().lower(): c for c in (reader.fieldnames or [])}
    missing = REQUIRED_CHART_COLUMNS - set(headers)
    if missing:
        raise ValueError("Chart of Accounts CSV is missing columns: " + ", ".join(sorted(missing)))

    chart: list[dict] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(reader, start=2):
        if not any(str(v or "").strip() for v in raw.values()):
            continue
        account = str(raw.get(headers["account"], "") or "").strip()
        category = str(raw.get(headers["category"], "") or "").strip()
        side = str(raw.get(headers["normal_balance_side"], "") or "").strip().title()
        if not account:
            raise ValueError(f"Blank account name on chart line {line_number}.")
        if account.casefold() in seen:
            raise ValueError(f"Duplicate account name '{account}' on chart line {line_number}.")
        if category not in ALLOWED_CATEGORIES:
            raise ValueError(
                f"Invalid category '{category}' for '{account}'. Allowed categories: "
                + ", ".join(sorted(ALLOWED_CATEGORIES))
            )
        if side not in ALLOWED_NORMAL_SIDES:
            raise ValueError(f"Normal balance for '{account}' must be Debit or Credit.")
        expected_side = "Credit" if category in {"Contra Asset", "Liability", "Current Liability", "Non-current Liability", "Equity", "Income"} else "Debit"
        if side != expected_side:
            raise ValueError(f"'{account}' in category '{category}' normally has a {expected_side} balance. Correct the chart before uploading.")
        seen.add(account.casefold())
        chart.append({"account": account, "category": category, "normal_balance_side": side})

    if not chart:
        raise ValueError("Chart of Accounts file contains no accounts.")
    return chart


def chart_to_csv(chart: Iterable[dict]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["account", "category", "normal_balance_side"])
    writer.writeheader()
    for account in chart:
        writer.writerow({
            "account": account["account"],
            "category": account["category"],
            "normal_balance_side": account["normal_balance_side"],
        })
    return output.getvalue()


def parse_journal_csv_text(text: str, chart: Iterable[dict]) -> list[dict]:
    """Parse and validate journal CSV text against the supplied chart of accounts."""
    reader = _csv_reader(text)
    headers = {str(c or "").strip().lower(): c for c in (reader.fieldnames or [])}
    missing = REQUIRED_JOURNAL_COLUMNS - set(headers)
    if missing:
        raise ValueError("Journal CSV is missing columns: " + ", ".join(sorted(missing)))

    chart_map = {a["account"]: a for a in chart}
    if not chart_map:
        raise ValueError("The Chart of Accounts is empty.")

    rows: list[dict] = []
    errors: list[str] = []
    for line_number, raw in enumerate(reader, start=2):
        if not any(str(v or "").strip() for v in raw.values()):
            continue
        try:
            date_text = str(raw.get(headers["date"], "") or "").strip()
            datetime.strptime(date_text, "%Y-%m-%d")
            entry_id = str(raw.get(headers["entry_id"], "") or "").strip()
            description = str(raw.get(headers["description"], "") or "").strip()
            account = str(raw.get(headers["account"], "") or "").strip()
            debit = money(raw.get(headers["debit"], "0"))
            credit = money(raw.get(headers["credit"], "0"))
        except (ValueError, TypeError) as exc:
            errors.append(f"Line {line_number}: {exc}")
            continue

        if not entry_id or not description or not account:
            errors.append(f"Line {line_number}: date, entry_id, description, and account are required.")
            continue
        if account not in chart_map:
            errors.append(f"Line {line_number}: unknown account '{account}'. Add it to the Chart of Accounts first.")
            continue
        if debit < ZERO or credit < ZERO:
            errors.append(f"Line {line_number}: debit and credit values cannot be negative.")
            continue
        if debit > ZERO and credit > ZERO:
            errors.append(f"Line {line_number}: enter either a debit or a credit, not both.")
            continue
        if debit == ZERO and credit == ZERO:
            errors.append(f"Line {line_number}: a journal line cannot have both debit and credit equal to zero.")
            continue

        rows.append({
            "date": date_text,
            "entry_id": entry_id,
            "description": description,
            "account": account,
            "debit": amount_text(debit),
            "credit": amount_text(credit),
        })

    if errors:
        raise ValueError("The journal file has errors:\n• " + "\n• ".join(errors[:30]) +
                         (f"\n...and {len(errors) - 30} more error(s)." if len(errors) > 30 else ""))
    if not rows:
        raise ValueError("The journal file contains no journal lines.")

    rows.sort(key=lambda r: (r["date"], r["entry_id"], r["account"]))
    validate_journal(rows, chart)
    return rows


def validate_journal(rows: Iterable[dict], chart: Iterable[dict]) -> dict:
    """Validate transaction-level double entry and consistent transaction metadata."""
    chart_map = {a["account"]: a for a in chart}
    totals: dict[str, dict] = defaultdict(lambda: {"debit": ZERO, "credit": ZERO, "dates": set(), "descriptions": set()})
    row_count = 0
    for row in rows:
        row_count += 1
        if row["account"] not in chart_map:
            raise ValueError(f"Unknown account '{row['account']}'. Add it to the Chart of Accounts first.")
        entry_id = str(row.get("entry_id", "")).strip()
        if not entry_id:
            raise ValueError("Every journal line must have an entry ID.")
        try:
            datetime.strptime(str(row.get("date", "")), "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"Entry {entry_id} has an invalid date. Use YYYY-MM-DD.") from exc
        debit, credit = money(row.get("debit", 0)), money(row.get("credit", 0))
        if debit < ZERO or credit < ZERO or (debit > ZERO and credit > ZERO) or (debit == ZERO and credit == ZERO):
            raise ValueError(f"Entry {entry_id}: each line must have one positive debit or credit amount.")
        group = totals[entry_id]
        group["debit"] += debit
        group["credit"] += credit
        group["dates"].add(str(row.get("date", "")))
        group["descriptions"].add(str(row.get("description", "")))
    if row_count == 0:
        raise ValueError("There are no journal lines to process.")

    errors = []
    for entry_id, group in sorted(totals.items()):
        if group["debit"] != group["credit"]:
            errors.append(f"Entry {entry_id}: debits ₹{group['debit']:,.2f} do not equal credits ₹{group['credit']:,.2f}.")
        if len(group["dates"]) != 1 or len(group["descriptions"]) != 1:
            errors.append(f"Entry {entry_id}: all lines in one entry must share the same date and description.")
    if errors:
        raise ValueError("Journal validation failed:\n• " + "\n• ".join(errors[:30]) +
                         (f"\n...and {len(errors) - 30} more error(s)." if len(errors) > 30 else ""))
    return {"valid": True, "line_count": row_count, "transaction_count": len(totals), "total_debits": sum((v["debit"] for v in totals.values()), ZERO), "total_credits": sum((v["credit"] for v in totals.values()), ZERO)}


def _normal_balance(debit_total: Decimal, credit_total: Decimal, side: str) -> Decimal:
    return (debit_total - credit_total) if side == "Debit" else (credit_total - debit_total)


def compute_financials(rows: Iterable[dict], chart: Iterable[dict]) -> dict:
    """Calculate trial balance, Profit & Loss, Balance Sheet and audit metadata."""
    rows = list(rows)
    chart = list(chart)
    validation = validate_journal(rows, chart)
    chart_map = {a["account"]: a for a in chart}
    totals: dict[str, dict[str, Decimal]] = {
        a["account"]: {"debit": ZERO, "credit": ZERO} for a in chart
    }
    for row in rows:
        account = row["account"]
        totals[account]["debit"] += money(row["debit"])
        totals[account]["credit"] += money(row["credit"])

    trial_balance = []
    account_balances = []
    for account in chart:
        name = account["account"]
        debit_total = totals[name]["debit"]
        credit_total = totals[name]["credit"]
        signed = debit_total - credit_total
        debit_balance = max(signed, ZERO)
        credit_balance = max(-signed, ZERO)
        normal = _normal_balance(debit_total, credit_total, account["normal_balance_side"])
        trial_balance.append({
            "account": name, "category": account["category"],
            "total_debits": debit_total, "total_credits": credit_total,
            "debit_balance": debit_balance, "credit_balance": credit_balance,
        })
        account_balances.append({
            "account": name, "category": account["category"],
            "normal_balance_side": account["normal_balance_side"],
            "total_debits": debit_total, "total_credits": credit_total,
            "closing_balance": normal,
        })

    tb_debits = sum((x["debit_balance"] for x in trial_balance), ZERO)
    tb_credits = sum((x["credit_balance"] for x in trial_balance), ZERO)

    income_rows = []
    expense_rows = []
    for account in chart:
        name, category = account["account"], account["category"]
        debit_total, credit_total = totals[name]["debit"], totals[name]["credit"]
        if category == "Income":
            income_rows.append({"account": name, "amount": credit_total - debit_total})
        elif category == "Expense":
            expense_rows.append({"account": name, "amount": debit_total - credit_total})
    total_income = sum((x["amount"] for x in income_rows), ZERO)
    total_expenses = sum((x["amount"] for x in expense_rows), ZERO)
    net_profit = total_income - total_expenses

    current_assets, fixed_assets, contra_assets = [], [], []
    liabilities, equity_accounts = [], []
    for account in chart:
        name, category = account["account"], account["category"]
        debit_total, credit_total = totals[name]["debit"], totals[name]["credit"]
        if category in {"Asset", "Current Asset"}:
            current_assets.append({"account": name, "amount": debit_total - credit_total})
        elif category in {"Non-current Asset", "Fixed Asset"}:
            fixed_assets.append({"account": name, "amount": debit_total - credit_total})
        elif category == "Contra Asset":
            # Display as a negative line item that reduces the related asset balance.
            contra_assets.append({"account": name, "amount": -(credit_total - debit_total)})
        elif category in {"Liability", "Current Liability", "Non-current Liability"}:
            liabilities.append({"account": name, "amount": credit_total - debit_total})
        elif category == "Equity":
            equity_accounts.append({"account": name, "amount": credit_total - debit_total})

    total_current_assets = sum((x["amount"] for x in current_assets), ZERO)
    total_fixed_assets = sum((x["amount"] for x in fixed_assets), ZERO)
    total_contra_assets = sum((x["amount"] for x in contra_assets), ZERO)
    total_assets = total_current_assets + total_fixed_assets + total_contra_assets
    total_liabilities = sum((x["amount"] for x in liabilities), ZERO)
    equity_before_profit = sum((x["amount"] for x in equity_accounts), ZERO)
    total_equity = equity_before_profit + net_profit
    liabilities_and_equity = total_liabilities + total_equity
    balance_sheet_difference = total_assets - liabilities_and_equity

    used_accounts = {row["account"] for row in rows}
    min_date = min(row["date"] for row in rows)
    max_date = max(row["date"] for row in rows)
    return {
        "validation": validation,
        "transaction_count": validation["transaction_count"],
        "line_count": validation["line_count"],
        "min_date": min_date,
        "max_date": max_date,
        "journal_total_debits": validation["total_debits"],
        "journal_total_credits": validation["total_credits"],
        "trial_balance": trial_balance,
        "account_balances": account_balances,
        "trial_balance_debits": tb_debits,
        "trial_balance_credits": tb_credits,
        "trial_balance_difference": tb_debits - tb_credits,
        "income_rows": income_rows,
        "expense_rows": expense_rows,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_profit": net_profit,
        "current_assets": current_assets,
        "fixed_assets": fixed_assets,
        "contra_assets": contra_assets,
        "liabilities": liabilities,
        "equity_accounts": equity_accounts,
        "total_current_assets": total_current_assets,
        "total_fixed_assets": total_fixed_assets,
        "total_contra_assets": total_contra_assets,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "equity_before_profit": equity_before_profit,
        "total_equity": total_equity,
        "liabilities_and_equity": liabilities_and_equity,
        "balance_sheet_difference": balance_sheet_difference,
        "used_accounts": used_accounts,
        "unused_accounts": sorted(set(chart_map) - used_accounts),
    }


def audit_checks(rows: Iterable[dict], chart: Iterable[dict], reports: dict) -> list[dict]:
    """Return assignment-oriented validations. These are checks, not an audit opinion."""
    rows, chart = list(rows), list(chart)
    chart_by_name = {a["account"]: a for a in chart}
    names = list(chart_by_name)
    lower = [(a, a.lower(), chart_by_name[a]["category"]) for a in names]

    def has_name(term: str) -> bool:
        return any(term in n for _, n, _ in lower)

    def count_cat(*cats: str) -> int:
        return sum(1 for a in chart if a["category"] in cats)

    bank_count = sum(1 for _, name, category in lower if "bank" in name and category in {"Asset", "Current Asset"})
    fixed_count = count_cat("Fixed Asset", "Non-current Asset")
    income_count = count_cat("Income")
    expense_count = count_cat("Expense")
    liabilities_with_payable = sum(1 for _, name, category in lower if category in {"Liability", "Current Liability", "Non-current Liability"} and "payable" in name)
    checks = [
        ("At least 50 transactions", reports["transaction_count"] >= 50, f"{reports['transaction_count']} transaction(s) found; assignment minimum is 50."),
        ("Journal entries balance", reports["journal_total_debits"] == reports["journal_total_credits"], f"Debits ₹{reports['journal_total_debits']:,.2f}; credits ₹{reports['journal_total_credits']:,.2f}."),
        ("Trial Balance balances", abs(reports["trial_balance_difference"]) <= CENT, f"Difference: ₹{reports['trial_balance_difference']:,.2f}."),
        ("Balance Sheet balances", abs(reports["balance_sheet_difference"]) <= CENT, f"Assets ₹{reports['total_assets']:,.2f}; liabilities + equity ₹{reports['liabilities_and_equity']:,.2f}; difference ₹{reports['balance_sheet_difference']:,.2f}."),
        ("Every chart account has activity", len(reports["unused_accounts"]) == 0, f"{len(reports['used_accounts'])} of {len(chart)} chart account(s) used."),
        ("Cash account", has_name("cash"), "Account name should identify cash on hand."),
        ("At least two bank accounts", bank_count >= 2, f"{bank_count} bank account(s) identified."),
        ("At least three fixed assets", fixed_count >= 3, f"{fixed_count} fixed/non-current asset account(s) identified."),
        ("Depreciation recorded", any("depreciation" in n and cat == "Expense" for _, n, cat in lower) and any("depreciation" in n and cat == "Contra Asset" for _, n, cat in lower), "Looks for a depreciation expense and an accumulated depreciation/contra-asset account."),
        ("Prepaid expense", has_name("prepaid"), "Looks for an account with 'prepaid' in its name."),
        ("Payable", liabilities_with_payable >= 1, f"{liabilities_with_payable} payable account(s) identified."),
        ("Salaries", any("salary" in n or "salaries" in n for _, n, _ in lower), "Looks for a salary/salaries account."),
        ("Receivables", has_name("receivable"), "Looks for an account with 'receivable' in its name."),
        ("Loans given and availed", has_name("loan") and (has_name("loan given") or has_name("loans given")) and any("loan" in n and cat in {"Liability", "Current Liability", "Non-current Liability"} for _, n, cat in lower), "Looks for a loan asset and a loan liability."),
        ("Inventory", has_name("inventory"), "Looks for an inventory account."),
        ("GST input credit", any("gst" in n and ("input" in n or "credit" in n) for _, n, _ in lower), "Looks for GST Input Credit or a similarly named account."),
        ("At least three income types", income_count >= 3, f"{income_count} account(s) classified as Income."),
        ("At least five expense types", expense_count >= 5, f"{expense_count} account(s) classified as Expense."),
    ]
    return [{"check": title, "status": "PASS" if passed else "REVIEW", "passed": bool(passed), "details": details} for title, passed, details in checks]
