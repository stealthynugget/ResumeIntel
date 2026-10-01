"""Deterministic, source-checked findings for a saved match run."""

import json
import re
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


INK = colors.HexColor("#1d2c29")
MUTED = colors.HexColor("#53645f")
GREEN = colors.HexColor("#176b53")
LINE = colors.HexColor("#d7e1db")
PALE = colors.HexColor("#f1f6f2")


def _font_names():
    regular = Path("C:/Windows/Fonts/arial.ttf")
    bold = Path("C:/Windows/Fonts/arialbd.ttf")
    if regular.is_file() and bold.is_file():
        if "RI-Arial" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("RI-Arial", str(regular)))
            pdfmetrics.registerFont(TTFont("RI-Arial-Bold", str(bold)))
        return "RI-Arial", "RI-Arial-Bold"
    return "Helvetica", "Helvetica-Bold"


def _safe(value, limit=600):
    """Escape paragraph syntax and suppress contact details in generated findings."""
    text = str(value or "")
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[contact redacted]", text)
    text = re.sub(r"(?:\+?\d[\d\s().-]{8,}\d)", "[contact redacted]", text)
    text = " ".join(text.split())[:limit]
    return escape(text)


def _excerpt(db, candidate_id, assessment):
    span_id = assessment.get("span_id")
    quote = assessment.get("quote")
    if not span_id or not quote:
        return None
    row = db.execute("SELECT text FROM spans WHERE id=? AND candidate_id=?", (span_id, candidate_id)).fetchone()
    if not row or quote not in row["text"]:
        return None
    text = row["text"]
    start = text.find(quote)
    low = max(0, start - 58)
    high = min(len(text), start + len(quote) + 85)
    if low:
        boundary = text.rfind(" ", max(0, low - 24), low + 1)
        if boundary >= 0:
            low = boundary + 1
    if high < len(text):
        boundary = text.find(" ", high, min(len(text), high + 24))
        if boundary >= 0:
            high = boundary
    excerpt = text[low:high].strip()
    # Keep only safe, contiguous source text; no redaction inside a purported exact excerpt.
    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?\d[\d\s().-]{8,}\d)", excerpt):
        return None
    return excerpt


