"""Slides with a design: 16:9, a theme, a layout per slide, native tables and charts, and text that fits.

``pptx_write`` used to put every slide into the default template's "title
and bullets": nine identical 4:3 slides for a request that asked for a modern
deck with a chart. Here a deck gets a theme (colours and fonts), each slide a
layout that suits what it says (cover, section, one big figure, two columns,
a table, a chart, or bullets), and the text is measured against its box:
it is set smaller down to a readable minimum, and a list that still does not
fit goes on onto a following slide. What was changed is reported.

Nothing here opens PowerPoint or reads a template from outside: slides are
built on the library's blank layouts, charts are the format's own (their
numbers live in an embedded workbook the library writes).
"""
from __future__ import annotations

import math
import re
import unicodedata

EMU_INCH = 914400
WIDE, STANDARD = (13.333, 7.5), (10.0, 7.5)
THEMES = {
    # background, text, muted text, accent, second accent, panel (a tint of the background)
    'midnight': {'background': '0F172A', 'text': 'F8FAFC', 'muted': '94A3B8', 'accent': '38BDF8', 'accent2': 'F472B6', 'panel': '1E293B'},
    'paper': {'background': 'FFFFFF', 'text': '111827', 'muted': '6B7280', 'accent': '2563EB', 'accent2': 'F59E0B', 'panel': 'F3F4F6'},
    'sand': {'background': 'FAF7F2', 'text': '1F2937', 'muted': '78716C', 'accent': 'E11D48', 'accent2': '0F766E', 'panel': 'EFE9DF'},
}
DEFAULT_THEME = 'midnight'
FONTS = {'heading': 'Yu Gothic UI', 'body': 'Yu Gothic UI'}
LAYOUTS = ('bullets', 'cover', 'section', 'kpi', 'two_column', 'table', 'chart')
CHARTS = ('bar', 'column', 'line', 'pie')
MAX_ROWS, MAX_COLUMNS, MAX_POINTS, MAX_SERIES = 15, 8, 30, 6
_HEX = re.compile(r'#?([0-9a-fA-F]{6})\Z')
_FONT = re.compile(r'[\w .\-]{1,60}\Z')

TEXT = {'type': 'string'}
TEXTS = {'type': 'array', 'items': TEXT}
SLIDE_SCHEMA = {'type': 'object', 'properties': {
    'title': TEXT, 'body': TEXTS,
    'layout': {'type': 'string', 'enum': list(LAYOUTS)},
    'subtitle': TEXT, 'value': TEXT, 'label': TEXT,
    'left_title': TEXT, 'left': TEXTS, 'right_title': TEXT, 'right': TEXTS,
    'table': {'type': 'array', 'items': TEXTS},
    'chart': {'type': 'object', 'properties': {
        'type': {'type': 'string', 'enum': list(CHARTS)}, 'categories': TEXTS, 'unit': TEXT,
        'series': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'name': TEXT, 'values': {'type': 'array', 'items': {'type': 'number'}}},
            'required': ['name', 'values'], 'additionalProperties': False}}},
        'required': ['type', 'categories', 'series'], 'additionalProperties': False},
    'notes': TEXT}, 'required': ['title'], 'additionalProperties': False}
DESIGN_PROPERTIES = {
    'theme': {'type': 'string', 'enum': list(THEMES)},
    'colors': {'type': 'object', 'properties': {key: TEXT for key in ('background', 'text', 'accent', 'accent2')},
               'additionalProperties': False},
    'fonts': {'type': 'object', 'properties': {'heading': TEXT, 'body': TEXT}, 'additionalProperties': False},
    'aspect': {'type': 'string', 'enum': ['16:9', '4:3']}}
PPTX_WRITE_DESCRIPTION = (
    'Create or explicitly replace a PPTX (16:9). theme: midnight (dark, one bright accent), paper (white, bold headings) '
    'or sand (warm, red accent); colors and fonts may override it. Each slide has a title and a layout: bullets (body), '
    'cover (subtitle), section, kpi (value such as "3.1%", label, body as caption), two_column (left, right and their '
    'titles), table (rows of cells, first row the header), chart (type bar|column|line|pie, categories, series of '
    'numbers, unit). Text is fitted to its box; a list that is too long continues on the next slide. The result says '
    'what was adjusted.')
