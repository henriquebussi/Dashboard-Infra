import csv
from io import BytesIO, StringIO

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Font, PatternFill
from reportlab.pdfgen.canvas import Canvas

from schemas import DashboardSnapshot


def safe_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def render_snapshot(snapshot: DashboardSnapshot, fmt: str):
    buffer = BytesIO()
    if fmt == "csv":
        stream = StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["Área", "Filtros", "Estatística", "Valor atual", "Unidade", "Origem", "Amostra", "Valor da amostra"])
        for stat in snapshot.statistics:
            for point in stat.points or [None]:
                writer.writerow(map(safe_text, [snapshot.title, snapshot.scope, stat.name, stat.value, stat.unit,
                                                 stat.source, point.label if point else "", point.value if point else ""]))
        return stream.getvalue().encode("utf-8-sig"), "text/csv"
    if fmt == "xlsx":
        book = Workbook()
        book.remove(book.active)
        for index, stat in enumerate(snapshot.statistics, 1):
            sheet = book.create_sheet(str(index))
            for row in [[snapshot.title, snapshot.scope], ["Estatística", "Valor atual", "Unidade", "Origem"],
                        [stat.name, stat.value, stat.unit, stat.source], ["Amostra", "Valor"]]:
                sheet.append(list(map(safe_text, row)))
            for point in stat.points:
                sheet.append([safe_text(point.label), point.value])
            sheet.sheet_view.showGridLines = False
            sheet.freeze_panes = "A5"
            for row_number in (1, 2, 4):
                for cell in sheet[row_number]:
                    cell.fill = PatternFill("solid", fgColor="286B4C" if row_number == 1 else "EAF3ED")
                    cell.font = Font(bold=True, color="FFFFFF" if row_number == 1 else "286B4C")
            for row in sheet.iter_rows(min_row=6, max_col=2):
                if row[0].row % 2 == 0:
                    for cell in row:
                        cell.fill = PatternFill("solid", fgColor="F5F8F6")
            sheet.column_dimensions["A"].width = 38
            sheet.column_dimensions["B"].width = 36
            if stat.points:
                chart = LineChart()
                chart.title = stat.name
                chart.y_axis.title = stat.unit
                chart.add_data(Reference(sheet, min_col=2, min_row=5, max_row=sheet.max_row))
                chart.set_categories(Reference(sheet, min_col=1, min_row=5, max_row=sheet.max_row))
                chart.series[0].graphicalProperties.line.solidFill = "286B4C"
                sheet.add_chart(chart, "F2")
        book.save(buffer)
        return buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    pdf = Canvas(buffer)
    for stat in snapshot.statistics:
        def heading():
            pdf.setFillColor("#eaf3ed")
            pdf.roundRect(30, 767, 550, 53, 8, fill=1, stroke=0)
            pdf.setFillColor("#286b4c")
            pdf.setFont("Helvetica-Bold", 15)
            for y, line in [(800, snapshot.title), (780, snapshot.scope), (750, stat.name),
                            (730, f"{stat.value}   |   {stat.unit}   |   {stat.source}")]:
                pdf.drawString(40, y, line)
                pdf.setFont("Helvetica", 10)
            pdf.setStrokeColor("#286b4c")
            pdf.setLineWidth(1.5)
        heading()
        values = [point.value for point in stat.points]
        if values:
            low, high = min(values), max(values)
            path = pdf.beginPath()
            for i, value in enumerate(values):
                x = 45 + 490 * i / max(1, len(values) - 1)
                y = 585 + 100 * (value - low) / (high - low or 1)
                if i == 0:
                    path.moveTo(x, y)
                    pdf.circle(x, y, 1.5, fill=1)
                else:
                    path.lineTo(x, y)
            pdf.drawPath(path)
            pdf.drawString(40, 560, f"{stat.points[0].label}  -  {stat.points[-1].label}     Min: {low:g}   Max: {high:g}")
        y = 530
        for point in stat.points:
            if y < 45:
                pdf.showPage()
                heading()
                y = 700
            if y % 32 < 16:
                pdf.setFillColor("#f0f6f2")
                pdf.rect(35, y - 4, 540, 16, fill=1, stroke=0)
            pdf.setFillColor("#203329")
            pdf.drawString(40, y, point.label)
            pdf.drawString(315, y, str(point.value))
            y -= 16
        pdf.showPage()
    pdf.save()
    return buffer.getvalue(), "application/pdf"
