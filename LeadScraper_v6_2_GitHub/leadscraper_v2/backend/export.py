"""CSV + XLSX export of job leads (blueprint: export.py)."""
import csv
import io

# NOTE: openpyxl is imported lazily inside export_xlsx — it is only needed
# when the user downloads an Excel file, never at server startup.

COLUMNS = [
    ("name", "Name"),
    ("address", "Address"),
    ("phone", "Phone"),
    ("website", "Website"),
    ("rating", "Rating"),
    ("review_count", "Reviews"),
    ("types", "Types"),
    ("enrichment_status", "Enrichment Tier"),
    ("company_size", "Company Size"),
    ("company_industry", "Company Industry"),
    ("decision_maker_name", "Decision Maker"),
    ("decision_maker_title", "DM Title"),
    ("decision_maker_email", "DM Email"),
    ("email_status", "Email Status"),
    ("pitch", "AI Pitch"),
    ("lead_score", "Lead Score"),
]


def _rows(leads: list) -> list[list]:
    rows = []
    for lead in leads:
        rows.append([getattr(lead, key, "") if getattr(lead, key, "") is not None else "" for key, _ in COLUMNS])
    return rows


def export_csv(leads: list) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in COLUMNS])
    writer.writerows(_rows(leads))
    return buf.getvalue().encode("utf-8-sig")  # BOM for Excel


def export_xlsx(leads: list) -> bytes:
    import openpyxl  # lazy: only needed for Excel downloads

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append([label for _, label in COLUMNS])
    for row in _rows(leads):
        ws.append(row)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 22
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