# What pptx_write looks like to a model while slides are not part of the work: the short form it always had.
PLAIN_WRITE_TOOL = {'description': 'Create or explicitly replace a PPTX from slides [{title,body:[text]}].',
                    'slides': {'type': 'array', 'items': {'type': 'object', 'properties': {'title': TEXT, 'body': TEXTS},
                                                          'required': ['title', 'body'], 'additionalProperties': False}}}
SLIDES_POLICY = (
    '\n\nSlides: build the deck with pptx_write and its layouts, not a list of bulleted slides. Choose a theme that '
    'suits the request (midnight for a modern dark look, paper for a clean white one, sand for a warm one). Open with '
    'a cover, divide parts with section slides, show a headline figure alone on a kpi slide, comparisons as a table or '
    'a chart with the real numbers (a chart needs numbers you have confirmed), and keep bullets to at most five short '
    'lines per slide. One message per slide; put the source and page in the last line of a slide\'s body. Read the '
    'result: it lists text that was made smaller or moved to a following slide.')
_SLIDE_WORD = re.compile(r'pptx|powerpoint|slide|deck|presentation|スライド|プレゼン|パワーポイント|パワポ', re.I)


class SlideError(ValueError):
    """A deck request that cannot be built; the text is for the model."""


def mentions_slides(text):
    return bool(isinstance(text, str) and _SLIDE_WORD.search(text))


# --- validation -----------------------------------------------------------------------------

def _text(value, label, limit, *, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise SlideError(f'{label} must be text of at most {limit} characters' + ('' if empty else ' and not empty'))
    return ''.join(char for char in value if char in '\n\t' or unicodedata.category(char)[0] != 'C')


def _lines(value, label, most=300, limit=10000):
    """A list of lines. One text with line breaks is taken as its lines, and numbers as their text: a model that
    sent body as a single string was refused four times with a message that did not say what it had sent."""
    if isinstance(value, str):
        value = [line for line in value.split('\n') if line.strip()]
    if not isinstance(value, list) or len(value) > most:
        got = f'{len(value)} items' if isinstance(value, list) else type(value).__name__
        raise SlideError(f'{label} must be a list of at most {most} short texts, such as ["first point", "second point"]; '
                         f'got {got}. Put more than that on further slides.')
    lines = []
    for item in value:
        if type(item) in (int, float) and math.isfinite(item):
            item = f'{item:g}'
        if not isinstance(item, str):
            raise SlideError(f'{label} must be a list of texts, such as ["first point", "second point"]; '
                             f'one item is {type(item).__name__}. A table goes into "table", a chart into "chart".')
        lines.append(_text(item, label, limit))
    return lines


def _color(value, label):
    match = _HEX.match(value) if isinstance(value, str) else None
    if not match:
        raise SlideError(f'{label} must be a colour as six hexadecimal digits such as "2563EB"')
    return match.group(1).upper()


def design(args):
    """The deck's colours, fonts and size from pptx_write's arguments."""
    name = args.get('theme', DEFAULT_THEME)
    if name not in THEMES:
        raise SlideError('theme must be one of: ' + ', '.join(THEMES))
    colors = dict(THEMES[name])
    custom = args.get('colors', {})
    if not isinstance(custom, dict) or set(custom) - {'background', 'text', 'accent', 'accent2'}:
        raise SlideError('colors may set background, text, accent and accent2')
    for key, value in custom.items():
        colors[key] = _color(value, f'colors.{key}')
    if 'background' in custom or 'text' in custom:
        # A tint between the two for panels and quiet text, so a custom pair stays readable.
        colors['panel'] = _mix(colors['background'], colors['text'], .08)
        colors['muted'] = _mix(colors['text'], colors['background'], .4)
    if _contrast(colors['background'], colors['text']) < 4.5:
        raise SlideError('colors.text is too close to colors.background to be read; choose a darker or lighter pair')
    fonts = dict(FONTS)
    custom = args.get('fonts', {})
    if not isinstance(custom, dict) or set(custom) - set(FONTS):
        raise SlideError('fonts may set heading and body')
    for key, value in custom.items():
        if not isinstance(value, str) or not _FONT.match(value):
            raise SlideError(f'fonts.{key} must be a font name')
        fonts[key] = value
    aspect = args.get('aspect', '16:9')
    if aspect not in {'16:9', '4:3'}:
        raise SlideError('aspect must be 16:9 or 4:3')
    return {'theme': name, 'colors': colors, 'fonts': fonts, 'aspect': aspect, 'size': WIDE if aspect == '16:9' else STANDARD}


def _rgb(value):
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _mix(first, second, share):
    return ''.join(f'{round(a + (b - a) * share):02X}' for a, b in zip(_rgb(first), _rgb(second)))


def _luminance(value):
    parts = [(channel / 255) for channel in _rgb(value)]
    parts = [part / 12.92 if part <= .03928 else ((part + .055) / 1.055) ** 2.4 for part in parts]
    return .2126 * parts[0] + .7152 * parts[1] + .0722 * parts[2]


def _contrast(first, second):
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + .05) / (low + .05)


