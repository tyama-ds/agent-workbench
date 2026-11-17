"""A table written as text in docx_write's paragraphs becomes a real table where it stands."""
import asyncio
import sys
from pathlib import Path

from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.harness import PathHarness, ToolExecutor, _comma_tables, _table_blocks


def write(tmp_path, **args):
    tools = ToolExecutor(PathHarness([str(tmp_path)], [str(tmp_path)]))
    path = str(tmp_path / 'report.docx')
    result = asyncio.run(tools.execute('docx_write', {'path': path, 'expected_sha256': 'missing', **args}))
    return result, Document(path), tools, path


def test_markdown_and_tab_separated_rows_are_written_as_tables_in_place(tmp_path):
    """Real-machine cases: a Markdown table stayed in the document as paragraphs ("| --- |" and all) beside
    the real table, and in another run the table was a list of tab-separated paragraphs."""
    paragraphs = ['世界経済見通しの要約', '| 地域 | 2026 | 2027 |', '| --- | --- | --- |', '| 世界 | 3.1 | 3.4 |', '| 先進国 | 2.1 | 1.8 |',
                  '出典: Table 1.1, p. 26 (printed 10)', '国\t成長率', '米国\t2.3', '日本\t0.7', '以上']
    result, document, tools, path = write(tmp_path, paragraphs=paragraphs)
    assert result['tables_converted'] == 2 and 'tables argument' in result['tables_note']
    assert [paragraph.text for paragraph in document.paragraphs] == ['世界経済見通しの要約', '出典: Table 1.1, p. 26 (printed 10)', '以上']
    first, second = document.tables
    assert [[cell.text for cell in row.cells] for row in first.rows] == [['地域', '2026', '2027'], ['世界', '3.1', '3.4'], ['先進国', '2.1', '1.8']]
    assert [[cell.text for cell in row.cells] for row in second.rows] == [['国', '成長率'], ['米国', '2.3'], ['日本', '0.7']]
    assert first.style.name == 'Table Grid' and first.cell(0, 0).paragraphs[0].runs[0].font.bold
    # In the order written: heading, table, source line, table, closing line.
    kinds = [child.tag.rsplit('}', 1)[-1] for child in document.element.body if child.tag.rsplit('}', 1)[-1] in {'p', 'tbl'}]
    assert kinds == ['p', 'tbl', 'p', 'tbl', 'p']
    back = asyncio.run(tools.execute('docx_read', {'path': path}))
    assert back['tables'][0][1] == ['世界', '3.1', '3.4'] and not any('|' in row['text'] or '\t' in row['text'] for row in back['paragraphs'])


def test_what_is_not_a_table_stays_as_written(tmp_path):
    paragraphs = ['a | b', '| 一行だけの行 | x |', '見出し\t値', '本文', 'タブ\tのある一文だけ', '| a | b |', '| c | d | e |', '| --- |']
    result, document, _, _ = write(tmp_path, paragraphs=paragraphs, tables=[[['x', 'y'], ['1', '2']]])
    assert 'tables_converted' not in result and len(document.tables) == 1  # only the one given as a table
    assert [paragraph.text for paragraph in document.paragraphs] == paragraphs
    assert document.tables[0].style.name == 'Table Grid'
    # One paragraph that holds the whole table on several lines.
    blocks = _table_blocks(['前文', '| a | b |\n|:--|--:|\n| 1 | 2 |', '後文'])
    assert blocks == ['前文', [['a', 'b'], ['1', '2']], '後文']
    assert _table_blocks(['x\ty', '1\t2', '3\t4\t5']) == [[['x', 'y'], ['1', '2']], '3\t4\t5']


