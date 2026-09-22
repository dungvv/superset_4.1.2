#!/usr/bin/env python3
"""Export Elasticsearch metrics to Excel file."""
import json
import sys
from datetime import datetime

try:
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
except ImportError:
    print("Installing openpyxl...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side


SERVICE_MAP = {
    "/mobileservice/api/v3/auth/login": "LOGIN",
    "/api/bccs/v1.0/partner/topup/payment": "TOPUP_PARTNER",
    "/services/bccs/api/bccs/v1.0/partner/topup/payment": "TOPUP_PARTNER",
    "/mobileservice/api/v3/transfer/lapnet/confirm": "W2BLAPNET",
    "/mobileservice/api/miniapp/transfer/lapnet/confirm": "W2BLAPNET",
    "/services/utilitiesconnector/api/v3/lapnet/transfer": "B2WLAPNET",
    "/mobileservice/api/v3/topup/confirm": "TOPUP_TELCO",
    "/mobileservice/api/miniapp/topup/confirm": "TOPUP_TELCO",
    "/mobileservice/api/v3/transfer/umoney/confirm": "TRANSFER_UMONEY",
    "/mobileservice/api/miniapp/transfer/umoney/confirm": "TRANSFER_UMONEY",
    "/mobileservice/api/v3/data/package/confirm": "DATA_UMONEY",
    "/mobileservice/api/v3/partner/electricity/confirm": "PAYMENT_ELECTRIC",
    "/mobileservice/api/v3/internetPayment/confirm": "PAYMENT_FTTH",
    "/mobileservice/api/v3/saleman/data/confirm": "SALEMAN_DATA",
    "/mobileservice/api/miniapp/saleman/data/confirm": "SALEMAN_DATA",
    "/mobileservice/api/v3/savings/validateOpenSavingsAccount": "SAVINGS_OPEN",
    "/mobileservice/api/v3/savings/confirmOpenSavingAccount": "SAVINGS_OPEN",
    "/mobileservice/api/v3/savings/settlementManual": "SAVINGS_SETTLEMENT",
}


def parse_es_response(data: dict) -> list[dict]:
    """Parse Elasticsearch aggregation response."""
    rows = []
    buckets = data.get("aggregations", {}).get("by_endpoint", {}).get("buckets", [])
    
    for bucket in buckets:
        endpoint = bucket["key"]
        service_type = SERVICE_MAP.get(endpoint, "UNKNOWN")
        
        total = bucket["doc_count"]
        success = bucket["success_count"]["doc_count"]
        failure = bucket["failure_count"]["doc_count"]
        success_rate = round(success / total * 100, 2) if total > 0 else 0
        
        stats = bucket["duration_stats"]
        pcts = bucket["duration_percentiles"]["values"]
        
        rows.append({
            "service_type": service_type,
            "endpoint": endpoint,
            "total": total,
            "success": success,
            "failure": failure,
            "success_rate": success_rate,
            "min_ms": stats.get("min"),
            "max_ms": stats.get("max"),
            "avg_ms": round(stats.get("avg", 0), 2),
            "p95_ms": round(pcts.get("95.0", 0), 2),
            "p99_ms": round(pcts.get("99.0", 0), 2),
        })
    
    # Sort by service_type then endpoint
    rows.sort(key=lambda x: (x["service_type"], x["endpoint"]))
    return rows


def create_excel(rows: list[dict], output_path: str):
    """Create Excel file from parsed data."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Endpoint Metrics"
    
    # Headers
    headers = [
        "Service Type",
        "Endpoint",
        "Total",
        "Success",
        "Failure",
        "Success Rate (%)",
        "Min (ms)",
        "Max (ms)",
        "Avg (ms)",
        "P95 (ms)",
        "P99 (ms)",
    ]
    
    # Style
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    
    # Write headers
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
    
    # Write data
    for row_idx, row_data in enumerate(rows, 2):
        ws.cell(row=row_idx, column=1, value=row_data["service_type"])
        ws.cell(row=row_idx, column=2, value=row_data["endpoint"])
        ws.cell(row=row_idx, column=3, value=row_data["total"])
        ws.cell(row=row_idx, column=4, value=row_data["success"])
        ws.cell(row=row_idx, column=5, value=row_data["failure"])
        ws.cell(row=row_idx, column=6, value=row_data["success_rate"])
        ws.cell(row=row_idx, column=7, value=row_data["min_ms"])
        ws.cell(row=row_idx, column=8, value=row_data["max_ms"])
        ws.cell(row=row_idx, column=9, value=row_data["avg_ms"])
        ws.cell(row=row_idx, column=10, value=row_data["p95_ms"])
        ws.cell(row=row_idx, column=11, value=row_data["p99_ms"])
        
        # Apply border and alignment
        for col in range(1, 12):
            cell = ws.cell(row=row_idx, column=col)
            cell.border = thin_border
            if col >= 3:
                cell.alignment = Alignment(horizontal="right")
    
    # Column widths
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 55
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 12
    ws.column_dimensions["F"].width = 15
    ws.column_dimensions["G"].width = 12
    ws.column_dimensions["H"].width = 12
    ws.column_dimensions["I"].width = 12
    ws.column_dimensions["J"].width = 12
    ws.column_dimensions["K"].width = 12
    
    # Freeze header row
    ws.freeze_panes = "A2"
    
    wb.save(output_path)
    print(f"Excel file saved to: {output_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python export_metrics_to_excel.py <es_response.json> [output.xlsx]")
        print("Or pipe JSON directly: cat response.json | python export_metrics_to_excel.py")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else f"endpoint_metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    rows = parse_es_response(data)
    create_excel(rows, output_file)
    
    # Print summary
    print(f"\nSummary:")
    print(f"  Total endpoints: {len(rows)}")
    print(f"  Total requests: {sum(r['total'] for r in rows):,}")
    print(f"  Total success: {sum(r['success'] for r in rows):,}")
    print(f"  Total failure: {sum(r['failure'] for r in rows):,}")


if __name__ == "__main__":
    main()
