# LedgerLab — Flask Accounting Website

LedgerLab is an educational double-entry accounting web application built with Python Flask, HTML, CSS, and JavaScript. It loads a 75-transaction sample company by default, lets users edit/add transactions or upload a different CSV, generates the financial statements, and offers downloadable reports.

## Features

- Starts with the included `journal_entries.csv` demo dataset (75 transactions / 210 journal lines).
- Editable journal grouped by transaction, plus a form for creating a standard two-line transaction.
- CSV upload for a new journal; optionally upload a custom Chart of Accounts CSV to support new account names.
- Add accounts using the Chart of Accounts page without editing Python code.
- Generates Trial Balance, account balances, Profit & Loss, Balance Sheet, and assignment-oriented audit checks.
- Downloads individual CSV reports or one ZIP report pack.
- Checks transaction-level debit/credit equality, Trial Balance equality, Balance Sheet equality, account coverage, and key assignment requirements.
- Responsive website layout for laptop and mobile screens.
- Includes a Render `Procfile` and `render.yaml` for deployment.

## Run locally on Windows

1. Install Python 3.10 or newer from https://www.python.org/downloads/.
2. Extract the project ZIP into a folder.
3. Open Command Prompt or the terminal in VS Code in that folder.
4. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

5. Start the website:

   ```bash
   python app.py
   ```

6. Open http://127.0.0.1:5000 in your browser.

On Windows, you can alternatively run `install_dependencies.bat` once and then launch the app with `run_ledgerlab.bat`. If `python` is not recognised, use `py` in place of `python`.

## Deployment using GitHub + Render

1. Create a GitHub repository and upload the contents of this folder. Include `app.py`, `accounting_engine.py`, `templates/`, `static/`, `journal_entries.csv`, `chart_of_accounts.csv`, `requirements.txt`, `Procfile`, and `render.yaml`.
2. Sign in to https://render.com/ and create a new **Blueprint** from that repository, or create a Python web service using the included Procfile.
3. Ensure the start command is:

   ```bash
   gunicorn --workers 1 --threads 4 app:app
   ```

4. Set a strong `SECRET_KEY` environment variable. The included `render.yaml` asks Render to generate one when supported by the chosen deployment flow.
5. Deploy, wait for the build to complete, then open the HTTPS URL provided by Render.
6. Test the public app with demo data and one small CSV before sharing the link with your professor.

## Journal CSV format

The uploaded journal needs these columns (column names are case-insensitive):

```text
date,entry_id,description,account,debit,credit
2025-04-01,JE001,Owner investment,Cash,100000.00,0.00
2025-04-01,JE001,Owner investment,Owner's Capital,0.00,100000.00
```

Rules:

- Date format: `YYYY-MM-DD`.
- Account names must exactly match names in the active Chart of Accounts.
- A transaction uses one `entry_id` across its journal lines; all lines with that ID must have the same date and description.
- Each transaction's debit total must equal its credit total.
- Each line must have a non-negative amount on exactly one side (debit or credit), and not zero on both sides.
- Use numeric amounts without a currency symbol. Decimal values are supported.
- When editing existing transactions in the browser, change account-level debits/credits and use the transaction header to change date, ID, or description for the entire transaction.

## Custom Chart of Accounts CSV format

To use new account names in an uploaded journal, upload a chart CSV with the following columns:

```text
account,category,normal_balance_side
Cash,Asset,Debit
Office Equipment,Fixed Asset,Debit
Accumulated Depreciation - Office Equipment,Contra Asset,Credit
Sales Revenue,Income,Credit
Electricity Expense,Expense,Debit
```

Supported categories:

- `Asset`, `Current Asset`, `Non-current Asset`, `Fixed Asset`, `Contra Asset`
- `Liability`, `Current Liability`, `Non-current Liability`, `Equity`, `Income`, `Expense`

Normal sides are category-checked: asset/fixed asset/expense accounts normally use Debit; contra-assets/liabilities/equity/income normally use Credit. Use a custom chart if the uploaded journal includes accounts outside the current chart.

You can also add one account from the Chart of Accounts page. The account will be available in the current browser workspace and for subsequent transactions/uploads, provided you don't replace it with a CSV without the matching custom chart.

## Output reports

- `journal_entries.csv`
- `chart_of_accounts.csv`
- `trial_balance.csv`
- `account_balances.csv`
- `profit_and_loss.csv`
- `balance_sheet.csv`
- `audit_checks.csv`
- `ledgerlab_reports.zip` with all of the above

## Important assumptions and limitations

- The supplied demo is for the academic assignment, not a statutory accounting system.
- GST is shown in separate input-credit and output-payable accounts. The app does not calculate GST rates, tax eligibility, filing liability, or statutory returns.
- Depreciation is recorded through the journal entries. The app does not calculate depreciation schedules automatically.
- Net profit/loss is shown as current-period equity to test the Balance Sheet equation; this is a reporting presentation, not a year-end closing journal.
- A balanced journal can still contain accounting mistakes. The software checks mathematical balance and some assignment criteria, not the economic validity of each transaction.
- The current workspace is stored in the web worker's memory for the browser session. It is a demo implementation, not durable cloud storage. Download your changed journal and reports before leaving or when finished. A service restart can reset in-session changes. Render is configured to use one worker so session state remains consistent within that running service.
- The software supports CSV, not arbitrary Excel, bank statement, invoice, or PDF formats. Convert them to the documented journal structure first.
- Do not upload sensitive or real customer/financial information to a public demonstration website.

## Demo dataset results

The included sample currently has:

- 75 transactions and 210 journal lines
- Journal debits: ₹35,79,914.00
- Journal credits: ₹35,79,914.00
- Total income: ₹6,44,000.00
- Total expenses: ₹5,92,350.00
- Net profit: ₹51,650.00
- Total assets: ₹8,97,250.00
- Total liabilities and equity: ₹8,97,250.00
- Balance Sheet difference: ₹0.00

All results are recalculated from the active dataset, not hard-coded into the dashboard.
