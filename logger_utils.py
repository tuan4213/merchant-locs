# logger_utils.py
import io

class PipelineLogger:
    def __init__(self):
        self.buffer = io.StringIO()
    
    def write(self, text):
        if text is None: return
        text = str(text)
        self.buffer.write(text)
        if not text.endswith('\n'):
            self.buffer.write('\n')
    
    def flush(self): pass
    
    def hdr(self, title):
        self.buffer.write(f"\n{'='*70}\n{title}\n{'='*70}\n")
    
    def section(self, title):
        self.buffer.write(f"\n--- {title} ---\n")
    
    def info(self, text):
        self.buffer.write(str(text) + "\n")
    
    def summary(self, title, data):
        self.buffer.write(f"\n{title}:\n")
        if isinstance(data, dict):
            for k, v in data.items():
                self.buffer.write(f"  • {k}: {v}\n")
    
    def table(self, title, rows, headers=None, widths=None):
        self.buffer.write(f"\n{title}:\n")
        if headers:
            self.buffer.write("  " + " | ".join(str(h) for h in headers) + "\n")
            self.buffer.write("  " + "-" * 50 + "\n")
        if rows:
            for row in rows:
                self.buffer.write("  " + " | ".join(str(c) for c in row) + "\n")
    
    def getvalue(self):
        return self.buffer.getvalue()
