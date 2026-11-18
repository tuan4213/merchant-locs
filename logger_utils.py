# logger_utils.py — Logging helpers cho pipeline
import io

class PipelineLogger:
    def __init__(self):
        self.buffer = io.StringIO()
        self.indent = "   "

    def write(self, msg=""):
        print(msg, file=self.buffer)

    def hdr(self, title):
        self.write(f"\n{'='*72}\n{title}\n{'='*72}")

    def section(self, title):
        self.write(f"\n{self.indent}── {title} ──")

    def kv(self, key, value, indent_lv=1):
        pad = self.indent * indent_lv
        self.write(f"{pad}{key:<22} = {value}")

    def info(self, msg, indent_lv=1):
        pad = self.indent * indent_lv
        self.write(f"{pad}{msg}")

    def summary(self, title, items, indent_lv=1):
        pad = self.indent * indent_lv
        if title: self.write(f"\n{pad}{title}")
        for k, v in items.items():
            self.write(f"{pad}{k:<22} {v}")

    def table(self, title, rows, headers=None, widths=None, indent_lv=1):
        pad = self.indent * indent_lv
        if title: self.write(f"\n{pad}{title}")
        if headers and widths:
            self.write(pad + " ".join(f"{h:<{w}}" for h, w in zip(headers, widths)))
            self.write(pad + "-" * (sum(widths) + len(widths) - 1))
        for row in rows:
            if widths:
                self.write(pad + " ".join(f"{str(c):<{w}}" for c, w in zip(row, widths)))
            else:
                self.write(pad + " ".join(str(c) for c in row))

    def getvalue(self):
        return self.buffer.getvalue()
