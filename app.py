"""LedgerLab - a small Flask accounting web application for an academic project.

Run locally:
    python -m pip install -r requirements.txt
    python -m flask --app app run --debug

For Render, the included Procfile runs: gunicorn app:app
"""
from __future__ import annotations

import csv
import io
import os
import secrets
import zipfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import hmac
from decimal import Decimal

from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename

from accounting_engine import (
    ALLOWED_CATEGORIES,
    ALLOWED_NORMAL_SIDES,
    amount_text,
    audit_checks,
    chart_to_csv,
    compute_financials,
    parse_chart_csv_text,
    parse_journal_csv_text,
    validate_journal,
)

BASE_DIR = Path(__file__).resolve().parent
DEMO_JOURNAL_PATH = BASE_DIR / "journal_entries.csv"
DEMO_CHART_PATH = BASE_DIR / "chart_of_accounts.csv"
PAGE_SIZE = 8

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload limit
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Demo app stores each browser session's active dataset in memory. On free/demo hosting,
# uploaded data is not durable and may reset if the service restarts.
WORKSPACES: dict[str, dict] = {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _load_demo() -> dict:
    chart = parse_chart_csv_text(_read_text(DEMO_CHART_PATH))
    rows = parse_journal_csv_text(_read_text(DEMO_JOURNAL_PATH), chart)
    return {
        "rows": rows,
        "chart": chart,
        "source_name": "Demo dataset — Campus Office Supplies & Services",
        "is_demo": True,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_workspace() -> dict:
    workspace_id = session.get("workspace_id")
    if not workspace_id or workspace_id not in WORKSPACES:
        workspace_id = uuid4().hex
        WORKSPACES[workspace_id] = _load_demo()
        session["workspace_id"] = workspace_id
    return WORKSPACES[workspace_id]


def set_workspace(data: dict) -> None:
    workspace_id = session.get("workspace_id")
    if not workspace_id:
        get_workspace()
        workspace_id = session["workspace_id"]
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    WORKSPACES[workspace_id] = data


def fmt_money(value) -> str:
    try:
        number = Decimal(str(value))
        if number < 0:
            return f"−₹{abs(number):,.2f}"
        return f"₹{number:,.2f}"
    except Exception:
        return str(value)


def fmt_amount(value) -> str:
    return f"{Decimal(str(value)):,.2f}"


@app.template_filter("money")
def money_filter(value):
    return fmt_money(value)


@app.template_filter("amount")
def amount_filter(value):
    return fmt_amount(value)


def get_data() -> tuple[dict, dict, list[dict]]:
    ws = get_workspace()
    reports = compute_financials(ws["rows"], ws["chart"])
    checks = audit_checks(ws["rows"], ws["chart"], reports)
    return ws, reports, checks


def transaction_groups(rows: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for idx, row in enumerate(rows):
        key = row["entry_id"]
        if key not in grouped:
            grouped[key] = {
                "entry_id": key,
                "date": row["date"],
                "description": row["description"],
                "lines": [],
            }
        line = dict(row)
        line["index"] = idx
        grouped[key]["lines"].append(line)
    return list(grouped.values())


def csv_bytes(headers: list[str], rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        clean = {}
        for key in headers:
            value = row.get(key, "")
            if isinstance(value, Decimal):
                value = f"{value:.2f}"
            elif isinstance(value, set):
                value = "; ".join(sorted(value))
            clean[key] = value
        writer.writerow(clean)
    return output.getvalue().encode("utf-8-sig")


def export_tables(ws: dict, reports: dict, checks: list[dict]) -> dict[str, bytes]:
    journal_headers = ["date", "entry_id", "description", "account", "debit", "credit"]
    journal = csv_bytes(journal_headers, ws["rows"])
    chart = chart_to_csv(ws["chart"]).encode("utf-8-sig")

    tb_headers = ["account", "category", "total_debits", "total_credits", "debit_balance", "credit_balance"]
    tb = csv_bytes(tb_headers, reports["trial_balance"])
    balance_headers = ["account", "category", "normal_balance_side", "total_debits", "total_credits", "closing_balance"]
    balances = csv_bytes(balance_headers, reports["account_balances"])

    pl_rows = []
    for item in reports["income_rows"]:
        pl_rows.append({"section": "Income", "account": item["account"], "amount": item["amount"]})
    pl_rows.extend([
        {"section": "Total income", "account": "", "amount": reports["total_income"]},
    ])
    for item in reports["expense_rows"]:
        pl_rows.append({"section": "Expenses", "account": item["account"], "amount": item["amount"]})
    pl_rows.extend([
        {"section": "Total expenses", "account": "", "amount": reports["total_expenses"]},
        {"section": "Net profit / (loss)", "account": "", "amount": reports["net_profit"]},
    ])
    pl = csv_bytes(["section", "account", "amount"], pl_rows)

    bs_rows = []
    for section_key, section_label in [
        ("current_assets", "Current assets"),
        ("fixed_assets", "Fixed assets"),
        ("contra_assets", "Less: accumulated depreciation / contra assets"),
    ]:
        for item in reports[section_key]:
            bs_rows.append({"section": section_label, "account": item["account"], "amount": item["amount"]})
    bs_rows.extend([
        {"section": "Total assets", "account": "", "amount": reports["total_assets"]},
    ])
    for item in reports["liabilities"]:
        bs_rows.append({"section": "Liabilities", "account": item["account"], "amount": item["amount"]})
    for item in reports["equity_accounts"]:
        bs_rows.append({"section": "Equity", "account": item["account"], "amount": item["amount"]})
    bs_rows.extend([
        {"section": "Current-period profit / (loss)", "account": "", "amount": reports["net_profit"]},
        {"section": "Total liabilities and equity", "account": "", "amount": reports["liabilities_and_equity"]},
        {"section": "Balance Sheet difference", "account": "", "amount": reports["balance_sheet_difference"]},
    ])
    bs = csv_bytes(["section", "account", "amount"], bs_rows)
    audit = csv_bytes(["check", "status", "details"], checks)
    return {
        "journal_entries.csv": journal,
        "chart_of_accounts.csv": chart,
        "trial_balance.csv": tb,
        "account_balances.csv": balances,
        "profit_and_loss.csv": pl,
        "balance_sheet.csv": bs,
        "audit_checks.csv": audit,
    }


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.before_request
def protect_state_changes():
    if request.method == "POST" and request.endpoint != "static":
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not submitted or not hmac.compare_digest(submitted, expected):
            abort(400, description="Your session token is missing or expired. Refresh the page and try again.")


@app.context_processor
def inject_globals():
    return {
        "csrf_token": csrf_token,
        "app_name": "LedgerLab",
        "current_endpoint": request.endpoint,
        "categories": sorted(ALLOWED_CATEGORIES),
        "normal_sides": sorted(ALLOWED_NORMAL_SIDES),
        "now_year": datetime.now().year,
        "today_date": datetime.now().strftime("%Y-%m-%d"),
    }


@app.route("/")
def dashboard():
    ws, reports, checks = get_data()
    income_sorted = sorted(reports["income_rows"], key=lambda x: x["amount"], reverse=True)
    expense_sorted = sorted(reports["expense_rows"], key=lambda x: x["amount"], reverse=True)
    max_income = max([float(x["amount"]) for x in income_sorted] + [1])
    max_expense = max([float(x["amount"]) for x in expense_sorted] + [1])
    return render_template(
        "dashboard.html", ws=ws, r=reports, checks=checks,
        income_sorted=income_sorted, expense_sorted=expense_sorted,
        max_income=max_income, max_expense=max_expense,
    )


@app.route("/transactions", methods=["GET", "POST"])
def transactions():
    ws = get_workspace()
    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "add":
            date_text = request.form.get("new_date", "").strip()
            description = request.form.get("new_description", "").strip()
            entry_id = request.form.get("new_entry_id", "").strip()
            debit_account = request.form.get("new_debit_account", "").strip()
            credit_account = request.form.get("new_credit_account", "").strip()
            amount = request.form.get("new_amount", "").strip()
            try:
                if not entry_id:
                    existing = {g["entry_id"] for g in transaction_groups(ws["rows"])}
                    serial = len(existing) + 1
                    entry_id = f"JE{serial:03d}"
                    while entry_id in existing:
                        serial += 1
                        entry_id = f"JE{serial:03d}"
                if entry_id in {g["entry_id"] for g in transaction_groups(ws["rows"])}:
                    raise ValueError(f"Entry ID '{entry_id}' already exists. Use a new ID.")
                amount_value = Decimal(amount)
                if amount_value <= 0:
                    raise ValueError("Amount must be greater than zero.")
                candidate = deepcopy(ws["rows"])
                candidate.extend([
                    {"date": date_text, "entry_id": entry_id, "description": description,
                     "account": debit_account, "debit": amount_text(amount_value), "credit": "0.00"},
                    {"date": date_text, "entry_id": entry_id, "description": description,
                     "account": credit_account, "debit": "0.00", "credit": amount_text(amount_value)},
                ])
                candidate = parse_journal_csv_text(
                    _rows_to_csv(candidate), ws["chart"]
                )
                ws["rows"] = candidate
                ws["source_name"] = "Edited dataset"
                ws["is_demo"] = False
                set_workspace(ws)
                flash(f"Transaction {entry_id} added. Financial statements have been recalculated.", "success")
                return redirect(url_for("transactions"))
            except Exception as exc:
                flash(str(exc), "error")
                return redirect(url_for("transactions"))

        if action == "save":
            try:
                rows_copy = deepcopy(ws["rows"])
                groups = transaction_groups(ws["rows"])
                page = max(0, int(request.form.get("page", "0")))
                visible_groups = groups[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
                new_ids = []
                for g_index, group in enumerate(groups):
                    if group not in visible_groups:
                        new_ids.append(group["entry_id"])
                        continue
                    # Header metadata is transaction-level, so date/description stay consistent across its lines.
                    posted_group_index = g_index
                    new_id = request.form.get(f"group_entry_id_{posted_group_index}", group["entry_id"]).strip()
                    new_date = request.form.get(f"group_date_{posted_group_index}", group["date"]).strip()
                    new_description = request.form.get(f"group_description_{posted_group_index}", group["description"]).strip()
                    if not new_id or not new_description:
                        raise ValueError("Every transaction needs an entry ID and description.")
                    new_ids.append(new_id)
                    for line in group["lines"]:
                        idx = line["index"]
                        rows_copy[idx]["entry_id"] = new_id
                        rows_copy[idx]["date"] = new_date
                        rows_copy[idx]["description"] = new_description
                        rows_copy[idx]["account"] = request.form.get(f"account_{idx}", line["account"]).strip()
                        rows_copy[idx]["debit"] = request.form.get(f"debit_{idx}", line["debit"]).strip() or "0"
                        rows_copy[idx]["credit"] = request.form.get(f"credit_{idx}", line["credit"]).strip() or "0"
                if len(set(new_ids)) != len(new_ids):
                    raise ValueError("Each transaction must have a unique Entry ID. One of the IDs is duplicated.")
                candidate = parse_journal_csv_text(_rows_to_csv(rows_copy), ws["chart"])
                ws["rows"] = candidate
                ws["source_name"] = "Edited dataset"
                ws["is_demo"] = False
                set_workspace(ws)
                flash("Changes saved. All reports have been recalculated.", "success")
            except Exception as exc:
                flash(str(exc), "error")
            page = max(0, int(request.form.get("page", "0")))
            return redirect(url_for("transactions", page=page))

    groups = transaction_groups(ws["rows"])
    pages = max(1, (len(groups) + PAGE_SIZE - 1) // PAGE_SIZE)
    try:
        page = int(request.args.get("page", "0"))
    except ValueError:
        page = 0
    page = min(max(page, 0), pages - 1)
    visible_groups = groups[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    return render_template(
        "transactions.html", ws=ws, groups=visible_groups, all_groups=groups,
        page=page, pages=pages, page_start=page * PAGE_SIZE, chart=ws["chart"],
        total_lines=len(ws["rows"]), total_transactions=len(groups),
    )


def _rows_to_csv(rows: list[dict]) -> str:
    out = io.StringIO(newline="")
    fields = ["date", "entry_id", "description", "account", "debit", "credit"]
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fields})
    return out.getvalue()


@app.route("/upload", methods=["GET", "POST"])
def upload():
    ws = get_workspace()
    if request.method == "POST":
        journal_file = request.files.get("journal_file")
        chart_file = request.files.get("chart_file")
        if not journal_file or not journal_file.filename:
            flash("Select a journal CSV file to upload.", "error")
            return redirect(url_for("upload"))
        try:
            journal_bytes = journal_file.read()
            try:
                journal_text = journal_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                journal_text = journal_bytes.decode("cp1252")
            if chart_file and chart_file.filename:
                chart_bytes = chart_file.read()
                try:
                    chart_text = chart_bytes.decode("utf-8-sig")
                except UnicodeDecodeError:
                    chart_text = chart_bytes.decode("cp1252")
                chart = parse_chart_csv_text(chart_text)
            else:
                chart = ws["chart"]
            rows = parse_journal_csv_text(journal_text, chart)
            # The CSV must have unique IDs per transaction, not reuse an ID for two separate transactions.
            ws_new = {
                "rows": rows,
                "chart": chart,
                "source_name": secure_filename(journal_file.filename) or "Uploaded journal",
                "is_demo": False,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            set_workspace(ws_new)
            flash(f"Uploaded {len(rows)} journal line(s) across {len({r['entry_id'] for r in rows})} transaction(s).", "success")
            return redirect(url_for("dashboard"))
        except UnicodeDecodeError:
            flash("Could not read the file as UTF-8 CSV. Save it as CSV UTF-8 and try again.", "error")
        except Exception as exc:
            flash(str(exc), "error")
    return render_template("upload.html", ws=ws)


@app.route("/accounts", methods=["GET", "POST"])
def accounts():
    ws = get_workspace()
    if request.method == "POST":
        account = request.form.get("account", "").strip()
        category = request.form.get("category", "").strip()
        side = request.form.get("normal_balance_side", "").strip().title()
        try:
            if not account:
                raise ValueError("Enter an account name.")
            if any(a["account"].casefold() == account.casefold() for a in ws["chart"]):
                raise ValueError(f"Account '{account}' already exists.")
            if category not in ALLOWED_CATEGORIES:
                raise ValueError("Select a valid account category.")
            if side not in ALLOWED_NORMAL_SIDES:
                raise ValueError("Select Debit or Credit as the normal balance side.")
            expected_side = "Credit" if category in {"Contra Asset", "Liability", "Current Liability", "Non-current Liability", "Equity", "Income"} else "Debit"
            if side != expected_side:
                raise ValueError(f"An account classified as {category} normally has a {expected_side} balance.")
            candidate_chart = deepcopy(ws["chart"])
            candidate_chart.append({"account": account, "category": category, "normal_balance_side": side})
            # A new account may not yet have journal activity, which is allowed.
            ws["chart"] = candidate_chart
            ws["source_name"] = "Custom chart of accounts"
            ws["is_demo"] = False
            set_workspace(ws)
            flash(f"Account '{account}' added to this workspace's Chart of Accounts.", "success")
            return redirect(url_for("accounts"))
        except Exception as exc:
            flash(str(exc), "error")
    used = {r["account"] for r in ws["rows"]}
    return render_template("accounts.html", ws=ws, used=used)


@app.route("/reports/trial-balance")
def trial_balance_report():
    ws, reports, checks = get_data()
    return render_template("trial_balance.html", ws=ws, r=reports)


@app.route("/reports/profit-and-loss")
def profit_and_loss_report():
    ws, reports, checks = get_data()
    return render_template("profit_and_loss.html", ws=ws, r=reports)


@app.route("/reports/balance-sheet")
def balance_sheet_report():
    ws, reports, checks = get_data()
    return render_template("balance_sheet.html", ws=ws, r=reports)


@app.route("/audit")
def audit():
    ws, reports, checks = get_data()
    return render_template("audit.html", ws=ws, r=reports, checks=checks)


@app.route("/reset", methods=["POST"])
def reset_demo():
    workspace_id = session.get("workspace_id")
    if workspace_id:
        WORKSPACES[workspace_id] = _load_demo()
    flash("Restored the original demo dataset for this browser session.", "success")
    return redirect(url_for("dashboard"))


@app.route("/export/<report_name>")
def export_report(report_name: str):
    ws, reports, checks = get_data()
    tables = export_tables(ws, reports, checks)
    if report_name == "all.zip":
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename, content in tables.items():
                archive.writestr(filename, content)
            archive.writestr("README.txt", (
                "LedgerLab financial report export\n\n"
                f"Source: {ws['source_name']}\n"
                f"Reporting period covered by journal: {reports['min_date']} to {reports['max_date']}\n"
                f"Transactions: {reports['transaction_count']}\n"
                "Accounting assumptions: category-based educational reports; no tax or statutory advice.\n"
                "The Balance Sheet and Trial Balance checks are included in audit_checks.csv.\n"
            ))
        stream.seek(0)
        return send_file(stream, mimetype="application/zip", as_attachment=True, download_name="ledgerlab_reports.zip")
    filename = report_name if report_name.endswith(".csv") else report_name + ".csv"
    if filename not in tables:
        abort(404)
    return send_file(io.BytesIO(tables[filename]), mimetype="text/csv", as_attachment=True, download_name=filename)


@app.errorhandler(413)
def too_large(_error):
    flash("The upload is too large. Maximum supported file size is 10 MB.", "error")
    return redirect(url_for("upload"))


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


if __name__ == "__main__":
    # Use debug=True only for local development. Production hosting uses the Procfile.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("FLASK_DEBUG") == "1")