def render_findings_pdf(db, run_id):
    run = db.execute("""SELECT mr.id,mr.created_at,mr.trace_json,j.title FROM match_runs mr
        JOIN jobs j ON j.id=mr.job_id WHERE mr.id=?""", (run_id,)).fetchone()
    if not run:
        raise ValueError("Match run not found")
    rows = db.execute("""SELECT r.rank,r.candidate_id,r.match_index,r.mandatory_status,r.assessments_json,
        c.name,c.external_id,c.category FROM results r JOIN candidates c ON c.id=r.candidate_id
        WHERE r.run_id=? ORDER BY r.rank""", (run_id,)).fetchall()
    trace = json.loads(run["trace_json"])
    retrieved = trace.get("retrieval", {}).get("candidates", len(rows))
    analyzed = trace.get("analysis", {}).get("candidates", len(rows))
    shown = rows[:10]
    normal, bold = _font_names()
    styles = {
        "title": ParagraphStyle("ri-title", fontName=bold, fontSize=19, leading=23, textColor=INK, spaceAfter=5),
        "h2": ParagraphStyle("ri-h2", fontName=bold, fontSize=11, leading=15, textColor=INK, spaceBefore=14, spaceAfter=5),
        "body": ParagraphStyle("ri-body", fontName=normal, fontSize=8.8, leading=12.5, textColor=INK, spaceAfter=5),
        "small": ParagraphStyle("ri-small", fontName=normal, fontSize=7.8, leading=11, textColor=MUTED, spaceAfter=4),
        "table": ParagraphStyle("ri-table", fontName=normal, fontSize=7.7, leading=10.2, textColor=INK),
        "table-head": ParagraphStyle("ri-table-head", fontName=bold, fontSize=7.5, leading=10, textColor=INK),
    }
    p = lambda text, style="body": Paragraph(text, styles[style])
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm, invariant=1, title="Resume Intelligence | Match findings",
                            author="Resume Intelligence")
    story = [p("RESUME INTELLIGENCE / SAVED FINDINGS", "small"),
             p(_safe(run["title"], 140), "title"),
             p(f"Run #{run_id}  |  {escape(run['created_at'])} UTC  |  {retrieved} retrieved  |  {analyzed} analyzed  |  {len(shown)} displayed", "small"),
             Spacer(1, 3 * mm),
             p("Method: FTS5 requirement terms and MiniLM span similarity feed reciprocal-rank fusion. The retrieved candidates are assessed against saved requirements and ordered by a deterministic match index. The index is a review aid, not a hiring probability."),
             p("TOP 10 / SAVED ORDER", "h2")]
    head = [p(x, "table-head") for x in ("Rank", "Candidate / category", "Index", "Mandatory", "Required", "Preferred")]
    table_data = [head]
    for row in shown:
        assessments = json.loads(row["assessments_json"])
        required = [a for a in assessments if a["mandatory"]]
        preferred = [a for a in assessments if not a["mandatory"]]
        count = lambda items: f"{sum(a['status'] == 'matched' for a in items)}/{len(items)}"
        name = row["name"].strip() if row["name"] and row["name"].strip() else f"Candidate {row['external_id'] or row['candidate_id']}"
        table_data.append([p(str(row["rank"]), "table"),
                           p(f"<b>{_safe(name, 90)}</b><br/>{_safe(row['category'] or 'Uploaded resume', 60)}", "table"),
                           p(f"{row['match_index']:.1f}", "table"), p(_safe(row["mandatory_status"].title(), 24), "table"),
                           p(count(required), "table"), p(count(preferred), "table")])
    table = Table(table_data, colWidths=[12*mm, 65*mm, 17*mm, 29*mm, 23*mm, 23*mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), PALE), ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LINEBELOW", (0,0), (-1,0), 0.7, GREEN), ("LINEBELOW", (0,1), (-1,-2), 0.3, LINE),
        ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
    story.extend([table, p("Coverage counts reflect matched resume mentions in the saved assessments; partial and uncertain items are not counted as supported.", "small")])
    for row in shown:
        assessments = json.loads(row["assessments_json"])
        name = row["name"].strip() if row["name"] and row["name"].strip() else f"Candidate {row['external_id'] or row['candidate_id']}"
        title = f"#{row['rank']}  {_safe(name, 100)}  |  {_safe(row['category'] or 'Uploaded resume', 55)}"
        block = [p(title, "h2"), p(f"Match index {row['match_index']:.1f}  |  Mandatory evidence: {_safe(row['mandatory_status'], 24)}", "small")]
        supported = [a for a in assessments if a["status"] == "matched"]
        attention = [a for a in assessments if a["status"] != "matched"]
        block.append(p("<b>Supported mentions:</b> " + ("; ".join(f"{_safe(a['label'], 95)} ({'required' if a['mandatory'] else 'preferred'})" for a in supported) or "None")))
        block.append(p("<b>Missing or uncertain evidence:</b> " + ("; ".join(f"{_safe(a['label'], 95)} ({_safe(a['status'].replace('_',' '), 28)})" for a in attention) or "None")))
        citations = 0
        for a in supported + attention:
            excerpt = _excerpt(db, row["candidate_id"], a)
            if not excerpt:
                continue
            block.append(p(f"<b>{_safe(a['label'], 75)} | span #{int(a['span_id'])} | candidate #{row['candidate_id']}:</b> &quot;{_safe(excerpt, 360)}&quot;", "small"))
            citations += 1
            if citations == 3:
                break
        if citations == 0:
            block.append(p("No short, contact-free validated source excerpt is available for this candidate.", "small"))
        story.extend(block)
    story.extend([p("LIMITATIONS", "h2"),
                  p("A resume mention does not verify proficiency, work depth, identity, or qualifications. Missing evidence does not prove inability. Scores depend on the job wording, retrieved shortlist, and deterministic evidence rules. Review original sources and conduct human assessment before any decision.")])

    def footer(canvas, pdf_doc):
        canvas.saveState()
        width, _ = A4
        canvas.setStrokeColor(LINE)
        canvas.line(17*mm, 14*mm, width-17*mm, 14*mm)
        canvas.setFont(normal, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(17*mm, 10*mm, "Resume Intelligence  |  Saved run evidence")
        canvas.drawRightString(width-17*mm, 10*mm, f"Page {pdf_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