def test_a_table_on_one_line_and_a_text_copy_of_a_given_table(tmp_path):
    """Real-machine case: "| 対象 | 2026 | 2027 | | --- | --- | --- | | 世界 | 3.1 | 3.4 |" stood in the document as one
    paragraph, above the real table that the same call had also given in tables."""
    one_line = '| 対象 | 2026 | 2027 | | --- | --- | --- | | 世界 | 3.1 | 3.4 | | 先進国 | 2.1 | 1.8 |'
    rows = [['対象', '2026', '2027'], ['世界', '3.1', '3.4'], ['先進国', '2.1', '1.8']]
    assert _table_blocks(['前文', one_line]) == ['前文', rows]
    assert _table_blocks(['|a|b||--|--||1|2|']) == [[['a', 'b'], ['1', '2']]]
    assert _table_blocks(['| a | b | --- | c |']) == ['| a | b | --- | c |']                 # no rule of cells: left as written
    assert _table_blocks(['| a | b | | --- | --- | | 1 | 2 | 3 |']) == ['| a | b | | --- | --- | | 1 | 2 | 3 |']  # rows do not add up
    # Given both as text and as a table: written once.
    result, document, _, _ = write(tmp_path, paragraphs=['成長率の見通し', one_line, '出典: Table 1.1'], tables=[rows])
    assert len(document.tables) == 1 and [[cell.text for cell in row.cells] for row in document.tables[0].rows] == rows
    assert [paragraph.text for paragraph in document.paragraphs] == ['成長率の見通し', '出典: Table 1.1']
    assert result['tables_converted'] == 0 and result['text_tables_dropped'] == 1 and 'tables argument only' in result['tables_note']
    # Given only as text: written as a table where it stands.
    (tmp_path / 'b').mkdir()
    result, document, _, _ = write(tmp_path / 'b', paragraphs=['成長率の見通し', one_line])
    assert result['tables_converted'] == 1 and 'text_tables_dropped' not in result and len(document.tables) == 1


def test_comma_separated_rows_do_not_stay_in_the_text(tmp_path):
    """Real-machine case: "項目,CPS,STEPS,NZE" and its rows stood in the document as text above the real table."""
    rows = [['項目', 'CPS', 'STEPS', 'NZE'], ['一次エネルギー供給 (EJ)', '838', '744', '654'],
            ['電力需要 (TWh)', '48,118', '45,109', '44,274']]
    copy = '項目,CPS,STEPS,NZE\n一次エネルギー供給 (EJ),838,744,654\n電力需要 (TWh),48,118,45,109,44,274'
    # A copy of the given table, in one paragraph or in several, is left out; thousands separators do not hide it.
    result, document, _, _ = write(tmp_path, paragraphs=['シナリオ別の見通し', copy, '出典: Annex A'], tables=[rows])
    assert [paragraph.text for paragraph in document.paragraphs] == ['シナリオ別の見通し', '出典: Annex A']
    assert len(document.tables) == 1 and result['text_tables_dropped'] == 1 and result['tables_converted'] == 0
    (tmp_path / 'b').mkdir()
    result, document, _, _ = write(tmp_path / 'b', paragraphs=['前文', *copy.split('\n'), '後文'], tables=[rows])
    assert [paragraph.text for paragraph in document.paragraphs] == ['前文', '後文'] and len(document.tables) == 1
    # The copy inside a paragraph: the text around it stays.
    assert _comma_tables(['表 1\n' + copy + '\n注: 2050 年'], [rows]) == (['表 1\n注: 2050 年'], 1)
    # Given only as text: three or more rows of equal width with figures become a table where they stand.
    (tmp_path / 'c').mkdir()
    text = '項目,2024,2035,2050\n石炭,"8,900",7200,4100\n再生可能,9800,17000,29000'
    result, document, _, _ = write(tmp_path / 'c', paragraphs=['前文', text, '後文'])
    assert [paragraph.text for paragraph in document.paragraphs] == ['前文', '後文']
    assert [[cell.text for cell in row.cells] for row in document.tables[0].rows] == [
        ['項目', '2024', '2035', '2050'], ['石炭', '8,900', '7200', '4100'], ['再生可能', '9800', '17000', '29000']]
    assert result['tables_converted'] == 1
    # The table stands between the paragraphs, not at the end.
    body = [child.tag.rsplit('}', 1)[1] for child in document.element.body if child.tag.endswith(('}p', '}tbl'))]
    assert body == ['p', 'tbl', 'p']


def test_text_with_commas_that_is_not_a_table_stays_as_written():
    for paragraphs in (
            ['First, we looked at coal, oil, and gas.', 'Then, in 2035, demand falls, slowly, everywhere.',
             'Finally, by 2050, the mix changes, a lot, in Asia.'],                    # sentences
            ['東京,大阪,名古屋', '札幌,仙台,福岡', '那覇,広島,神戸'],                      # equal rows, but no figures
            ['項目,CPS,STEPS', '供給,838,744'],                                          # two lines only
            ['項目,2035,2050', '供給,48,118,45,109', '需要,31,229,44,274'],              # thousands separators: rows do not add up
            ['a,b,c\nd,e,f', '1,2']):
        assert _comma_tables(paragraphs, []) == (paragraphs, 0), paragraphs
    # One line that happens to equal one row of a given table is not taken for a copy.
    assert _comma_tables(['項目,CPS,STEPS'], [[['項目', 'CPS', 'STEPS'], ['供給', '1', '2']]]) == (['項目,CPS,STEPS'], 0)