def _on(color):
    """Black or white, whichever reads better on this colour."""
    return '111827' if _contrast(color, '111827') >= _contrast(color, 'FFFFFF') else 'FFFFFF'


def slide(item, index):
    """One validated slide: {layout, title, ...} with every text cleaned."""
    if not isinstance(item, dict) or 'title' not in item:
        raise SlideError(f'slide {index + 1}: each slide is an object with a title')
    unknown = set(item) - set(SLIDE_SCHEMA['properties'])
    if unknown:
        raise SlideError(f'slide {index + 1}: unknown field(s) ' + ', '.join(sorted(map(str, unknown))))
    where = f'slide {index + 1}'
    layout = item.get('layout') or ('table' if 'table' in item else 'chart' if 'chart' in item else 'bullets')
    if layout not in LAYOUTS:
        raise SlideError(f'{where}: layout must be one of ' + ', '.join(LAYOUTS))
    result = {'layout': layout, 'title': _text(item['title'], f'{where} title', 1000),
              'body': _lines(item.get('body', []), f'{where} body'), 'notes': _text(item.get('notes', ''), f'{where} notes', 5000)}
    for key in ('subtitle', 'value', 'label', 'left_title', 'right_title'):
        result[key] = _text(item.get(key, ''), f'{where} {key}', 300)
    for key in ('left', 'right'):
        result[key] = _lines(item.get(key, []), f'{where} {key}', 60, 2000)
    if layout == 'kpi' and not result['value'].strip():
        raise SlideError(f'{where}: a kpi slide needs value, the one figure it shows (for example "3.1%")')
    if layout == 'two_column' and not (result['left'] and result['right']):
        raise SlideError(f'{where}: a two_column slide needs left and right, each a list of lines')
    if layout == 'table':
        rows = item.get('table')
        if (not isinstance(rows, list) or not 2 <= len(rows) <= MAX_ROWS or not all(isinstance(row, list) for row in rows)
                or not 1 <= len(rows[0]) <= MAX_COLUMNS or any(len(row) != len(rows[0]) for row in rows)):
            raise SlideError(f'{where}: table must be 2 to {MAX_ROWS} rows of equal length (1 to {MAX_COLUMNS} cells), the first row the header')
        result['table'] = [[_text(cell if isinstance(cell, str) else _cell(cell), f'{where} table cell', 300) for cell in row] for row in rows]
    if layout == 'chart':
        result['chart'] = _chart(item.get('chart'), where)
    return result


def _cell(value):
    if type(value) in (int, float) and math.isfinite(value):
        return f'{value:g}'
    raise SlideError('a table cell must be text or a number')


def _chart(value, where):
    if not isinstance(value, dict) or set(value) - {'type', 'categories', 'series', 'unit'}:
        raise SlideError(f'{where}: chart must be an object with type, categories, series and optionally unit')
    kind = value.get('type')
    if kind not in CHARTS:
        raise SlideError(f'{where}: chart.type must be one of ' + ', '.join(CHARTS))
    categories = value.get('categories')
    if not isinstance(categories, list) or not 1 <= len(categories) <= MAX_POINTS:
        raise SlideError(f'{where}: chart.categories must list 1 to {MAX_POINTS} labels')
    categories = [_text(item if isinstance(item, str) else _cell(item), f'{where} chart category', 80) for item in categories]
    series = value.get('series')
    if not isinstance(series, list) or not 1 <= len(series) <= (1 if kind == 'pie' else MAX_SERIES):
        raise SlideError(f'{where}: chart.series must hold 1 to {MAX_SERIES} series (a pie chart has one)')
    rows = []
    for item in series:
        if not isinstance(item, dict) or set(item) != {'name', 'values'} or not isinstance(item['values'], list):
            raise SlideError(f'{where}: each chart series is {{name, values}}')
        values = item['values']
        if len(values) != len(categories) or any(type(number) not in (int, float) or not math.isfinite(number) for number in values):
            raise SlideError(f'{where}: a chart series needs one number for each of the {len(categories)} categories '
                             '(numbers, not text; leave a chart out when a value is not confirmed)')
        rows.append({'name': _text(item['name'], f'{where} series name', 80), 'values': [float(number) for number in values]})
    return {'type': kind, 'categories': categories, 'series': rows, 'unit': _text(value.get('unit', ''), f'{where} chart unit', 40)}


