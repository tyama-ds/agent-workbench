"""pptx_write with a design: 16:9, themes, layouts, native tables and charts, and text that fits its box."""
import asyncio
import io
import sys
import zipfile
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Inches

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench import slides
from workbench.harness import HarnessError, PathHarness, ToolExecutor
from test_engine import configured, start

DECK = [
    {'layout': 'cover', 'title': '世界経済見通し 2026年10月', 'subtitle': 'IMF World Economic Outlook の要点'},
    {'layout': 'section', 'title': '1. 世界経済の現状'},
    {'layout': 'kpi', 'title': '2026年の世界成長率', 'value': '3.1%', 'label': '2027年は 3.4%', 'body': ['出典: p. 15 (printed xiii)']},
    {'title': '主なポイント', 'body': ['世界の成長率は 3.1%', 'インフレ率は 4.7%']},
    {'layout': 'two_column', 'title': '先進国と新興国', 'left_title': '先進国', 'left': ['2.1%'], 'right_title': '新興国', 'right': ['3.7%']},
    {'layout': 'table', 'title': '成長率（%）', 'table': [['', '2026', '2027'], ['世界', '3.1', '3.4'], ['先進国', '2.1', '1.8']]},
    {'layout': 'chart', 'title': '世界成長率', 'body': ['出典: Table 1.1'],
     'chart': {'type': 'column', 'categories': ['2025', '2026', '2027'], 'unit': '%',
               'series': [{'name': '世界', 'values': [3.5, 3.1, 3.4]}, {'name': '先進国', 'values': [2.0, 2.1, 1.8]}]}},
]


def write(tmp_path, **args):
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    path = str(tmp_path / 'deck.pptx')
    result = asyncio.run(tools.execute('pptx_write', {'path': path, 'expected_sha256': 'missing', **args}))
    return result, Presentation(path), tools, path


def test_a_deck_is_wide_themed_and_uses_a_layout_for_each_kind_of_content(tmp_path):
    result, deck, tools, path = write(tmp_path, slides=DECK, theme='paper')
    assert result['slides_written'] == 7 and 'adjusted' not in result and 'design_note' not in result
    assert result['design'] == {'theme': 'paper', 'aspect': '16:9', 'layouts': {
        'cover': 1, 'section': 1, 'kpi': 1, 'bullets': 1, 'two_column': 1, 'table': 1, 'chart': 1}}
    assert (deck.slide_width, deck.slide_height) == (Inches(13.333), Inches(7.5))
    cover, section, kpi, bullets, columns, table, chart = deck.slides
    # Every slide keeps a real title, with the theme's colours and the font set for Japanese text too.
    assert [slide.shapes.title.text_frame.text for slide in deck.slides] == [item['title'] for item in DECK]
    run = cover.shapes.title.text_frame.paragraphs[0].runs[0]
    assert run.font.bold and run.font.size.pt == 44 and str(run.font.color.rgb) == '111827' and run.font.name == 'Yu Gothic UI'
    assert 'ea typeface="Yu Gothic UI"' in run._r.xml.replace('a:ea', 'ea')
    assert str(cover.background.fill.fore_color.rgb) == 'FFFFFF' and str(section.background.fill.fore_color.rgb) == '2563EB'
    assert str(section.shapes.title.text_frame.paragraphs[0].runs[0].font.color.rgb) == 'FFFFFF'  # readable on the accent
    # The one figure of a kpi slide is large and in the accent colour.
    figure = next(shape for shape in kpi.shapes if shape.has_text_frame and shape.text_frame.text == '3.1%')
    assert figure.text_frame.paragraphs[0].runs[0].font.size.pt == 110 and str(figure.text_frame.paragraphs[0].runs[0].font.color.rgb) == '2563EB'
    assert bullets.placeholders[1].text_frame.text.startswith('世界の成長率') and 'buChar' in bullets.placeholders[1]._element.xml
    grid = next(shape for shape in table.shapes if shape.has_table).table
    assert [[cell.text for cell in row.cells] for row in grid.rows] == DECK[5]['table']
    assert str(grid.cell(0, 1).fill.fore_color.rgb) == '2563EB'
    plot = next(shape for shape in chart.shapes if shape.has_chart).chart.plots[0]
    assert list(plot.categories) == ['2025', '2026', '2027'] and [list(series.values) for series in plot.series] == [[3.5, 3.1, 3.4], [2.0, 2.1, 1.8]]
    # The file holds no embedded object: the chart shows from its own copy of the numbers.
    names = zipfile.ZipFile(path).namelist()
    assert not [name for name in names if 'embeddings' in name.lower()] and any(name.startswith('ppt/charts/chart') for name in names)
    # What a reader of the file gets back, numbers included.
    back = asyncio.run(tools.execute('pptx_read', {'path': path}))
    assert len(back['slides']) == 7 and back['sha256'] == result['sha256']
    shapes = back['slides'][6]['shapes']
    assert {'categories': ['2025', '2026', '2027'], 'series': [{'name': '世界', 'values': [3.5, 3.1, 3.4]}, {'name': '先進国', 'values': [2.0, 2.1, 1.8]}]} in [
        shape.get('chart') for shape in shapes]
    assert any(shape.get('table') == DECK[5]['table'] for shape in back['slides'][5]['shapes'])


