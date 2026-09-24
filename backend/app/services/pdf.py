from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def create_offer_pdf(offer: dict, candidate: dict, job: dict | None = None) -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("NovaTitle", parent=styles["Title"], textColor=colors.HexColor("#123B4A"), spaceAfter=14)
    body = ParagraphStyle("NovaBody", parent=styles["BodyText"], fontSize=10, leading=15)
    story = [Paragraph("NOVATECH SOLUTIONS", title), Paragraph("Employment Offer Letter", styles["Heading2"]), Spacer(1, 8), Paragraph(f"Dear {candidate.get('full_name', 'Candidate')},", body), Spacer(1, 8)]
    story.append(Paragraph("We are pleased to offer you employment with NovaTech Solutions. This offer is subject to the terms below and any applicable company policies.", body))
    story.append(Spacer(1, 14))
    rows = [["Offer code", str(offer.get("offer_code", ""))], ["Position", str((job or {}).get("title", "NovaTech Solutions role"))], ["Salary", f"{offer.get('currency', 'PKR')} {offer.get('salary', '')}"], ["Joining date", str(offer.get("joining_date", ""))], ["Probation", f"{offer.get('probation_months', 3)} months"], ["Offer expiry", str(offer.get("expiry_date", ""))]]
    table = Table(rows, colWidths=[42 * mm, 112 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E8F1F3")), ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#17313B")), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B7C9CE")), ("PADDING", (0, 0), (-1, -1), 8)]))
    story.extend([table, Spacer(1, 18), Paragraph("Please review this offer through your secure candidate portal. Contact the NovaTech Solutions hiring team with any questions.", body), Spacer(1, 22), Paragraph("NovaTech Solutions Human Resources", body)])
    document.build(story)
    return output.getvalue()


def create_analytics_pdf(metrics: dict) -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("ReportTitle", parent=styles["Title"], textColor=colors.HexColor("#123B4A"), spaceAfter=14)
    story = [Paragraph("NOVATECH SOLUTIONS", title), Paragraph("Recruitment Analytics Report", styles["Heading2"]), Spacer(1, 12)]
    rows = [["Metric", "Value"], ["Applications", str(metrics.get("applications_total", 0))], ["Interviews", str(metrics.get("interviews_total", 0))], ["Offers", str(metrics.get("offers_total", 0))]]
    rows.extend([[f"Applications: {key}", str(value)] for key, value in sorted(metrics.get("by_status", {}).items())])
    table = Table(rows, colWidths=[110 * mm, 44 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123B4A")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B7C9CE")), ("PADDING", (0, 0), (-1, -1), 8)]))
    story.append(table)
    document.build(story)
    return output.getvalue()