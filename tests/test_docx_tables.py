"""A table written as text in docx_write's paragraphs becomes a real table where it stands."""
import asyncio
import sys
from pathlib import Path

from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.harness import PathHarness, ToolExecutor, _table_blocks


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