# --- measuring text ---------------------------------------------------------------------------

def _units(text):
    """Width of a line in units of one full-width character."""
    return sum(1.0 if unicodedata.east_asian_width(char) in 'WFA' else .58 if char.isupper() or char.isdigit() else .5 for char in text)


def lines_needed(texts, width_inches, points, *, bullet=False):
    """How many lines these paragraphs take in a box of this width at this size."""
    per_line = max(4.0, (width_inches - (.35 if bullet else 0)) * 72 / points)
    return sum(max(1, math.ceil(_units(part) / per_line)) for text in texts for part in (text.split('\n') or ['']))


def height_needed(texts, width_inches, points, *, bullet=False, spacing=1.3):
    """Inches these paragraphs take: their lines, and for a list the space after each item."""
    lines = lines_needed(texts, width_inches, points, bullet=bullet)
    return (lines * spacing + (len(texts) * .35 if bullet else 0)) * points / 72


def fit(texts, width_inches, height_inches, sizes, *, bullet=False, spacing=1.3):
    """The largest of ``sizes`` (points) at which the paragraphs fit the box, and whether even the smallest does."""
    for points in sizes:
        if height_needed(texts, width_inches, points, bullet=bullet, spacing=spacing) <= height_inches:
            return points, True
    return sizes[-1], False


def split(texts, width_inches, height_inches, points, *, spacing=1.3):
    """Cut a list into parts that each fit the box at this size (a part always takes at least one item)."""
    parts, current = [], []
    for text in texts:
        if current and height_needed([*current, text], width_inches, points, bullet=True, spacing=spacing) > height_inches:
            parts.append(current)
            current = []
        current.append(text)
    return [*parts, current] if current else parts or [[]]


# --- drawing ----------------------------------------------------------------------------------