@pytest.mark.parametrize('theme,background,accent', [('midnight', '0F172A', '38BDF8'), ('paper', 'FFFFFF', '2563EB'), ('sand', 'FAF7F2', 'E11D48')])
def test_the_built_in_themes_and_the_default(tmp_path, theme, background, accent):
    result, deck, _, _ = write(tmp_path, slides=DECK[:3], theme=theme)
    assert str(deck.slides[0].background.fill.fore_color.rgb) == background and str(deck.slides[1].background.fill.fore_color.rgb) == accent
    assert slides.DEFAULT_THEME == 'midnight'
    for name, colors in slides.THEMES.items():
        assert slides._contrast(colors['background'], colors['text']) >= 7, name      # body text
        assert slides._contrast(colors['background'], colors['accent']) >= 3, name    # large figures and marks


def test_colours_fonts_and_the_old_shape_of_a_request(tmp_path):
    result, deck, _, _ = write(tmp_path, slides=[{'title': 'First', 'body': ['One', 'Two']}], aspect='4:3',
                               colors={'background': '#101010', 'text': 'fafafa', 'accent': 'FFCC00'}, fonts={'heading': 'BIZ UDPGothic'})
    assert result['design']['aspect'] == '4:3' and deck.slide_width == Inches(10)
    slide = deck.slides[0]
    assert str(slide.background.fill.fore_color.rgb) == '101010' and slide.shapes.title.text_frame.paragraphs[0].runs[0].font.name == 'BIZ UDPGothic'
    body = next(shape for shape in slide.shapes if shape.has_text_frame and shape.text_frame.text.startswith('One'))
    assert [paragraph.text for paragraph in body.text_frame.paragraphs] == ['One', 'Two']
    for bad, problem in (({'theme': 'neon'}, 'theme must be one of'), ({'colors': {'text': '0F172A', 'background': '101828'}}, 'too close'),
                         ({'colors': {'accent': 'blue'}}, 'six hexadecimal digits'), ({'fonts': {'heading': 'x' * 80}}, 'font name'),
                         ({'aspect': '21:9'}, 'aspect must be')):
        with pytest.raises(HarnessError, match=problem):
            write(tmp_path / 'x' if False else tmp_path, slides=[{'title': 'T'}], **bad)


def test_text_is_fitted_and_a_long_list_goes_on_onto_the_next_slide(tmp_path):
    long_list = [f'項目 {index}: これは長めの説明文で、スライドの幅を超えると折り返されます。数値や出典も併記します。' for index in range(1, 31)]
    result, deck, _, _ = write(tmp_path, slides=[{'title': '長い一覧', 'body': long_list}, {'title': '短い一覧', 'body': ['一行']}])
    parts = result['slides_written'] - 1
    assert parts >= 2 and result['adjusted'] == [f'slide 1: the list was set at 14 pt to fit and continues on {parts - 1} more slide(s)']
    titles = [slide.shapes.title.text_frame.text for slide in deck.slides]
    assert titles == [f'長い一覧 ({number}/{parts})' for number in range(1, parts + 1)] + ['短い一覧']
    shown = []
    for slide in list(deck.slides)[:parts]:
        box = next(shape for shape in slide.shapes if shape.has_text_frame and shape.text_frame.text.startswith('項目'))
        lines = [paragraph.text for paragraph in box.text_frame.paragraphs]
        size = box.text_frame.paragraphs[0].runs[0].font.size.pt
        # What the box holds fits it at the size it was set.
        assert size == 14 and slides.height_needed(lines, slides.WIDE[0] - 1.4, size, bullet=True) <= box.height / 914400 + .01
        shown += lines
    assert shown == long_list  # nothing is dropped
    # A medium list is only set smaller; a long title is set smaller and said to be so.
    medium, deck, _, _ = write(tmp_path / 'm' if (tmp_path / 'm').mkdir() is None else tmp_path, slides=[
        {'title': '要点', 'body': [f'要点 {index}: 短い説明' for index in range(1, 13)]},
        {'title': 'とても長い題名が続くスライドで、' * 6, 'body': ['一行']}])
    assert medium['slides_written'] == 2 and medium['adjusted'][0] == 'slide 1: the list was set at 18 pt to fit'
    assert medium['adjusted'][1] == 'slide 2: the title was set at 22 pt and is still too long for its place; shorten it'
    ten, _, _, _ = write(tmp_path / 't' if (tmp_path / 't').mkdir() is None else tmp_path, slides=[
        {'title': '要点', 'body': [f'要点 {index}: 短い説明' for index in range(1, 11)]}])
    assert 'adjusted' not in ten  # ten short lines fit as they are
    # Measuring: full-width characters are twice as wide as Latin letters.
    assert slides.lines_needed(['あ' * 60], 10, 20) == 2 and slides.lines_needed(['a' * 60], 10, 20) == 1
    assert slides.fit(['x'], 5, 1, (30, 20)) == (30, True) and slides.fit(['あ' * 400], 5, 1, (30, 20)) == (20, False)


