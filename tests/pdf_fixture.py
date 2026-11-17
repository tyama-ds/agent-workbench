"""Small PDF files written by hand for tests: text pages, an outline, a title, empty (scanned-like) pages."""


def _escape(text):
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def make_pdf(pages, *, title=None, outline=None, labels_from=None):
    """pages: one string per page (lines separated by newlines; '' gives a page without text).

    outline: [(title, page_number, level)] with level 0 or 1 (a level-1 row belongs to the level-0 row before it).
    labels_from: (first_page, printed_start): pages before first_page are numbered i, ii, ...; from it 1, 2, ...
    """
    objects = {}  # number -> bytes (without "n 0 obj" / "endobj")
    count = len(pages)
    font, first_page = 3, 4
    page_ids = [first_page + 2 * index for index in range(count)]
    following = first_page + 2 * count
    for index, text in enumerate(pages):
        lines = text.split('\n') if text else []
        stream = b''
        if lines:
            parts = ['BT /F1 11 Tf 72 760 Td']
            for line_index, line in enumerate(lines):
                if line_index:
                    parts.append('0 -14 Td')
                parts.append(f'({_escape(line)}) Tj')
            parts.append('ET')
            stream = '\n'.join(parts).encode('latin-1')
        objects[page_ids[index]] = (f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
                                    f'/Resources << /Font << /F1 {font} 0 R >> >> /Contents {page_ids[index] + 1} 0 R >>').encode()
        objects[page_ids[index] + 1] = b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream'
    catalog = '<< /Type /Catalog /Pages 2 0 R'
    if outline:
        root = following
        ids = [root + 1 + index for index in range(len(outline))]
        top = [index for index, row in enumerate(outline) if row[2] == 0]
        for index, (name, page, level) in enumerate(outline):
            entry = f'<< /Title ({_escape(name)}) /Dest [{page_ids[page - 1]} 0 R /Fit]'
            if level == 0:
                position = top.index(index)
                entry += f' /Parent {root} 0 R'
                if position:
                    entry += f' /Prev {ids[top[position - 1]]} 0 R'
                if position + 1 < len(top):
                    entry += f' /Next {ids[top[position + 1]]} 0 R'
                end = top[position + 1] if position + 1 < len(top) else len(outline)
                children = list(range(index + 1, end))
                if children:
                    entry += f' /First {ids[children[0]]} 0 R /Last {ids[children[-1]]} 0 R /Count {len(children)}'
            else:
                parent = max(item for item in top if item < index)
                end = next((item for item in top if item > index), len(outline))
                siblings = list(range(parent + 1, end))
                place = siblings.index(index)
                entry += f' /Parent {ids[parent]} 0 R'
                if place:
                    entry += f' /Prev {ids[siblings[place - 1]]} 0 R'
                if place + 1 < len(siblings):
                    entry += f' /Next {ids[siblings[place + 1]]} 0 R'
            objects[ids[index]] = (entry + ' >>').encode('latin-1')
        objects[root] = (f'<< /Type /Outlines /First {ids[top[0]]} 0 R /Last {ids[top[-1]]} 0 R /Count {len(top)} >>').encode()
        catalog += f' /Outlines {root} 0 R'
        following = root + 1 + len(outline)
    if labels_from:
        start, printed = labels_from
        catalog += f' /PageLabels << /Nums [0 << /S /r >> {start - 1} << /S /D /St {printed} >>] >>'
    objects[1] = (catalog + ' >>').encode()
    objects[2] = (f'<< /Type /Pages /Count {count} /Kids [' + ' '.join(f'{ident} 0 R' for ident in page_ids) + '] >>').encode()
    objects[font] = b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'
    info = None
    if title:
        info = following
        objects[info] = f'<< /Title ({_escape(title)}) >>'.encode('latin-1')
    output = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(output)
        output += b'%d 0 obj\n' % number + objects[number] + b'\nendobj\n'
    xref = len(output)
    size = max(objects) + 1
    output += b'xref\n0 %d\n' % size + b'0000000000 65535 f \n'
    for number in range(1, size):
        output += b'%010d 00000 n \n' % offsets[number] if number in offsets else b'0000000000 65535 f \n'
    output += (b'trailer\n<< /Size %d /Root 1 0 R' % size + (b' /Info %d 0 R' % info if info else b'')
               + b' >>\nstartxref\n%d\n%%%%EOF\n' % xref)
    return bytes(output)


def encrypted(data, user_password=''):
    """The same document, encrypted (RC4, which needs no extra library)."""
    import io
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    writer.encrypt(user_password=user_password, owner_password='owner', algorithm='RC4-128')
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