class Deck:
    """Draws validated slides into a python-pptx presentation and notes what it had to adjust."""

    def __init__(self, presentation, look):
        from pptx.util import Inches
        self.presentation, self.look, self.colors, self.fonts = presentation, look, look['colors'], look['fonts']
        self.width, self.height = look['size']
        presentation.slide_width, presentation.slide_height = Inches(self.width), Inches(self.height)
        self.adjusted, self.count = [], 0
        self.margin = .7 if self.width > 11 else .55
        self.inner = self.width - 2 * self.margin

    # -- small helpers
    def _new(self, background=None, *, with_body=False):
        from pptx.dml.color import RGBColor
        # "Title Only", or "Title and Content" for a list: the title stays a title and the list stays the
        # slide's body, which is what an outline view and a screen reader go by.
        slide_ = self.presentation.slides.add_slide(self.presentation.slide_layouts[1 if with_body else 5])
        fill = slide_.background.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor.from_string(background or self.colors['background'])
        self.count += 1
        return slide_

    def _run(self, paragraph, text, points, color, *, bold=False, font='body'):
        from pptx.dml.color import RGBColor
        from pptx.oxml.ns import qn
        from pptx.util import Pt
        run = paragraph.add_run()
        run.text = text
        run.font.size, run.font.bold, run.font.name = Pt(points), bold, self.fonts[font]
        run.font.color.rgb = RGBColor.from_string(color)
        properties = run._r.get_or_add_rPr()
        for tag in ('a:ea', 'a:cs'):  # the same face for Japanese text, which "name" alone does not set
            element = properties.find(qn(tag))
            if element is None:
                element = properties.makeelement(qn(tag), {})
                properties.append(element)
            element.set('typeface', self.fonts[font])
        return run

    def _frame(self, shape, *, anchor='top', wrap=True):
        from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
        from pptx.util import Inches
        frame = shape.text_frame
        frame.word_wrap = wrap
        frame.auto_size = MSO_AUTO_SIZE.NONE  # the size was chosen here; the viewer is not to rescale it
        frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = Inches(.02)
        frame.vertical_anchor = {'top': MSO_ANCHOR.TOP, 'middle': MSO_ANCHOR.MIDDLE, 'bottom': MSO_ANCHOR.BOTTOM}[anchor]
        return frame

    def _box(self, slide_, left, top, width, height, *, anchor='top'):
        from pptx.util import Inches
        shape = slide_.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        return self._frame(shape, anchor=anchor)

    def _bar(self, slide_, left, top, width, height, color):
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.util import Inches
        shape = slide_.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(color)
        shape.line.fill.background()
        return shape

    def _paragraphs(self, frame, texts, points, color, *, bullet=False, bold=False, font='body', align=None, spacing=1.15):
        from pptx.oxml.ns import qn
        from pptx.util import Pt
        for index, text in enumerate(texts or ['']):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.line_spacing = spacing
            if align is not None:
                paragraph.alignment = align
            if bullet and text.strip():
                properties = paragraph._p.get_or_add_pPr()
                properties.set('marL', str(int(.3 * EMU_INCH)))
                properties.set('indent', str(int(-.3 * EMU_INCH)))
                colour = properties.makeelement(qn('a:buClr'), {})
                colour.append(colour.makeelement(qn('a:srgbClr'), {'val': self.colors['accent']}))
                properties.append(colour)
                properties.append(properties.makeelement(qn('a:buFont'), {'typeface': 'Arial'}))
                properties.append(properties.makeelement(qn('a:buChar'), {'char': '•'}))
                paragraph.space_after = Pt(points * .35)
            self._run(paragraph, text, points, color, bold=bold, font=font)

    def _title(self, slide_, text, *, top=.5, height=1.0, sizes=(30, 26, 22), color=None, left=None, width=None, anchor='bottom', where=''):
        from pptx.util import Inches
        left, width = self.margin if left is None else left, self.inner if width is None else width
        points, fits = fit([text], width, height, sizes, spacing=1.15)
        if points != sizes[0] or not fits:
            self.adjusted.append(f'{where}: the title was set at {points} pt' + ('' if fits else ' and is still too long for its place; shorten it'))
        shape = slide_.shapes.title
        shape.left, shape.top, shape.width, shape.height = Inches(left), Inches(top), Inches(width), Inches(height)
        from pptx.enum.text import PP_ALIGN
        frame = self._frame(shape, anchor=anchor)
        self._paragraphs(frame, [text], points, color or self.colors['text'], bold=True, font='heading', spacing=1.05,
                         align=PP_ALIGN.LEFT)  # the template centres its titles
        return points

    def _notes(self, slide_, text):
        if text.strip():
            slide_.notes_slide.notes_text_frame.text = text

    # -- layouts
    def add(self, item):
        where = f'slide {self.count + 1}'
        getattr(self, '_' + item['layout'])(item, where)

    def _bullets(self, item, where, *, continued=0):
        top, height = 1.85, self.height - 1.85 - .6
        points, fits = fit(item['body'], self.inner, height, (22, 20, 18, 16, 14), bullet=True)
        parts = [item['body']]
        if not fits:
            parts = split(item['body'], self.inner, height, points)
        if points != 22 and item['body']:
            self.adjusted.append(f'{where}: the list was set at {points} pt to fit'
                                 + (f' and continues on {len(parts) - 1} more slide(s)' if len(parts) > 1 else ''))
        for number, part in enumerate(parts):
            from pptx.util import Inches
            slide_ = self._new(with_body=True)
            title = item['title'] + (f' ({number + 1}/{len(parts)})' if len(parts) > 1 else '')
            self._title(slide_, title, top=.6, height=1.05, where=where)
            # The list is the slide's body and its second shape, as it always was (pptx_edit addresses shapes by number).
            body = slide_.placeholders[1]
            body.left, body.top, body.width, body.height = Inches(self.margin), Inches(top), Inches(self.inner), Inches(height)
            self._paragraphs(self._frame(body), part, points, self.colors['text'], bullet=True)
            self._bar(slide_, self.margin, .45, .9, .08, self.colors['accent'])
            self._notes(slide_, item['notes'])

    def _cover(self, item, where):
        slide_ = self._new()
        self._bar(slide_, 0, 0, .28, self.height, self.colors['accent'])
        self._bar(slide_, self.margin + .3, 2.15, 1.6, .12, self.colors['accent'])
        self._title(slide_, item['title'], top=2.45, height=2.2, sizes=(44, 38, 32, 28), left=self.margin + .3,
                    width=self.inner - .6, anchor='top', where=where)
        lines = [line for line in (item['subtitle'], *item['body']) if line.strip()]
        if lines:
            frame = self._box(slide_, self.margin + .3, 4.8, self.inner - .6, 1.6)
            points, fits = fit(lines, self.inner - .6, 1.6, (20, 18, 16, 14))
            if not fits:
                self.adjusted.append(f'{where}: the cover has more text under its title than fits; shorten it')
            self._paragraphs(frame, lines, points, self.colors['muted'])
        self._notes(slide_, item['notes'])

    def _section(self, item, where):
        accent = self.colors['accent']
        slide_ = self._new(background=accent)
        on = _on(accent)
        self._bar(slide_, self.margin, 3.05, 1.2, .1, on)
        self._title(slide_, item['title'], top=3.3, height=1.8, sizes=(40, 34, 28), color=on, anchor='top', where=where)
        lines = [line for line in (item['subtitle'], *item['body']) if line.strip()]
        if lines:
            frame = self._box(slide_, self.margin, 5.2, self.inner, 1.2)
            self._paragraphs(frame, lines[:3], 18, on)
        self._notes(slide_, item['notes'])

    def _kpi(self, item, where):
        slide_ = self._new()
        self._bar(slide_, self.margin, .45, .9, .08, self.colors['accent'])
        self._title(slide_, item['title'], top=.6, height=.9, sizes=(26, 22, 20), where=where)
        value_points, fits = fit([item['value']], self.inner, 2.3, (110, 96, 80, 66, 54), spacing=1.0)
        if not fits:
            self.adjusted.append(f'{where}: the figure is too long for a kpi slide; give value as a short figure such as "3.1%"')
        frame = self._box(slide_, self.margin, 1.75, self.inner, 2.4, anchor='middle')
        self._paragraphs(frame, [item['value']], value_points, self.colors['accent'], bold=True, font='heading', spacing=1.0)
        if item['label'].strip():
            frame = self._box(slide_, self.margin, 4.2, self.inner, .8)
            points, _ = fit([item['label']], self.inner, .8, (26, 22, 18))
            self._paragraphs(frame, [item['label']], points, self.colors['text'], bold=True)
        if item['body']:
            frame = self._box(slide_, self.margin, 5.1, self.inner, self.height - 5.1 - .5)
            points, fits = fit(item['body'], self.inner, self.height - 5.1 - .5, (18, 16, 14, 12))
            if not fits:
                self.adjusted.append(f'{where}: the caption under the figure is too long; keep it to two or three lines')
            self._paragraphs(frame, item['body'], points, self.colors['muted'])
        self._notes(slide_, item['notes'])

    def _two_column(self, item, where):
        slide_ = self._new()
        self._bar(slide_, self.margin, .45, .9, .08, self.colors['accent'])
        self._title(slide_, item['title'], top=.6, height=1.05, where=where)
        gap, top = .5, 1.9
        width, height = (self.inner - gap) / 2, self.height - top - .6
        sizes = (20, 18, 16, 14, 12)
        points = min(fit(item[side], width - .5, height - (.75 if item[side + '_title'].strip() else .2), sizes, bullet=True)[0]
                     for side in ('left', 'right'))
        for number, side in enumerate(('left', 'right')):
            left = self.margin + number * (width + gap)
            self._bar(slide_, left, top, width, height, self.colors['panel'])
            self._bar(slide_, left, top, width, .07, self.colors['accent' if number == 0 else 'accent2'])
            inner_top = top + .25
            if item[side + '_title'].strip():
                frame = self._box(slide_, left + .25, inner_top, width - .5, .5)
                self._paragraphs(frame, [item[side + '_title']], 20, self.colors['text'], bold=True, font='heading')
                inner_top += .6
            room = top + height - inner_top - .15
            if height_needed(item[side], width - .5, points, bullet=True) > room:
                self.adjusted.append(f'{where}: the {side} column holds more than fits even at {points} pt; shorten it or use two slides')
            frame = self._box(slide_, left + .25, inner_top, width - .5, room)
            self._paragraphs(frame, item[side], points, self.colors['text'], bullet=True)
        if points != sizes[0]:
            self.adjusted.append(f'{where}: the columns were set at {points} pt to fit')
        self._notes(slide_, item['notes'])

    def _table(self, item, where):
        from pptx.dml.color import RGBColor
        from pptx.util import Inches
        slide_ = self._new()
        self._bar(slide_, self.margin, .45, .9, .08, self.colors['accent'])
        self._title(slide_, item['title'], top=.6, height=1.05, where=where)
        rows = item['table']
        caption = [line for line in item['body'] if line.strip()][:2]
        top = 1.9
        height = self.height - top - (.5 + .35 * len(caption))
        columns, width = len(rows[0]), self.inner
        cell_width = width / columns - .2

        def needed(points):
            # Each row is as tall as its tallest cell; a little padding above and below the text.
            return sum(max(lines_needed([cell], cell_width, points) for cell in row) * points * 1.3 / 72 + .14 for row in rows)

        sizes = (18, 16, 14, 12, 11, 10)
        points = next((candidate for candidate in sizes if needed(candidate) <= height), sizes[-1])
        if needed(points) > height:
            self.adjusted.append(f'{where}: the table does not fit even at {points} pt; use fewer rows or shorter cells, or two slides')
        elif points != sizes[0]:
            self.adjusted.append(f'{where}: the table was set at {points} pt to fit')
        shape = slide_.shapes.add_table(len(rows), columns, Inches(self.margin), Inches(top), Inches(width), Inches(min(height, needed(points))))
        from pptx.enum.text import MSO_ANCHOR
        table = shape.table
        accent, on = self.colors['accent'], _on(self.colors['accent'])
        # Rows share the room that is left, up to a comfortable height, so a short table does not sit cramped at the top.
        spare = max(0.0, min(height, len(rows) * .75) - needed(points)) / len(rows)
        for r, row in enumerate(rows):
            table.rows[r].height = Inches(max(lines_needed([cell], cell_width, points) for cell in row) * points * 1.3 / 72 + .14 + spare)
            for c, text in enumerate(row):
                cell = table.cell(r, c)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.margin_left = cell.margin_right = Inches(.12)
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(accent if r == 0 else self.colors['panel'] if r % 2 == 0 else self.colors['background'])
                frame = cell.text_frame
                frame.word_wrap = True
                self._paragraphs(frame, [text], points, on if r == 0 else self.colors['text'], bold=r == 0, font='heading' if r == 0 else 'body')
        if caption:
            frame = self._box(slide_, self.margin, self.height - .45 - .35 * len(caption), self.inner, .35 * len(caption) + .1)
            self._paragraphs(frame, caption, 12, self.colors['muted'])
        self._notes(slide_, item['notes'])

    def _chart(self, item, where):
        from pptx.chart.data import CategoryChartData
        from pptx.dml.color import RGBColor
        from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
        from pptx.util import Inches, Pt
        slide_ = self._new()
        self._bar(slide_, self.margin, .45, .9, .08, self.colors['accent'])
        self._title(slide_, item['title'], top=.6, height=1.05, where=where)
        spec = item['chart']
        caption = [line for line in item['body'] if line.strip()][:2]
        data = CategoryChartData()
        data.categories = spec['categories']
        for series in spec['series']:
            data.add_series(series['name'], series['values'])
        kind = {'bar': XL_CHART_TYPE.BAR_CLUSTERED, 'column': XL_CHART_TYPE.COLUMN_CLUSTERED,
                'line': XL_CHART_TYPE.LINE_MARKERS, 'pie': XL_CHART_TYPE.PIE}[spec['type']]
        top = 1.85
        height = self.height - top - (.45 + .35 * len(caption))
        frame = slide_.shapes.add_chart(kind, Inches(self.margin), Inches(top), Inches(self.inner), Inches(height), data)
        chart = frame.chart
        # The library keeps the numbers twice: in the chart itself and in an embedded workbook for "edit data".
        # Embedded objects are not allowed in the files this application writes or reads, so the workbook is
        # left out; the chart shows from its own copy of the numbers.
        from pptx.oxml.ns import qn
        external = chart._chartSpace.find(qn('c:externalData'))
        if external is not None:
            relation = external.get(qn('r:id'))
            chart._chartSpace.remove(external)
            chart.part.drop_rel(relation)
        chart.has_title = False  # the slide's title says what the chart shows
        chart.font.size, chart.font.name = Pt(13), self.fonts['body']
        chart.font.color.rgb = RGBColor.from_string(self.colors['text'])
        palette = [self.colors['accent'], self.colors['accent2'], self.colors['muted'],
                   _mix(self.colors['accent'], self.colors['background'], .45), _mix(self.colors['accent2'], self.colors['background'], .45),
                   _mix(self.colors['text'], self.colors['background'], .25)]
        several, points = len(spec['series']) > 1, len(spec['categories'])
        chart.has_legend = several or spec['type'] == 'pie'
        if chart.has_legend:
            chart.legend.position, chart.legend.include_in_layout = XL_LEGEND_POSITION.BOTTOM, False
        plot = chart.plots[0]
        if spec['type'] == 'pie':
            for index, point in enumerate(plot.series[0].values):
                fill = plot.series[0].points[index].format.fill
                fill.solid()
                fill.fore_color.rgb = RGBColor.from_string(palette[index % len(palette)] if index < len(palette)
                                                           else _mix(palette[index % len(palette)], self.colors['background'], .3))
        else:
            for index, series in enumerate(plot.series):
                color = RGBColor.from_string(palette[index % len(palette)])
                if spec['type'] == 'line':
                    series.format.line.color.rgb, series.format.line.width, series.smooth = color, Pt(2.75), False
                    series.marker.format.fill.solid()
                    series.marker.format.fill.fore_color.rgb = color
                else:
                    series.format.fill.solid()
                    series.format.fill.fore_color.rgb = color
            if spec['type'] in {'bar', 'column'}:
                plot.gap_width = 60
            for axis in (chart.category_axis, chart.value_axis):
                axis.format.line.color.rgb = RGBColor.from_string(self.colors['muted'])
                axis.tick_labels.font.size = Pt(12)
            chart.value_axis.has_major_gridlines = True
            chart.value_axis.major_gridlines.format.line.color.rgb = RGBColor.from_string(_mix(self.colors['background'], self.colors['text'], .18))
            if spec['unit'].strip():
                chart.value_axis.has_title = True
                chart.value_axis.axis_title.text_frame.text = spec['unit']
                chart.value_axis.axis_title.text_frame.paragraphs[0].runs[0].font.size = Pt(12)
        if (not several and points <= 12) or spec['type'] == 'pie':
            plot.has_data_labels = True
            plot.data_labels.font.size = Pt(12)
            whole = all(float(number).is_integer() for series in spec['series'] for number in series['values'])
            plot.data_labels.number_format, plot.data_labels.number_format_is_linked = ('#,##0' if whole else '0.0'), False
            if spec['type'] == 'pie':
                plot.data_labels.show_percentage = False
        if caption:
            box = self._box(slide_, self.margin, self.height - .45 - .35 * len(caption), self.inner, .35 * len(caption) + .1)
            self._paragraphs(box, caption, 12, self.colors['muted'])
        self._notes(slide_, item['notes'])


def build(presentation, args):
    """Draw pptx_write's slides into an empty presentation. Returns what to report beside the saved file."""
    slides = args.get('slides')
    if not isinstance(slides, list) or not 1 <= len(slides) <= 100:
        raise SlideError('slides must contain 1 to 100 slide objects')
    look = design(args)
    items = [slide(item, index) for index, item in enumerate(slides)]
    deck = Deck(presentation, look)
    for item in items:
        deck.add(item)
        if deck.count > 150:
            raise SlideError('The deck grew past 150 slides while fitting its text; shorten the lists')
    layouts = {}
    for item in items:
        layouts[item['layout']] = layouts.get(item['layout'], 0) + 1
    result = {'slides_written': deck.count, 'design': {'theme': look['theme'], 'aspect': look['aspect'], 'layouts': layouts}}
    if deck.adjusted:
        result['adjusted'] = list(dict.fromkeys(deck.adjusted))[:40]
    if len(items) >= 4 and set(layouts) == {'bullets'}:
        result['design_note'] = ('Every slide is a bulleted list. A deck reads better with a cover, section slides, a kpi slide '
                                 'for a headline figure and a table or chart for comparisons; see the layouts of pptx_write.')
    return result