def test_a_deck_of_bullets_only_is_pointed_to_the_other_layouts(tmp_path):
    result, _, _, _ = write(tmp_path, slides=[{'title': f'スライド {index}', 'body': ['一行']} for index in range(1, 6)])
    assert 'Every slide is a bulleted list' in result['design_note'] and 'kpi' in result['design_note']


@pytest.mark.parametrize('slide,problem', [
    ({'body': ['x']}, 'object with a title'), ({'title': 'T', 'colour': 'red'}, 'unknown field'),
    ({'title': 'T', 'layout': 'poster'}, 'layout must be one of'), ({'title': 'T', 'layout': 'kpi'}, 'needs value'),
    ({'title': 'T', 'layout': 'two_column', 'left': ['a']}, 'needs left and right'),
    ({'title': 'T', 'layout': 'table', 'table': [['a', 'b'], ['c']]}, 'rows of equal length'),
    ({'title': 'T', 'layout': 'table', 'table': [['only header']]}, '2 to 15 rows'),
    ({'title': 'T', 'layout': 'chart'}, 'chart must be an object'),
    ({'title': 'T', 'chart': {'type': 'radar', 'categories': ['a'], 'series': []}}, 'chart.type must be'),
    ({'title': 'T', 'chart': {'type': 'bar', 'categories': ['a', 'b'], 'series': [{'name': 's', 'values': [1]}]}}, 'one number for each of the 2 categories'),
    ({'title': 'T', 'chart': {'type': 'bar', 'categories': ['a'], 'series': [{'name': 's', 'values': ['3.1%']}]}}, 'numbers, not text'),
    ({'title': 'T', 'chart': {'type': 'bar', 'categories': ['a'], 'series': [{'name': 's', 'values': [float('nan')]}]}}, 'one number for each'),
    ({'title': 'T', 'chart': {'type': 'pie', 'categories': ['a'], 'series': [{'name': 's', 'values': [1]}, {'name': 't', 'values': [2]}]}}, 'a pie chart has one'),
])
def test_a_slide_that_cannot_be_built_says_what_it_needs(tmp_path, slide, problem):
    with pytest.raises(HarnessError, match=problem):
        write(tmp_path, slides=[slide])
    assert not (tmp_path / 'deck.pptx').exists()


def test_charts_of_every_kind_are_written_and_read_back(tmp_path):
    kinds = [{'title': kind, 'chart': {'type': kind, 'categories': ['A', 'B', 'C'], 'series': [{'name': 'S', 'values': [1, 2.5, 4]}]}}
             for kind in slides.CHARTS]
    result, deck, tools, path = write(tmp_path, slides=kinds, theme='sand')
    assert result['slides_written'] == 4 and result['design']['layouts'] == {'chart': 4}
    for slide in deck.slides:
        chart = next(shape for shape in slide.shapes if shape.has_chart).chart
        assert list(chart.plots[0].series[0].values) == [1.0, 2.5, 4.0] and chart.has_title is False


async def test_the_guidance_on_slides_joins_the_instructions_when_slides_are_asked_for(tmp_path):
    engine, work = configured(tmp_path, None)
    engine.kick = lambda agent: None
    try:
        run, pm = await start(engine, task='WEO の要約を docx で、説明スライドをモダンなデザインで作って', max_workers=0)
        policy = engine._policy(run, pm)
        assert 'Slides: build the deck with pptx_write and its layouts' in policy and 'midnight for a modern dark look' in policy
        assert 'a chart needs numbers you have confirmed' in policy
        tool = next(tool for tool in engine._model_tools(run, pm) if tool['name'] == 'pptx_write')
        assert set(tool['parameters']['properties']) >= {'slides', 'theme', 'colors', 'fonts', 'aspect'}
        assert tool['parameters']['properties']['slides']['items']['properties']['layout']['enum'] == list(slides.LAYOUTS)
        # Work that is not about slides sees pptx_write in its short form and carries no guidance on decks.
        plain, lead = await start(engine, task='売上の表を xlsx にまとめて', max_workers=0)
        assert 'Slides:' not in engine._policy(plain, lead)
        short = next(tool for tool in engine._model_tools(plain, lead) if tool['name'] == 'pptx_write')
        assert short['description'] == 'Create or explicitly replace a PPTX from slides [{title,body:[text]}].'
        assert set(short['parameters']['properties']) == {'path', 'expected_sha256', 'slides'}
        assert set(short['parameters']['properties']['slides']['items']['properties']) == {'title', 'body'}
        saved = await engine.execute_tool(plain, lead, 'pptx_write', {
            'path': str(work / 'a.pptx'), 'expected_sha256': 'missing', 'slides': [{'layout': 'kpi', 'title': '売上', 'value': '124'}]})
        assert saved['slides_written'] == 1 and 'Slides:' in engine._policy(plain, lead)  # once a deck is being made
        full = next(tool for tool in engine._model_tools(plain, lead) if tool['name'] == 'pptx_write')
        assert 'theme' in full['parameters']['properties'] and 'kpi' in full['description']
    finally:
        await engine.close()
