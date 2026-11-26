"""Use openpyxl's 3.1 serializers with worksheet XML held in memory."""
import os
from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl.drawing.spreadsheet_drawing import SpreadsheetDrawing
from openpyxl.worksheet._writer import WorksheetWriter
from openpyxl.writer.excel import ExcelWriter


class InMemoryExcelWriter(ExcelWriter):
    def write_worksheet(self, worksheet):
        worksheet._drawing = SpreadsheetDrawing()
        worksheet._drawing.charts = worksheet._charts
        worksheet._drawing.images = worksheet._images
        with BytesIO() as xml:
            writer = WorksheetWriter(worksheet, out=xml)
            writer.write()
            worksheet._rels = writer._rels
            self._archive.writestr(worksheet.path[1:], xml.getvalue())
        self.manifest.append(worksheet)


def save_workbook(workbook, path):
    """Write a new XLSX directly, without worksheet scratch files or deletion."""
    workbook.properties.modified = datetime.now(timezone.utc).replace(tzinfo=None)
    with path.open("xb") as stream:
        with ZipFile(stream, "w", ZIP_DEFLATED, allowZip64=True) as archive:
            InMemoryExcelWriter(workbook, archive).write_data()
        stream.flush()
        os.fsync(stream.fileno())
