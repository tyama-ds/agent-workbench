# Versioned development log

Historical PR handoff evidence, source/run/artifact links and exact snapshot provenance
are available in the [verification evidence index](evidence/README.md). The current PR
overview keeps only the latest head’s checks; archived claims retain their original scope.

## 0.1.1.dev90 — One thing at a time in the centre; a face for every agent (2026-11-18)

"The screen is split into too many panels and has become hard to read."
The centre stacked the run's numbers, the automatic team, the status of
every agent, the team diagram and the messages, each in its own box and
each with its own scrolling, and showed every agent four times (the list,
the status cards, the diagram, the detail).

- The centre shows one thing at a time. The buttons at the top are its
  tabs: 進み具合 (who is doing what, and the messages; where the screen
  opens), チーム図 (the diagram alone, with the room it needs), 掲示板,
  and 担当ログ. A link that leads to the messages opens 進み具合.
- The run's numbers and settings are one line away ("予算と設定の詳細")
  instead of three rows that are always there.
- Every agent has a face: 26 original drawings (18 people, 8 robots),
  built in the page from a few shapes, with no image files. They stand in
  the list, on the status cards, in the diagram and beside the selected
  agent's name. Each piece of work shuffles the faces by its id and deals
  them in the order its agents joined: one work keeps its cast, another
  work has another.
- The start screen and the settings are as they were.

Three manners of drawing (2026-11-18)

- Every face can be drawn as a flat illustration (the first set), in a
  shaded manner called リアル (light and shadow on skin, hair and cloth,
  eyes with lids, a nose, lips) and in an anime manner (a small chin,
  large eyes with lights in them, bangs). All three are drawings built in
  the page; none is a photograph or an image file.
- A piece of work is drawn in one manner, chosen by its id, so that works
  differ. "顔の絵柄" above the status cards fixes one manner for as long
  as the page is open; nothing is stored, and a reload returns to
  "作業ごとにおまかせ".
- Shadings (gradients) are defined inside each drawing under a name of its
  own: one defined in a part of the page that is not shown would not
  paint elsewhere.

## 0.1.1.dev89 — Looking at the screen (2026-11-18)

Desktop, first stage: an agent can be shown the screen. It cannot operate
it; that comes as a later stage, after this one has been tried on the real
machine.

- Off unless the human ticks "この作業で画面の閲覧を許可" on the start screen,
  for that one piece of work. There is no setting that turns it on, and
  the tick is taken off again after each start. It is its own choice,
  apart from operating pages in the browser.
- `screen_view` takes one picture of the primary screen (Windows, through
  GDI; no new dependency), made smaller so that its longest side is at
  most 1568 pixels. Nothing is clicked, typed or moved.
- Every look waits for the human, also in a piece of work that asks for
  no other approval: what is on the screen at that moment cannot be known
  beforehand. The request says that everything on the screen is sent to
  the agent's model. No answer in three minutes counts as "no".
- The picture goes to the model beside the tool result. It is not part of
  the conversation, the log, the events, the history or any file; only
  the latest look is kept, in memory, and sent while its result is still
  in the context. At most 30 looks in one piece of work.
- The model layer could send text only. Each kind of connection now
  carries a picture: Anthropic inside the tool result, OpenAI and local
  servers as one user item after the batch of results. The Copilot
  connection exchanges text only, so its agents are not offered the tool.
- A connection that turns the request with the picture away (HTTP 400,
  413, 415, 422) gets the same request once more without it, with a note
  that the screen was not seen; that agent is not offered another look.
- Not verified here: the capture itself on a real desktop with display
  scaling and several monitors (the Windows test job pictures the
  runner's screen), and which of the models in use accept pictures.

## 0.1.1.dev88 — Someone else reads what is handed in (2026-11-18)

"The coordinator is a dictator": it plans, gives out the work, accepts the
reports and declares the result good, and nobody else looks at what goes
to the human. An independent review existed only inside the strict mode in
which the application also forms the team, off by default.

- By default, before the root coordinator finishes a piece of work in
  which files were saved, one agent that took no part in the work reads
  them (read-only, outside the worker cap) and reports a verdict with
  findings. The coordinator finishes after it has the report, and is sent
  back once when the verdict asks for corrections and nothing was saved.
  The result says what the reviewer found and what was changed after it.
  The start screen has the checkbox, ticked; working without a reviewer is
  what one chooses.
- Operating pages in the browser can be chosen per piece of work, like
  Python.

Python for one piece of work (2026-11-18)

- Python could be turned on only for the whole installation, in the
  settings. The start screen now offers it per piece of work, like the
  browser window: it starts as the setting says (off unless turned on),
  and a run can have it on while the setting stays off, or off while the
  setting is on. It needs the python.exe set in the settings.

A list of things to make; the folder the request names (2026-11-18)

At dev85 the slides were missing and the run was "done" a third time.
The tester found the cause by running the request through the two
functions: `named_files` returned both names, `output_names` nothing.

- The request said "…次の2つを作成して提出してください。" and then
  "1. 要約レポート（weo2026_summary.docx）", "2. 説明スライド（weo2026_slides.pptx）".
  The word of making stood in the sentence before the list, and each line
  was looked at alone; and "1. 要約…" was cut at its own number. With older
  files of both names in the folders of earlier runs, nothing was
  expected, so nothing was missed: no send-back, no note, "done". A
  sentence that introduces a list as things to produce now holds for the
  names in the list's lines.
- Where the request names the folder to save to, a file of the same name
  in another folder is not "already there".
- The request of that run is a test now, with older files of both names
  beside it.

What a request asks to be made; a worker with nothing in hand; the report that came late (2026-11-18)

At dev84 the window got the October report (124 pages) at the address
that follows from the issue's page. Three things went wrong around it.

- The slides, asked for by name, were not made and the run was "done".
  Two ways out of the check were found and closed. Words of reading
  anywhere before the word of making ("要約から 8 枚程度で作成", "図表を
  使ったスライド") had turned a file to produce into a file to read; only
  what stands right behind the name now does. And a file of the same name
  lying directly in a permitted folder (an earlier run's folder that is
  itself a read folder) had counted as "what the request works on"
  whatever the request said.
- The worker that was to make the slides ended without one tool call. A
  worker that reports without the file its assignment names, or without
  having used any tool while requested files are missing, is sent back
  once.
- The report arrived at second 281 of 312; the document had been written
  before from a two-page summary, and the report was never opened. A
  completion that never read the work's largest PDF is sent back once.
  The coordinator's tool for creating workers now says to give a writer
  depends_on of those who gather its sources.

A heavy page is read when its document is there; the report at its own address (2026-11-17)

At dev83 the energy report came out nearly right: three files, 14 of 15
quotations on their pages, one page corrected by the application, one
invented quotation marked.

- The economic outlook's issue page failed for the third run, now with
  its reason: "Timed out receiving message from renderer". The driver
  waited for the whole page with every question. The window now takes a
  page once its document is there, stops a page that does not answer, and
  reads what had arrived.
- The report itself had still not been asked for after the page failed;
  saying so to the model had not been enough. Where a page is an issue of
  the World Economic Outlook, the application asks for that issue's report
  at the address that follows from the page's, once, as its own address.
- "STEPS｜CO2排出｜2035年に35…｜Gt｜p.176｜“…”" stood in a paragraph above the
  table with the same cells: rows set apart by bars or tabs are left out
  like comma-separated ones.

The page is written by the one who knows it; a busy window is not a closed one (2026-11-17)

At dev82 the newest copy was fetched and saved, the marks were written
(17 of them), and the coordinator, shown the right pages, changed none:
"…105 mb/d in 2035 (p.153)" stood on p. 123, "…peaks at 102 mb/d (p.123)"
on p. 171.

- Which page a passage stands on is a fact the application has. Where a
  quotation stands on exactly one page, the application writes that page
  into the document, the slides or the text file, and reports
  "p.153→p.123". Only a passage on several pages, or on none, is left to
  the coordinator and then marked; one that is not in the PDF at all is
  marked as such, in the sentence or row whose figure rests on it.
- "The window was closed before anything arrived" for an issue's page,
  right after a window had read the list. Every error while asking the
  window how the page arrived had been taken for a closed window. A page
  that is busy is now asked again until the wait ends; the reason is kept
  either way, with the job's records. No records of that run existed to
  look at: they were kept only for failed jobs.
- After a failed page the refusal now says that the report's own PDF
  address is still to be tried, and the policy says how to find it.
- A document without the table the request asks for is sent back once.
- Addresses in results lose their session values ("?t:state:client=…").

An id is not a hash; the issue after its list; a quotation is a passage (2026-11-17)

At dev81 the newest issue was found from the publisher's list, with its
dates, and the energy report's three files were saved and reported as
saved.

- The report then could not be read: `web_fetch` returned the id
  `pdf-23d1…4e` and, beside it, `sha256`; the agents passed "pdf-" plus the
  whole hash six times and were refused each time. Such an id, the hash
  itself, or a clear beginning of an id is now that PDF; a wrong one lists
  the ids of the work; the hash is returned as `content_sha256`.
- With the newest issue named, a supplement was fetched from elsewhere and
  the issue's own page was never opened. A list page's text does not say
  where its entries lead: its dated links are now returned, and the policy
  goes on to the issue's page and its full report.
- 26 of 40 quotations did not match. Many were terms of one to three
  words, which stand on many pages; they are no longer looked up. A range
  of pages matches any page in it. The send-back tells for each line the
  page to write, and what is still wrong afterwards is marked in the file
  itself as （ページ未確認）.

The day it is; a PDF to keep without a name (2026-11-17)

At dev80 the window saved the report from the publisher's site (180
pages), and the quotations were looked up (11 of 13 on their pages, two
named as on other pages).

- The report was the April issue, taken in November with an October issue
  out. The search had shown only April, and nothing had told the agents
  what day it was. The PDF guidance now gives the date the work began, and
  choosing the latest issue is four steps that start at the publisher's
  list of issues and do not end with the first search.
- "…and save the downloaded PDF in the same folder" named no file, so no
  file was missed: the folder had no PDF, the document said "obtained and
  saved in this work", and the run was done. A request to keep the PDF is
  a deliverable without a name, and the result says, from the
  application's own record, which PDF was saved or that none was.

What failed in the window; the PDF that was read; quotations looked up (2026-11-17)

At dev79 the energy outlook run produced its three files with figures that
matched, and the economic outlook run had no window at all.

- "The browser could not be started or did not finish: (Session info:
  MicrosoftEdge=157…)": the last line of the error. The kind of error and
  its message were cut away, and the private folder with everything else
  was deleted. A failed job now reports the kind of error, the step and
  the first words of the message, and its records (error, trace, the
  driver's log) are kept in a folder of their own. A page that cannot be
  read from the window ends the try with an answer instead of an error.
  One failed try no longer ends the window for the whole piece of work.
- The report quoted one copy of the document and an older copy was saved,
  twice, under two names; read by its path, the saved file was reported as
  "not downloaded in this work". `pdf_save` now asks for the copy that was
  read, saves a file once, and a saved download read by path is a download.
- "5,600 bcm by 2050 (p.119)" stood on pages 151 and 161, and one figure
  was not in the PDF. Before the coordinator finishes, the application
  looks up every quotation that stands with a page number in the saved
  files, sends back once what does not match, and says in the result what
  is still wrong.

Not known: why the browser failed. The next failure will say.

A refusal names the argument; one table is one table; the same PDF twice (2026-11-17)

The energy outlook run at dev77 chose the newest copy of the report and
read it, and produced no file.

- `docx_write` answered "Unsupported or missing tool arguments" seven
  times. The refusal now names the argument that is not one, the one that
  is missing, what the tool takes, and an example. `tables` that holds the
  rows of one table is one table; a cell may be a number.
- "[WinError 5] Access is denied: …pdf.tmp -> …pdf": the coordinator and
  a worker fetched the same report at once, and replacing the file the
  other had open was refused. A file of the same content is kept, not
  replaced; a refused replacement is tried again.
- The result listed the document among the files with cited sources
  although its save had failed every time: citations are noted before the
  write runs. Only saved files are listed.

The newest of several copies is the application's to say; a missing PDF is named again (2026-11-17)

The energy outlook run at dev76 ended `incomplete`, as it should: the
downloaded PDF was to be saved in the folder and was not. But `pdf_save`
was never called, and of five copies of the report the coordinator took one
dated November although it had looked at one from March of the next year.

- `web_fetch` `headers_only` returns the copies of one file name compared
  so far, newest first, and names the one to fetch; a download of an older
  copy says that a newer one was seen. The policy gives the choice as
  numbered steps.
- A completion without a requested file is sent back once for each set of
  missing files: after the document and slides were saved, the PDF alone is
  named once more, with `pdf_save` and the ids downloaded. The policy says
  to use `pdf_save` when the request asks to keep the PDF.

The outlook run at dev77 (191 s) then showed three more things.

- It ended `done` with an empty folder, the coordinator itself reporting
  that the two requested files had not been made. Files of those names
  stood in the folders of earlier runs under the same read folder, and a
  name that exists anywhere was taken for an input. A name the request
  asks to produce is now a deliverable all the same, and "saved" means new
  or changed since the request.
- "Browser try, success (page read)", and the next `web_fetch` of that
  address answered "already tried": the page never reached the agent that
  needed it. What a window brought is now returned again.
- The page's report was never opened: an older issue's file was refused
  first, which closed the whole site. A refusal now closes that address
  only, and a read page is followed in the same window by its own full
  report, which comes back with the page (`linked_pdf`). Links in
  `data-href` / `data-url` and links that only say "PDF" are found.

Not verified here: the real page's markup. The link rules were written
from the addresses reported, not from the page.

The report behind a read page; a worker without a report; 520 sent again (2026-11-17)

- One `HTTP 520` from the provider's front end ended an agent's turn, and the
  run then waited for a person for seven minutes without a question. 520-524
  join the statuses that are sent again (three times for a cloud profile,
  with backoff); when the re-sends are used up the message says how many
  there were.
- `docx_write`: "項目,CPS,STEPS,NZE" and its rows stood in a document as
  text above the real table. Comma-separated lines that repeat a given
  table are left out; a block that is a table of its own becomes one.
- The IMF run at dev76 read the issue's page in the window, then asked
  only for the size and date of the report it links to (`headers_only`),
  got HTTP 403 and took a two-page summary from elsewhere. A refused
  question now goes on to the file itself, and a PDF link of a page read
  in the window is opened from that page, in the same window, as the
  continuation of that try.
- The same run could not end: a worker had answered a re-request in prose
  and was "done" without a `finish_work` report; the coordinator could
  neither accept nor return what was not a report, and after three notices
  the run stopped as a deadlock. The coordinator's refusal now names the
  state and the way on; `review_worker_report` reopens such a worker
  (`revise`) or takes its last answer as the report (`accept`); a worker
  whose coordinator needs a formal report is reminded once; a deadlock's
  error says what was still open.

A run without its files is not "done"; the window saves the PDF it shows; documents can grow (2026-11-17)

Two runs on the real machine. The IEA's World Energy Outlook (PM and five
workers, 432 s): the PDF was found on the IEA's own storage and two workers
gathered figures with pages, but the document stayed three placeholder
paragraphs, there were no slides and no saved PDF, and the run said "done".
The IMF's outlook at dev75: the browser window now opened and showed the
PDF, five times, and saved none.

- The window: Edge showed the PDF in its viewer although the preference to
  download PDFs was set. The document the window shows is now read through
  the page's own fetch, with the window's session and from its cache, and
  saved as the download. Nothing else is requested.
- A run whose requested file was never saved ends as `incomplete`
  ("未完了（成果物なし）"), not `done`, in the list, the team view and the
  history; it becomes `done` when the file arrives.
- `docx_edit` could only replace the paragraphs that were there, so a
  document saved as a placeholder could not grow ("index must be an integer
  between 0 and 2", four times). It can now insert and delete paragraphs,
  and an index outside the document is answered with the paragraph count
  and the two ways on. Policy: no placeholder is saved first.
- `pptx_write` refused a body given as one text, four times, with "must be
  a list of at most 100 texts". A text is taken as its lines, numbers as
  their text, long lists continue on further slides, and a refusal says what
  was received and shows an example.
- `pdf_save` writes a downloaded PDF into a write folder as a new file.
- A worker that depends on others gets their accepted reports, copied by
  the application. The writer had answered that no confirmed evidence was
  in its conversation.
- Policy: the newest issue of a periodical is chosen by its publication
  date; of a report in several files the full report is fetched first.

Not verified here: the page's fetch of a shown PDF runs against a fake
driver; whether Edge's viewer page allows it is for the real machine.

## 0.1.1.dev75 — The browser window no longer fails on a helper that came and went; confirmed figures are taken over (2026-11-17)

dev73 on the real machine (`0903a73`): the headline figures were right and
came with page and quotation, and the slides were 16:9 with a chart and a
table. Four things were not.

- The browser window never came to be used: "Browser process history is
  incomplete (total=16, held=15, active=0)". The Job that holds the browser
  is looked at every 50 ms and a handle is kept for each process seen; at
  the end the number of handles had to equal the number of processes the
  Job ever had. A headed Edge with a new profile starts helpers that live
  for a few milliseconds, and one of them was never seen. That process was
  over. What has to be certain is that nothing still running is unknown:
  once the Job is sealed its running set can only shrink, so it is compared
  with the held handles that have not signalled. A running process that is
  not held still fails as before.
- The profile of that run stayed in the temporary folder. A retained folder
  is now removed at the next browser job once it is six hours old.
- A worker had read Table 1.1; the PM's table still said "not confirmed"
  for the countries, and one row held numbers that are in no table. Policy:
  a worker reports each figure with value, unit, page and quotation, the
  coordinator takes them over as they stand, and a table or chart holds no
  figure that nobody confirmed.
- The Markdown table stood in the document again, this time as one
  paragraph holding the whole table, above the real table from the same
  call. A table written on one line is recognised, and a text copy of a
  table that is also given in `tables` is left out.
- Asked to download the report, a worker read a copy that an earlier test
  had left in the folder, and nothing said so. `pdf_read` on a path now
  says that the file was not downloaded in this work, the policy asks for
  that to be stated in the deliverable, and the application lists under
  the report which PDFs were read and which of them it downloaded.

Not verified here: the Job logic runs against a fake of the Windows calls;
whether the window now opens, loads the address and saves the PDF is for
the real machine.

## 0.1.1.dev74 — The publisher's own copy of a report; a person passes a check in the window; tables in DOCX (2026-11-17)

The next goal on the real machine is the IEA's World Energy Outlook. Its
report page answers 403 behind a Cloudflare check to every HTTP library and
to a driven Edge, and shows a Turnstile box even in a person's own Chrome.
The PDF itself is served without any check from the IEA's own storage
(`iea.blob.core.windows.net`), where five files carry the same name.

- Policy: when a report's page is refused, search for the publisher's own
  copy (`filetype:pdf`, `site:` the publisher's domain) and fetch the PDF
  from where the publisher distributes it. Among same-named copies take the
  newest and say on what basis; an unrelated mirror only when no official
  copy can be had, and say so.
- `web_fetch` with `headers_only` returns the size and date the server
  states without downloading, so five candidates of 15 MB are compared by
  five small requests. A downloaded PDF's result carries that date.
- The browser window (off by default) no longer ends at a check meant for a
  person. It is closed, the human is asked through an approval that expires
  after three minutes whether they will pass it, and only then does the
  window open again and wait up to five minutes while they do; what follows
  the check is taken in. The application clicks nothing. A flat refusal
  ("Access Denied") is still final at once, and a human who declines is not
  asked again in that work.
- `docx_write`: a table written into the paragraphs as Markdown rows or as
  tab-separated cells is written as a real table at that place. On the real
  machine the Markdown rows had stayed in the document beside the real
  table, and in another run the table was tab-separated paragraphs.

Not verified here: no browser is started in the tests; whether the page
that follows a Turnstile check is recognised as such is for the real
machine (the worker waits while the title or short text is a check).

## 0.1.1.dev73 — Slides get a theme, a layout per slide, tables and charts, and text that fits (2026-11-17)

The same run on the real machine asked for "fashionable, modern" slides with
a chart or a table. It got nine 4:3 slides of the default template, each a
title and a list, no colour, no chart.

- `pptx_write` writes 16:9. A deck has a theme: `midnight` (dark, one bright
  accent), `paper` (white, bold headings) or `sand` (warm, a red accent);
  colours and fonts can be set separately, and a text colour too close to
  the background is refused.
- Each slide has a layout: cover, section, one big figure (kpi), two
  columns, a table, a chart (bar, column, line, pie: the format's own
  charts), or a list. A slide with a table or a chart takes that layout
  without being told.
- Text is measured against its box. It is set smaller down to a readable
  minimum; a list that still does not fit continues on following slides.
  The result lists what was changed, and a deck that is lists only is
  pointed to the other layouts.
- A chart keeps its numbers in the chart itself. The library would also
  embed a workbook for "edit data"; embedded objects are not allowed in the
  files this application writes or reads, so it is left out. `pptx_read`
  returns a chart's categories and numbers, so a deck can be checked.
- Titles stay title placeholders and a list stays the body placeholder, as
  before: an outline view, a screen reader and `pptx_edit`'s shape numbers
  go by them.
- The long description of `pptx_write` and the guidance on building a deck
  join an agent's instructions only once slides are part of the work, as
  with PDFs.
- A test of dev72 set `os.name` itself to 'nt'. On Python 3.11 that changes
  what every `Path()` is, and pytest ended with an internal error on the
  Linux 3.11 job. The test now tells only the one module.

Seen here: the three themes rendered through LibreOffice. Not seen: how
PowerPoint itself shows the charts without their workbook, and the fonts on
Windows (Yu Gothic UI is not installed here).

## 0.1.1.dev72 — A figure is found by its words and checked before it is reported; one try in a browser window (2026-11-17)

dev71 on the real machine: the 124-page World Economic Outlook, saved by the
human, was summarised into a document and slides in five minutes, and the
headline figures were wrong. World growth was given as 2.6 % and 2.7 % where
the text says 3.1 % and 3.4 %; the table had a third set of numbers; world
inflation was "not confirmed" although it stands on the same page; the
table's source was given as pages 39 to 44 instead of page 26 (printed 10).
The country figures were right. The request had asked for a check against
the PDF before finishing.

- `pdf_search` finds words, a table or row label or a number and returns the
  pages with what stands around the match (case and line breaks ignored).
  Reading a long report page after page is how the numbers were mixed up;
  `find` inside `pdf_read` was not used and is gone.
- Every page returned carries its position in the file and, where the file
  prints other numbers, the printed one (`page` 26, `printed_page` 10), and
  so does the outline.
- Policy for work with a PDF: find by search, read only those pages; each
  figure with its page and the words it comes from; one form of page
  citation; before finishing, look each headline figure up again and
  correct what differs, and never replace a figure that cannot be found.
  This guidance now joins the instructions only once a PDF is part of the
  work, which keeps other work's instructions shorter than before.
- `search.browser_fetch`, off by default, and the same choice per piece of
  work on the start screen: the owner wants to see, once, what an ordinary
  browser gets where `web_fetch` is refused. The address is loaded once in a
  visible window of the configured browser with a new profile; a PDF is
  saved into the job's private folder and taken in; the window is closed
  whatever happens. Nothing is clicked, nothing disguises the browser, and
  a check meant for a person ends the try. One try per address, five
  windows per piece of work, none for a site that turned the window away;
  each try is an event the human sees.

Not verified here: no browser is started in the tests (the worker runs
against a fake driver, the engine against a fake opener); whether Edge
saves the PDF with these preferences is for the real machine.

## 0.1.1.dev71 — Protected PDFs that open for anyone are read; nothing a PDF raises stops a turn (2026-11-17)

dev70 on the real machine (`7aa3e18`): the WEO's executive summary was
fetched from the IMF eLibrary and summarised with page numbers. Then five
Japanese ministry PDFs were tried and four could not be read.

- Two of them raised `DependencyError` inside pypdf (AES needs the
  `cryptography` library). That class is not one of pypdf's own errors, so it
  passed through `web_fetch` as an unexpected error and the PM's turn
  stopped. Two more were refused as encrypted. All four open in any viewer
  without a password: their authors only restricted changing, printing or
  copying. Refusing every encrypted file left most public documents of this
  kind unreadable.
  - A file that opens with the empty password is now read as a viewer shows
    it, and its overview says so (`protected`). A file that needs a password
    to open is refused, and no password is ever tried.
  - `cryptography` 50.0.2 is pinned with hashes (with cffi and pycparser).
  - Whatever the parser raises, on opening or later, comes back as the
    tool's error with its reason; where the library is missing the error
    says that.
- The model wrote "main points of chapter 1" although the chapter could not
  be downloaded, from the executive summary. Policy: a part that was not
  obtained gets one line saying so and no summary; and the human is asked
  once (with a recommended course, so an unanswered question does not stop
  the work) to save that PDF from their browser into a read folder, after
  which it is read by path.
- `stat_lookup` with the IMF returned nothing for the world. The World
  Economic Outlook keeps its aggregates under its own codes: WLD is asked as
  G001 and the euro area as G163, and advanced economies (G110) and
  emerging market and developing economies (G200) can be asked by name.

Not done here: a Markdown table left as paragraphs beside the real table in
a DOCX (next).

## 0.1.1.dev70 — PDF reports are read by page (2026-11-17)

The request: download the IMF's World Economic Outlook, read it and report a
summary; and the same for any long PDF report. On the real machine nothing of
this worked: `web_fetch` took text kinds only and stopped at 1 MiB, and no
file tool opened a PDF.

- `pdf_read` reads a PDF in an allowed read folder or one `web_fetch`
  downloaded. The first call gives the page count, the outline, characters
  per page and how the document begins; then pages by number, each under its
  page number, as far as the answer's size allows, with where to go on;
  `find` lists the pages on which a phrase stands. An encrypted file is
  refused. Pages without a text layer are named, and a file with none says
  that nothing could be read (there is no OCR).
- `web_fetch` keeps a PDF answer in the application's own folder under
  `limits.max_pdf_bytes` (50 MiB by default) and returns `pdf_id` with the
  overview. A page's links to PDF files are returned beside its text, which
  is how a report is reached from the page that describes it (the IMF
  eLibrary's book page links to the chapters' files).
- The run remembers which pages of a downloaded PDF were read. When sources
  are checked, a cited PDF is shown with them, and the PM is told that only
  pages read can be cited, each figure with its page.
- Policy: page count and outline first, the executive summary and the first
  chapter, then only what the request needs; every figure with its page; a
  refused site's own official distribution site (the IMF eLibrary) instead
  of repeating the request.
- Dependency, pinned with hashes: pypdf 6.21.4 (pure Python; 7.x was days
  old). It has no known advisory in PyPI's records today, and has had many
  about files that exhaust time or memory, which is why reading has a time
  budget and a file that does not end is not tried again.
- Two tests fixed their context budget as a number and broke when the tool
  list grew; they now measure it, as the one fixed in dev69.

Built and taken out again within this version: a second request with a
browser's TLS handshake (curl_cffi) for a site that answers 403 to an HTTP
library, as www.imf.org does. The owner first asked for it and then decided
against getting past a site's filter with a library. Nothing of it is in the
product or the lock. The standing rule is unchanged: the application does not
hide that a request is automated. What the owner asked for instead: anything
that operates a browser or the screen is a separate switch, off by default,
and is also chosen per piece of work on the start screen. Selenium page
operation (off by default) and browser search (only when chosen as the search
method) already are; a later "download through the browser" will follow the
same rule.

Not verified here: this environment reaches neither www.imf.org nor the
eLibrary. A Japanese PDF made here with a CID font reads correctly; the
ministries' own files were not tried.

## 0.1.1.dev69 — A change that cannot be formed is said, and a coordinator reads what its workers wrote (2026-11-17)

dev68 passed on the real machine at `f07437a` (latest month and quarter,
changes of an index for a quarter, forecasts marked, six suites done, a
spreadsheet of numbers only). Two things went wrong in the agent tasks.

- The lookup gave no change from a year earlier for the latest month of the
  consumer price index, because BLS never published October 2025. The model
  formed one itself, "1.0 % (2026-10 against 2025-10)", from a base that
  does not exist. Now `latest_period.change_percent` is always there for an
  index: a number, or null with `comparable`, the newest period that does
  have a change, and a remark naming the missing period. The policy says to
  use the change the lookup returns and not to compute one.
- Three workers were to fill one workbook. One reserved it; one was refused
  ("別の作業者がこの範囲を予約中") and wrote nothing; one wrote into another
  sheet. The file held two of three countries and the PM reported all three.
  - A refused reservation now names its holder and says what to do: report
    the values to the PM (preferred), or wait. When the reservation ends,
    the agents it turned away are told, so waiting is possible.
  - Before the root PM finishes, a requested file that teammates wrote and
    that the PM has not read since its last save sends the PM back once to
    read it and compare it with the request (as with tests that were asked
    for and not run). What the PM wrote itself needs no second look. An
    automatically formed team is left out: there an independent reviewer
    has read the saved file and accepted it before the PM may finish (the
    Edge acceptance of that flow failed until this was excluded).
  - Policy: one file has one writer; workers report their values and one
    agent writes the file and reads it back.

## 0.1.1.dev68 — The latest month and quarter, changes of an index, forecasts marked, and spreadsheet units (2026-11-17)

dev67 passed on the real machine (BEA six of six, BLS four, EIA five, the
Treasury two). In the agent task that collected five United States figures
and compared them with the World Bank, the workers went to the web for the
newest month and quarter, the change of consumer prices over the year stayed
"unconfirmed" because only the index came back, a crude oil forecast for the
current year carried no mark, and the spreadsheet mixed "94.37 USD/bbl" as
text, 0.034 for 3.4 % and 0.02793.

- `latest_period` beside the yearly values: the newest month for BLS, the
  newest quarter for the BEA (from `NipaDataQ.txt`, seasonally adjusted at
  annual rates). If the quarterly file cannot be read, the yearly figures
  still come back and `note` says so.
- BLS: a year with fewer than twelve published months has no yearly figure,
  and `note` now says how many months there are and which are missing.
- Index series (consumer prices, the PCE and GDP price indexes) carry
  `change_percent`, the change from a year earlier to one decimal, for each
  year and for the latest month or quarter, with the remark that the
  application computed it. A test compares it with BLS's published figures
  for the CPI-U: 8.0, 4.1 and 2.9 for 2022 to 2024 and 3.0 for September
  2025, from the published monthly indexes.
- EIA Short-Term Energy Outlook series: every year has `status` `actual` or
  `forecast`. The file's own last observed period decides where it gives
  one; the file read on the real machine gave none, so then the current year
  and later are forecasts, and `note` says which rule was used. IMF values
  of the current year and later have `status: forecast`.
- `xlsx_write`: every cell that holds a number with a unit as text is
  listed (it was the first of each column), also "3.4% (2026Q3)"; a year
  with a remark stays a label. Two or more values far below 1 under a
  heading about a rate or percent are pointed out as probable fractions.
- Policy: the unit once in the heading, bare numbers in the cells, the same
  form for every source compared; what `latest_period` and
  `status: forecast` mean.
- Python sandbox (Windows): while a script runs, its workspace is scanned
  every 50 ms for size and for hidden streams. A scan that met a file in the
  moment it was saved, renamed or deleted failed, and the run was ended as
  `workspace_changed` with nothing wrong. CI hit this in the real sandbox
  test, with a script that saves a .docx, an .xlsx and a .pptx. The scan is
  now made again up to five times (about 0.15 s) before its failure is taken
  as real, as the browser job has done since dev56; the scan after the
  script has ended stays strict.
- **Not seen answering**: `NipaDataQ.txt` (assumed beside `NipaDataA.txt`,
  same columns, periods like 2026Q3) and the name of the field in the EIA
  file that gives the last observed period.

## 0.1.1.dev67 — United States government statistics: BEA, BLS, EIA and the Treasury (2026-11-17)

dev66 was confirmed on the real machine for all five providers (IMF 3 to 4
s, OECD about 9 s, Eurostat about 10 s, ILO about 54 s). The human then asked
for United States government statistics. Without a key, from that machine:
the BEA's bulk file `NipaDataA.txt` (12 MB, 7 s), the BLS API v1, the EIA's
bulk zips (`TOTAL.zip` 3.2 MB, 4 s) and the Treasury's fiscal data API
answered; the BEA, Census and EIA APIs need a key; FRED timed out.

- `stat_lookup` sources `bea`, `bls`, `eia`, `treasury`, for the United
  States only (another country is refused with that reason).
- BEA: gdp, real_gdp, gdp_growth, gdp_price_index, personal_consumption,
  pce_price_index, or a series code. One series is read out of the whole
  file by its exact code.
- BLS: unemployment, cpi, payrolls, labor_force_participation, or a series
  id. The series are monthly: a year is the agency's own annual figure where
  the series has one, otherwise the mean of its twelve monthly values
  (marked `months: 12`), and only complete years are given; the latest
  month is in `note`. Keyless BLS answers few requests a day, so an answer
  is kept for a day and a refused request is not repeated.
- EIA: energy_consumption, energy_production, electricity_generation from
  `TOTAL.zip`; crude_oil_price and brent_oil_price from `STEO.zip`, whose
  forecast years are marked `forecast: true`. The zip is read in memory, one
  line at a time, with the same checks as the World Bank's.
- Treasury: government_debt and debt_held_by_public, the amount on the last
  reported day of each year with its date.
- A provider's answer that was received but cannot be read is no longer
  requested a second time (it would be the same answer).
- **Not run from this environment.** Seen on the real machine: the four
  addresses and the first lines of the BEA file. Not seen: the BEA series
  codes other than the example line, whether the BLS v1 address honours
  `startyear`/`endyear`, the EIA file's line format and the series ids
  (TOTAL.TETCBUS.A, TOTAL.TEPRBUS.A, TOTAL.ELETPUS.A, STEO.WTIPUUS.A,
  STEO.BREPUUS.A), and the Treasury `fields`/`filter` parameters. A series
  that is not in a file is an error naming it, never another series.
- Not in this change: Census, and optional keys (BEA, Census, EIA, BLS).

Two small things from the agent runs at `920dee1` (all passed: 18 of 18
lookups in a three-provider comparison, 2 of 2 for Eurostat):

- The OECD `page_url` was the Data Explorer's front page. It now opens the
  table and selection that were read
  (`…/vis?df[ds]=dsDisseminateFinalDMZ&df[id]=<table>&df[ag]=<agency>&dq=<key>`,
  with brackets, `@` and `+` encoded).
- A statistics task rewrote its table under a new sheet name and the file
  kept the old sheet beside the new one. `xlsx_write` only sets cells, so
  nothing could delete a sheet. It now takes `remove_sheets`, and a write
  that adds a sheet while an earlier sheet with content is left untouched
  says so and names the way to remove it.

## 0.1.1.dev66 — The IMF's periods, several records of one ILO series, a refusal that is temporary, and the OECD (2026-11-17)

dev65 was tried on the real machine for Japan, the United States and
Germany, four indicators, four providers. The World Bank and Eurostat
answered correctly. The IMF returned no values for any country although its
answer held 52 observations; the ILO took 51.8 seconds and then failed with
"2 different series for JPN (they differ in: )", after which the machine
got HTTP 403 from sdmx.ilo.org.

- IMF: the answer names a time period as `{"value": "1980"}`, without an
  `id`. Only `id` was read, so every period was empty and every observation
  dropped. Both are read now; the test fixture has the real shape.
- ILO: one country per request with `lastNObservations`, the shape that
  answered in two seconds (several countries with a period filter needed
  more than thirty, so the first try timed out). Requests are three seconds
  apart.
- Several records of one series whose dimensions are all equal are one
  statistic kept more than once (the ILO keeps one per national source).
  The record with the most recent year is used, and `note` says so and
  shows the attributes that tell them apart. Series that differ in a
  dimension stay an error, now showing the values; where an indicator says
  which value of an open dimension it means, that one is taken.
- HTTP 403 or 429 from a provider is reported as a temporary refusal, not
  as missing figures; nothing more is sent to that provider for ten minutes.
- OECD (`source: oecd`): unemployment, GDP growth and consumer price
  inflation, with the three keys that answered on the real machine
  (SDMX-CSV with labels). Japan is absent from the consumer price series
  there and comes back under `no_values`. No OECD population: the dataflow
  tried returned 404.
- **Still not run from this environment.** The OECD CSV's column names are
  as SDMX-CSV defines them; whether the open dimensions of the unemployment
  and GDP growth keys return one series per country has not been seen.

## 0.1.1.dev65 — stat_lookup with a source: the IMF, Eurostat and the ILO beside the World Bank (2026-11-17)

The human asked for statistics from more providers than the World Bank. From
the test machine, without a key: the IMF's SDMX 3.0 API answered in 1.4 s,
Eurostat in 2.3 s (JSON-stat), the ILO in 2.3 s (SDMX-ML); the IMF DataMapper
API was refused (403), UNdata failed (500), Destatis timed out, and e-Stat,
Census, BEA and FRED need keys.

- `stat_lookup` takes `source`: `worldbank` (default), `imf`, `eurostat`,
  `ilo`. The same plain indicator names work wherever a provider has the
  series: IMF World Economic Outlook (population, GDP, GDP growth, GDP per
  capita, inflation, CPI, unemployment, government debt, or any WEO code),
  Eurostat (population, GDP growth, inflation, unemployment, government
  debt), ILO (unemployment, youth unemployment).
- Every result, the World Bank's too, now carries `source` (the id),
  `source_name`, `unit`, and `as_of` with `as_of_basis`: the provider's own
  update time, or the day the figures were retrieved when it gives none.
  `indicator.name` is the provider's own label of what was read.
- A provider's answer with several series or categories for one country,
  none of them the one the indicator means, is an error that says what
  differs. A number is never picked among candidates.
- One request at a time; answers that could be read are kept for a day; a
  failed request is tried once more unless the provider refused it.
- The policy tells the model to compare countries within one source, to
  prefer a country's own statistical office for its own figures, to report
  both values with source and date when sources differ, and that units
  differ (the IMF gives population in millions).
- **Not run against the real providers from this environment** (none is
  reachable). The address shapes are the ones that answered on the test
  machine; the answers' layouts are read as the standards describe them. The
  Eurostat table codes and the categories chosen in them, and the ILO key
  for youth unemployment, have not been seen answering.
- Not in this change: the OECD (no series key is known to answer; guessing
  one risks a wrong series under a right name), the ECB, UN SDG, national
  statistical offices' files, and optional keys.

## 0.1.1.dev64 — Nobody to wait for: a coordinator that works alone, and a worker whose coordinator waits (2026-11-17)

From the real-machine suite at `503253a`: a research task's PM worked alone
(no worker was created). Search was used up (two bot checks had lowered the
allowance from 120 to 30) and 25 of 28 page fetches failed, several with HTTP
202 from one site. At 273 seconds the PM called `wait_for_message`; the run
stayed "waiting / peer_message" past 900 seconds with no notice and nothing
saved. `stat_lookup` at `d0e9b23` was confirmed there: six of six lookups in
1.3 seconds together.

- The refusal of a wait that nobody can end (dev55) and the stall notices
  required the coordinator to own workers. Both now hold for any agent:
  `wait_for_message` is refused, once per turn, whenever no other member of
  the run is working, startable or waiting for a human. A coordinator
  without workers is told to finish with what it has and to mark what could
  not be confirmed; a worker whose coordinator only waits for its report is
  told to report, or to say what it needs and then wait.
- A coordinator without workers that waits anyway now gets the three stall
  notices and is then stopped with its own reason.
- A worker that has sent its coordinator a question may still wait: the
  coordinator has mail to read, so somebody can act.
- `web_fetch`: HTTP 202 is named as what it usually is, a browser check the
  site runs before it sends the page, with the advice not to retry that
  address. The application does not pass such a check. Why that site answers 202 could not
  be examined from this environment (it cannot reach the site).

## 0.1.1.dev63 — stat_lookup reads the World Bank's bulk file (2026-11-17)

`stat_lookup` at `503253a` was tried against the real API from the test
machine: all four calls ended in "timeout waiting for the response (20 s
limit)". Measured there with curl: an address the JSON API had served before
answered in 0.13 to 0.17 s; a new one took 34 s or ran past 60 s (six of six),
and answered in 0.17 s a few minutes later. The bulk download of one indicator
(`/v2/en/indicator/<code>?downloadformat=csv`, a 140 KB zip with every
country and year) always answered in 0.15 s. The IMF DataMapper API returned
403 from that machine and is not used.

- The bulk file is the source. Countries and years are picked out by the
  application; another lookup of the same indicator costs no request.
- The unchanged zip is kept for 24 hours in `stat-cache` under the state
  folder and read through the same checks each time. When no newer file can
  be had, an older copy still answers.
- The archive is unpacked in memory only: every entry must be a plain file
  name (no folders, no `..`), at most 16 entries, 8 MiB zipped, and no more
  than 24 MiB is read from the table whatever the archive declares.
- The JSON API is the fallback when no file can be read: one country at a
  time, 75 s wait, one retry after 5 s, about 170 s in all; countries it did
  not read are named.
- `read_from` in the result says which address was actually read.
- **Not run against the real World Bank from this environment** (it cannot
  reach it): the file's layout is as the test machine described it and as the
  World Bank documents it.

## 0.1.1.dev62 — Statistics read directly, a search guide, and a human check that does not wait for ever (2026-11-16)

From a real-machine load run at `2d07f9f` (information gathering and
statistics three times each, about 50 minutes). The higher allowance and the
per-run share worked (33/33, 58/58, 17/17, 56/56 searches answered). What it
showed next: one statistics task sends 56 to 58 searches and one research
task 17 to 33; duckduckgo.com in a browser asked for a human check after
about 165 searches in 45 minutes, so the default of 200 an hour was out of
reach; and with nobody at the machine the request to pass that check held
the run until it was cut off at 901 seconds, with stats.xlsx already saved.

- `stat_lookup` reads country statistics from World Bank Open Data
  (`api.worldbank.org`, no key): one indicator, up to 12 countries, a range of
  years, with the address to cite. Built-in names cover population, GDP, GDP
  growth, GDP per capita, consumer prices, unemployment and a few more; any
  World Bank indicator code is accepted. The policy tells the model to use it
  before searching. **Not run against the real API**: this environment cannot
  reach it, so the answer's shape is from the API's documentation.
- `search.run_guide` (default 20, 0 none): the policy says how many searches
  one piece of work is expected to need; from half of that each answer says so
  and asks to go on with what is held, and past it asks to stop. A guide, not
  a limit; the run's hard share stays half of the hourly allowance.
- Browser search: 120 an hour by default (was 200), 4.5 s between searches on
  duckduckgo.com (was 3).
- A query practically equal to an earlier one of the same run (at least 65%
  of the words shared, and the differing words neither numbers nor country
  names) is answered once from the earlier result, marked `similar_to`.
  Sending exactly the same query again searches. Before, only the same set of
  words was shared; different wordings by several workers each cost a search.
- `run.search_use` and the run's "Web の利用" line show searches sent, answers
  reused, similar questions answered and statistics read directly, so the
  effect can be measured on the real machine.
- The request to pass a bot check expires after three minutes and then counts
  as declined. `web_search` is refused for the rest of that run without
  sending anything, the caller is told at once and every agent at its next
  turn; `web_fetch` and `stat_lookup` keep working. The card shows the
  deadline. Other approvals still wait.
- Tests: `test_pm_accepted_dependency_handoff_runs_real_file_workflow` failed
  on a Windows runner that took 41 minutes for the suite instead of about 20.
  Its three-second waits only tell a hang from progress; they are 20 seconds.

## 0.1.1.dev61 — Bing is off unless the human turns it on; acceptance failures say why (2026-11-16)

The human decided the terms question for browser search: DuckDuckGo is fine.
Bing was not part of that decision, and on the real machine it asked for a
verification from the second search on, so leaving it out costs nothing.

- `search.browser_bing` (default false; settings: 「ブラウザー検索の予備に Bing
  も使う」). Off: browser search uses duckduckgo.com and then DuckDuckGo's
  HTML page. On: Bing is tried between them, as before.
- No terms notice is attached to DuckDuckGo. The README's general sentence
  about engines' terms is replaced by one about Bing next to its switch.
- Edge acceptance: the adaptive script printed only `ok:false`; its report
  is a build artifact that cannot be fetched from every environment. It now
  prints the reasons. The first failure read this way was "Read-only
  process census exceeded 10000ms": `powershell.exe` asking WMI for the
  process list took longer than ten seconds on a shared runner and then
  ended normally. The wait is 60 seconds and each census records its time.
- Edge acceptance, "task dialog stays open after start" (seen now and then
  since dev53, cause still unknown): the page had the server's acceptance
  and was waiting to see the run in the list. A failed run now reports the
  page's last `/api` requests with durations, a direct state request, and
  where the test server's loop was whenever it did not answer for two
  seconds, so the next occurrence tells a silent server from a page that
  stopped updating.

## 0.1.1.dev60 — Search allowance by method, a share per run, and a warning before it runs out (2026-11-16)

Browser search worked on the real machine (35 of 35 searches in one research
task, no bot check). The allowance of 60 searches an hour for the whole PC
did not: one research task sends about 35 searches and a statistics task 23
to 31, so every task after the first two failed within seconds, with values
left unconfirmed and loosely related sources. Nothing had ever been stopped
at that rate.

- The allowance is per search method: browser 200 an hour, DuckDuckGo over
  HTTP 60, Brave 120, a SearXNG server of the human's own none (dev59 had
  wrongly capped it at 60 too). `search.hourly_limit` replaces the number for
  the chosen method; 0 keeps the method's own.
- After a bot check the method's allowance is halved for the next hour, and
  quartered after two or more, never below 10.
- One run may send half of the allowance, so a single task cannot use up
  the hour for the others.
- Every `web_search` answer that cost a request carries
  `search_budget.searches_left`; in the last fifth (at least the last five)
  it also carries a plain notice to keep the remaining searches for what
  matters most. Before, the model learned of the limit only when it was hit.
- Answers already held are still not counted.
- `xlsx_write` also warns about a number saved as text because a unit is
  attached ("2.8 percent", "1億2269万人", "¥1,200"); labels that only start
  with digits (a year, a date, a rank) are left alone.

## 0.1.1.dev59 — Keyless browser search, one search queue, a cache that outlives a run (2026-11-16)

After the Accept-Encoding fix the first three DuckDuckGo searches of a run
succeeded and the fourth, 24 seconds in, was challenged; from then on the
address was paused. Keyless HTTP search cannot carry workers that search in
parallel (20 to 30 searches per task), and an API key is not an option for
this user.

- Browser search (`search.provider = browser`). `web_search` opens a search
  engine's result page in the browser configured under Selenium, through the
  existing Windows Job runner, and reads titles, URLs and snippets from the
  page's HTML on the application's side. The model gets the usual
  `{query, results}`; it cannot steer the browser. Engines are tried in
  order: duckduckgo.com as a browser renders it, then Bing, then DuckDuckGo's
  HTML page. Each has its own pacing and its own ten-minute pause after a
  bot check, separate from the keyless HTTP method's pause. The order follows
  a check on the real test machine with an ordinary window: duckduckgo.com
  answered ten searches in a row (2.5 s apart) while HTTP requests from the
  same address were refused; Bing answered once and then asked for a
  verification every time; a headless window got DuckDuckGo's check at once.
  A page without result rows that carries a verification text (for example
  "bots use DuckDuckGo", 「課題を解決してください」) is a bot check, not
  "no results".
- The browser runs as an ordinary window kept off the visible screen (not
  headless) with a profile of its own that the application keeps under its
  state folder, so cookies survive between searches. The human's own profile
  is never used. Nothing hides that the browser is automated.
- It needs the browser, driver and Python executables from the Selenium and
  Python settings, but neither `selenium.enabled` (the page-operation tool for
  agents) nor Python's network permission.
- A bot check is never solved by the application. When every engine asks for
  one, the tool call waits on an approval card: on approval a visible window
  opens on the search page and the application waits up to five minutes for a
  person to pass the check, then finishes the search. One check at a time for
  the whole application; teammates that hit the same wall wait and then
  search again. A human who declines is not asked again in that run.
- All search methods: an answer already held is reused for the same query
  and for rewordings of it (width, case,
  spacing, punctuation and word order are ignored); answers are kept on disk
  for six hours and reused across runs (keys are hashes of the normalised
  query, so the file does not list what was asked); this PC sends at most 60
  searches to search services per hour, counted across runs and restarts.
  The keyless methods (browser, DuckDuckGo) also send one search at a time
  per run; a SearXNG server of the human's own or a keyed API is not held
  back.
- Not verified here: reading the real result pages (the readers were built
  from fixtures and from the selectors the tester reported), the off-screen
  window on Windows, and the human-check flow in a real browser.
  Automated use of a search engine's pages may be against that engine's
  terms; the human decides whether to use this method.

## 0.1.1.dev58 — DuckDuckGo searches return results: no "gzip, deflate" beside a browser identity (2026-11-16)

Every DuckDuckGo search on the real test machine had returned 0 results
(HTTP 202, bot check). The tester isolated the cause on that machine, with
the same POST at the same time: aiohttp's automatic
`Accept-Encoding: gzip, deflate` next to the Chrome User-Agent got 202 every
time; without the header, or with `identity`, the same search returned 10
results. The address was never blocked.

- Every web request (search and page fetch) now states
  `Accept-Encoding: identity`, so aiohttp adds nothing of its own. This
  client cannot decode `br` or `zstd`, which a browser would also offer.
- A challenge page that arrives with HTTP 200 raises its error where it is
  detected, before anything could count as a success; the block stays.
- Not verified here: the effect on page fetches (403 from some sites may
  have had the same cause), and whether the ten-minute pause after a bot
  check is still needed now that the cause is known.

## 0.1.1.dev57 — An ended worker's unmet dependency no longer holds the run (2026-11-16)

- Regression from dev56, seen on a real machine: a worker that depended on
  two others never started; the PM approved one report and finished, and the
  application closed the remaining teammates. The stopped worker still had an
  unmet dependency on record, and the run status counted it, so the run
  stayed `waiting` although every agent was done or stopped. A stopped
  teammate, or one the application closed at its coordinator's completion, no
  longer counts as waiting for a dependency (run status and its reason).
- When a named deliverable is missing, the notice names the tool for its kind
  (`docx_write`, `xlsx_write`, `pptx_write`, otherwise `write_text`) and says
  not to build Office files through `python_execute`.
- `python_execute` file-mapping errors name the argument and the value
  (`outputs[0].name '...'`, `inputs[1].path '...'`) with what that argument
  must be; a missing destination folder says to create it first.
- The activity log keeps what each tool was called with (paths and names in
  full, long text as its start and length) as the first key, `called_with`,
  of the logged result. The line format (tool name, newline, result JSON) is
  unchanged, and the model's own tool result does not carry the summary.

## 0.1.1.dev56 — A coordinator nobody can wake is told what to do, then stopped (2026-11-16)

Real-machine case: the PM's `finish_work` was refused because worker reports
were not approved; it then called `wait_for_message` although every worker
had ended, and the run stayed `waiting` until it was cut off after 15
minutes. Three causes, all fixed:

- A worker the application closed when the PM first tried to finish (it had
  only waited, or never started; not one that failed) could never have an approved report, so a
  plan with `depends_on` could not be finished at all. Such teammates no
  longer count towards the reports a coordinator must receive and approve.
- The stall check returned early when no worker was left alive, so only the
  first notice was ever sent. It now continues to 2/3 and 3/3 and then stops
  the PM with a visible reason. The notice names the concrete next step taken
  from the application's records.
- A root PM's `wait_for_message` is refused (once per turn) when nobody is
  left who could send anything, with that same next step. A model that waits
  anyway is handled by the notices, never by an endless loop.
- The `finish_work` refusal lists each report still to approve with the
  worker's name, `worker_id` and `result_revision`.
- `xlsx_write` returns a `warning` when one column of a call holds both a
  percentage stored as a fraction (`'0.9%'` → 0.009) and a plain number
  (2.16); the file is saved and the PM is asked to use one unit.

## 0.1.1.dev55 — Named deliverables and cited sources are checked at completion (2026-11-16)

From a real-machine research run in which search returned nothing, one page
could be fetched, and that page (about another subject) was cited as the
source of the report. Until now the application checked only that a cited URL
had been retrieved.

- The run remembers how each page a web tool returned begins (90 characters;
  a fetched page's own text, or only a search result's title).
- Before the root PM finishes, once per run and only when web tools are
  available and a saved document cites retrieved URLs, the PM is sent back
  with each citation beside that evidence: the page's first words, "only seen
  as a search result", or "no page text was retrieved". It is asked to remove
  or relabel any citation the page does not support.
- The PM's result ends with the same list for the human, stating that the
  application has not judged whether the pages support the claims.
- The system prompt (web runs only) says to cite a page only for what its
  retrieved text states.
- The application still does not compare a claim with a page's text; the
  judgement stays with the PM and the human, who now see the evidence. After
  a real-machine run in which the PM kept an unrelated page, the notice now
  says to delete such a citation or fetch a page that covers the point.
- Named deliverables. A real-machine run ended `done` with an empty output
  folder: the PM rejected a correct report and finished without creating the
  requested `stats.xlsx`. A file the request names (a bare ASCII name or any
  quoted name with a document, data or code extension; not inside a URL) that
  does not exist when the run starts is a deliverable. Saves are recorded by
  name. A root PM that finishes while one is neither recorded nor on disk is
  sent back once (`outputs_missing`); after that the result ends with the
  application's record that the file was not made, and the run shows
  「依頼されたファイル」 as a metric (`run.output_check`). A file that already
  exists is treated as an input.
- `xlsx_write`: a decimal such as `'0.239578342117881%'` stayed text because
  its leading `0.` was counted towards the 15-digit limit, leaving one column
  with numbers and strings. Only a whole part longer than 15 digits keeps a
  value as text now.

## 0.1.1.dev54 — Runs that end, working web search, sandbox hints and tests (2026-11-16)

Phase 9, from real-machine runs of coding, research, statistics, slides and
spreadsheet tasks (gpt-5.4-mini).

- A run ends when the work is done. When a coordinator gives its final answer
  (`finish_work`, or plain text without it) and no teammate under it can still
  act, teammates that only wait for a message, never started or failed are
  closed (`team_settled`), so the run becomes `done` instead of `waiting`.
  Teammates that are working, queued or waiting for a human still hold the
  report back. A worker that starts waiting after the final answer closes the
  team then. A PM that waits for reports while every worker only waits for a
  message is told so (twice at most).
- Cited URLs: the run remembers URLs from the request, human messages, web
  tool results, files it read and scripts it ran. A document write (not source
  code) citing other URLs is refused once when web tools are available, and a
  visibly made-up URL (long zero runs, xxxx, template marks) is always refused;
  what is saved anyway is listed for the human at the end of the PM's result.
  The system prompt says to cite only URLs a tool returned (web runs only).
- Web tools: DuckDuckGo searches are a form POST with browser headers (every
  search had returned HTTP 403); a bot check or refusal is reported as such,
  never as an empty list. Page fetches use the same headers, accept long
  response headers, try up to three resolved addresses and name the failure
  class. `web_read` caps an oversized `limit` and its errors say what is
  accepted and what was received.
- `python_execute`: a failed run gets a `hint` for the common sandbox
  failures (a host path opened in the script, with the `inputs` shape to use;
  subprocess; network; missing module; timeout). The working directory is now
  importable. `import awb_pytest; raise SystemExit(awb_pytest.run())` runs
  tests inside the sandbox: real pytest with plugin autoload, cache, fd
  capture and outside temp dirs switched off, under a deadline; if pytest does
  not start in time the helper dumps all thread stacks and falls back to a
  built-in simple runner, so the call always returns a result.
  Not yet run on Windows LPAC.
- Second real-machine round. A team in which everybody waits and no mail is
  undelivered (a PM that asked for a correction and waits, a worker that read
  it and waits too) is detected at the end of each turn: the PM is told who
  waits and what it can do (three notices, then it stops with a clear reason
  instead of waiting silently). A worker that received a correction may not
  `wait_for_message` before acting (refused once). `awb_pytest` treats a path
  it may not examine as absent (the sandbox may not stat the parent of its
  working directory, which made pytest fail while collecting) and falls back
  to the simple runner when pytest cannot collect anything. DuckDuckGo
  searches are spaced two seconds apart, the same query is sent once per run,
  and after a bot check no search is sent for ten minutes; the start check and
  the settings say so and point to SearXNG. Text tools name the right tool for
  .xlsx/.docx/.pptx.
- Third real-machine round (8 of 8 runs ended `done`).
  `run_tests({paths})`: the application copies the given files or folders into
  the sandbox (layout kept below their common folder, `src/` importable, no
  caches or virtual environments, at most 200 files) and runs `awb_pytest`
  there; nothing is written back. Offered to the PM and every worker,
  including read-only ones, wherever Python may run; it follows the Python
  approval setting. Every test run (this tool, or `python_execute` output with
  an `awb_pytest:` summary) is recorded (`tests_run` event, `run.test_check`).
  When the request asks for tests to be run, the root PM's completion is sent
  back once if no run passed, and the result always ends with the
  application's own record (passed / last run failed / never run), also shown
  as a run metric. Without Python the missing run is reported, not retried.
  Brave Search returns as an optional engine that uses the human's own API
  key; the default stays keyless DuckDuckGo and SearXNG is unchanged. Its
  endpoint is fixed, the key is kept for the session or in the encrypted
  store under a fixed binding (never in settings, history or the
  environment), sent only as `X-Subscription-Token` to that origin, and
  accepted only while Brave Search is the saved engine. A retired Brave
  configuration (another endpoint) still becomes DuckDuckGo. The start check
  points to this option while DuckDuckGo is blocking, and warns when Brave
  is selected without a key. Not yet run against the real Brave API.
  `xlsx_write` stores a numeric string (`'123,366,734'`, `'12.5%'`, `'42'`)
  as a number with a matching format; leading zeros, 16+ digits and a leading
  apostrophe stay text.
- Questions that wait for a person (no recommendation, or `kind=permission`)
  are for the root PM only and limited to two per run; others become
  consultations when they carry a recommendation, or are refused with
  guidance. The `ask_user` description says a failed tool is not a permission
  matter.

## 0.1.1.dev53 — Mandatory plan and application-run turns (2026-11-15)

Phase 8. Goal: a request such as 「5人でしりとりを10回」 runs to the end on a real
machine, with the application (not a model) granting and checking each move.

- `plan_work` is mandatory for every root PM in a non-adaptive run. Until a
  plan is accepted the PM is offered only `plan_work`, `ask_user` and read-only
  tools, and every other tool is refused. Shapes: `solo` (PM works alone;
  worker tools removed), `parallel` / `sequence` (two or more assignments with
  key, role, goal, deliverable, acceptance; a single assignment, a goal equal
  to the request, placeholders, unknown or cyclic `depends_on` are rejected),
  and `turns`. A PM that answers in prose before planning is asked for the
  plan (twice at most). A しりとり request must use `turns`.
- `turns{participants, rounds, rule, topic, first_word?, save_as?, profile_id?}`:
  the application validates capacity (worker cap, turn and model budgets),
  creates the participants itself (`参加者1..N`), and runs the game
  (`workbench/turns.py`, `workbench/turn_engine.py`). The legacy
  `start_ordered_work` path and its `participant_key` / `initial_wait`
  arguments are not offered in plan mode, so they no longer clash with
  `depends_on`.
- Each participant is offered only `submit_turn` and gets a short system
  prompt without the original request. One turn = one move. `shiritori`
  checks one hiragana/katakana word, the link to the previous word (long mark
  skipped, small kana as large), no ん ending and no repeats. A rejected move
  returns the reason; three in a row record a pass. A plain-text reply is
  checked the same way. A participant that errors or is stopped is passed, so
  the chain never waits; a whole round of passes ends the game.
- The PM waits without model calls while turns run and cannot write files or
  moves. When all turns finish, the application optionally saves the record
  (`save_as`; xlsx/csv/md/txt, never overwriting) and notifies the PM, who
  reports with `finish_work`; the result ends with the application's counts.
  `export_turn_history` saves the same record on request. Turns spend no
  automatic-collaboration budget and need no worker reports or reviews.
- Also fixed: a probed Local context window is used only when the bare
  request fits with a 2 bytes-per-token allowance (a server reporting 16k–32k
  no longer stops the PM before its first call); an ordinary rate-limit body
  that mentions a billing URL is no longer treated as quota exhaustion; a new
  workbook's automatic empty `Sheet` is removed when other sheets are
  requested; a worker waiting for approval counts as progressing for
  `wait_for_workers`.
- Tests and scripted fixtures run without the plan gate unless marked `plan`
  (`tests/conftest.py`, `tools/*fixture.py`).
- After the first real-machine runs (gpt-5.4-mini): a sent-back move now lists
  the words tried in this turn, the used words starting with the required
  kana, and every word refused for ending in ん (kept for the whole game and
  shown in each later turn message). A participant gets four attempts, the
  last with an explicit prompt, before a pass. After two passes in a row the
  next participant restarts with any unused word (recorded as 受理（再開）), so
  one dead-end kana cannot end the game.
- The new-task worker cap starts at the saved cap instead of the HTML default
  3, and a request naming more people than the cap (「5人」) shows a
  non-blocking note before the run starts. `save_as` defaults to the example
  name `turn_history.xlsx` in the tool description.

## 0.1.1.dev52 — Approvals, team memo, past-work search and fallback models (2026-11-15)

Phase 7 of the hermes-agent comparison, with the design choices made by the
human.

- Approvals: `approvals.mode` is `ask` (default) or `always_allow`. In `ask`
  mode, `python_execute`, `selenium_browse` and writes to an existing file
  (a write tool with `expected_sha256` other than `missing`) each pause before
  running; the agent shows `approval` and status reason `approval`, and the
  run waits. `POST /api/agents/{id}/approval {approval_id, decision, note?}`
  approves (the call then runs) or rejects (nothing runs; the model gets a
  tool error with the note). Each kind can be switched off in settings, and a
  run can start with `approval_mode: always_allow`. Creating new files and
  reading never ask. Stopping the team while an approval waits runs nothing.
- Team memo: a human-written memo (`memo.json` in the state folder, 4,000
  characters, outside settings so editing it never marks running teams as
  changed) is snapshotted at run start and added to every agent's system
  prompt as guidance that grants nothing. With `memo.proposals_enabled`
  (default on), root PMs get `propose_memo({text, reason})`; proposals wait in
  `state.memo_proposals` until `POST /api/memo/proposals/{id}` approves
  (appends) or rejects them. They never change a running team.
- Past work: `GET /api/history/search?q=` searches saved runs' tasks, results
  and logs. With `history_search.pm_enabled` (default off), root PMs get
  `search_past_work({query})`, which returns other runs' tasks and recorded
  results only (no logs or tool outputs), marked as untrusted past data.
- Fallback models: `providers[].fallback_profile_id` names another profile.
  After the provider's retries and the outage waits fail with a retryable
  error or a timeout, the agent switches once per turn to that profile when
  the run allows it, drops native replay envelopes (as in a PM handoff) and
  re-sends. Quota, authentication and request errors never switch.
- Tests run with approvals off unless marked `approvals` (`tests/conftest.py`).
- The cockpit shows approval cards, an approvals-waiting indicator, the memo
  and its proposals, history search, and the new settings.

## 0.1.1.dev51 — Partial reads, batched edits, read-only workers, single stop and restore (2026-11-15)

Phase 6 of the hermes-agent comparison (files and operations).

- `read_text` takes optional 1-based `start_line` and `line_count` and then
  returns `start_line`, `end_line` and `total_lines`; the hash is still of the
  whole file. A whole-file read cut at the output limit also reports
  `total_lines`. Only whole-file reads count as independent-review evidence.
- `patch_text` keeps the single `find`/`replace` form and adds `edits`: up to
  50 changes, each `{find, replace}` (exactly one match) or
  `{start_line, end_line, replace}` (inclusive). All edits are located in the
  same file version, may not overlap and are applied together, so line numbers
  never shift between edits; any invalid edit rejects the whole patch. Line
  edits keep CRLF and a UTF-8 BOM.
- Read-only workers: `spawn_worker(read_only=true)` creates a worker that may
  read but is neither offered nor allowed write, directory, reservation,
  Python, browser or spawn tools. The identity says `read_only`, and the flag
  is kept in history (agent field `read_only_worker`; `read_only` on agents already marks saved history).
- A PM with `max_workers` 0 is no longer offered worker tools (`spawn_worker`,
  `start_ordered_work`, `wait_for_workers`, `review_worker_report`), which could
  only fail; this keeps the request smaller in solo runs.
- Stop one worker: `POST /api/agents/{id}/stop` stops that worker and its own
  sub-workers (not a PM; not in adaptive or ordered-work runs). Its status
  becomes `stopped` with `stop_reason` `human_stop`, saved files stay, and its
  parent is told by mail so it can reassign. Human-stopped workers no longer
  count toward mandatory-delegation and `wait_for_workers` checks.
- Restore: every overwrite through the file harness (text, Office, Python and
  browser outputs) first keeps the replaced bytes in the app's state folder
  (`checkpoints/`, never readable by agent tools; 256 MB per run, 1 GB total;
  removed when the app closes). A receipt for such a write is `restorable`.
  `POST /api/runs/{id}/restore {"receipt_id"}` puts the earlier content back
  only when no agent is working and the file still has exactly the content
  that write produced. The restore is recorded as a `human_restore` receipt and
  can itself be undone. Archived runs keep no restore points.
- The cockpit shows a stop button for workers, a read-only badge and a
  restore button on restorable receipts.
- Plain labels: the English eyebrow headings and vague secondary labels
  (e.g. TEAM OPERATIONS / 協働の進行, MISSION NETWORK, AGENT INSPECTOR, CREW,
  LEAD · D1, CTX/TURNS, 再委任: 可能との表示) are replaced with short Japanese
  labels; see the table in `docs/GUI_REDESIGN.md`.

## 0.1.1.dev50 — Prompt cache, local runtime and cheaper context (2026-11-14)

Phase 5 of the hermes-agent comparison.

- Prompt cache: the system prompt no longer contains live values. The identity
  JSON keeps static budget limits; live used/remaining counts and the
  automatic-collaboration count travel in a per-request note added on the wire
  after the history (OpenAI: own user item; Anthropic: a text block after the
  last user turn's blocks; Local: a separate user message after tool results,
  or appended to a trailing user message so strict chat templates never see
  two user turns). The note is never persisted and is part of every size
  check. Anthropic requests mark the latest persisted block with
  `cache_control`, caching tools, system prompt and history. Copilot JSON mode
  keeps the note in its system text (it is not cached).
- Local runtime: the wait for response headers and the first chunk scales with
  the request size for Local streams (`max(t, min(1800, t*(1+tokens/32000)))`);
  later gaps keep the idle timeout. A timed-out streamed request is re-sent once
  (closing the stream stops generation); JSON replies and the Copilot bridge
  never replay. When a Local profile has no context window, llama.cpp `/props`
  or Ollama `/api/show` is probed once (loopback/LAN only, 3 s, 64 KB, no proxy)
  and the result applies to that dispatch's measurement only.
- Context: before a summary call, older tool outputs over 2,000 characters
  (outside the recent groups; skill and history reads excluded) become a stub
  with the record id, without inference; if that suffices, no summary call is
  made. Summary markers keep the summarized human messages verbatim (newest
  first, 4,000 characters) and name skills to reload.

## 0.1.1.dev49 — Guards adapted from hermes-agent (2026-11-14)

Phase 4: small, schema-neutral guards modelled on NousResearch/hermes-agent
(`agent/error_classifier.py`, `tool_guardrails.py`, `turn_empty_response.py`,
`turn_tool_validation.py`, `turn_finalizer.py`, `scripts/ci/prompt_surface.py`).

- Provider error bodies are classified from at most 4 KB, by fixed error codes
  and phrases only; the body itself is never logged, returned or shown. Quota
  or billing exhaustion (402/429) is not retried and says so; a context-length
  rejection raises `ProviderContextOverflowError`, which shortens the context
  once with deterministic excerpts (no model call) and re-sends; 401/403/404
  carry a key / model / URL hint.
- An empty or thinking-only reply is nudged once instead of ending the turn.
- Unterminated tool-call arguments (`{...` without a closing brace) are treated
  as an output-limit cut-off, even when the server reports `tool_calls`: no call
  from the batch runs, one larger retry, then the existing recovery.
- The same tool with the same arguments and the same result three times in a
  row adds a notice to the result; five times stops the turn with a message.
  Waiting and team-status tools are exempt.
- Each agent gets one notice in a tool result once any shared budget (model
  calls, tool calls, time) passes 80%.
- With a budget of at least 20 model calls, the last call per PM is reserved:
  workers stop at the reserve, and a PM with workers is told to write its final
  report without tools on that last call.
- `tests/test_prompt_surface.py` snapshots the PM and worker tool schemas and
  system prompts (run-specific values masked) so any change to what the model
  receives is a reviewable diff.
- Tool schemas and system prompts are unchanged.

## 0.1.1.dev48 — Long runs keep saving and survive outages (2026-11-13)

Phase 3 of the agent-persistence work: robustness for long, multi-agent runs.

- History saves reuse this app's last saved archive instead of decoding and
  re-validating the stored document every time (dropped on scrub or failure).
  An archive that would exceed 16 MiB or the per-list item limit is shortened
  (oldest thinking first, then oldest log rows and events; the newest rows,
  results and receipts are kept) instead of every later save failing, which
  left the final run state unsaved.
- The turn limit is checked before the next queued input is taken, so that
  mail or report stays queued instead of being dropped.
- A hierarchy failure or a formation recording failure inside a tool batch no
  longer leaves later calls without results (which made the agent unusable).
- Compaction summarizes one contiguous run of unprotected groups, so work done
  after a protected human message is never placed in front of it.
- After the provider's own retries, a transient failure (connection, 5xx,
  overload) waits 30 s, then 90 s, and re-sends the same call in the same turn
  instead of stopping the agent. Timeouts and non-transient errors stop as
  before; stop and the run deadline still apply; the call is charged once.
- Tool schemas and system prompts are unchanged.

## 0.1.1.dev47 — Streaming replies, concurrent reads and recoverable edits (2026-11-13)

Phase 2 of the agent-persistence work (dev46), again following openai/codex
(`codex-api` SSE handling, idle timeouts, parallel-safe tools).

- Provider replies are streamed (`stream: true`) for OpenAI Responses,
  Anthropic Messages and Local chat completions, and rebuilt into exactly the
  non-streamed JSON shape, so parsing and native replay are unchanged
  (Anthropic thinking signatures and tool input included). Servers that answer
  with JSON are read as before. The Copilot bridge stays non-streamed.
- `request_timeout_seconds` is now the longest allowed silence between received
  bytes (connect timeout 15 s), not a total generation limit; the run deadline
  still bounds total time. A stream that ends before its terminal event is
  retryable; a timeout still is not.
- An output-token-limit rejection is re-sent once with the limit doubled (cap
  32,768, never above a profile limit), outside the Copilot bridge. A second
  limit hit, or a server rejecting the larger limit, keeps the existing
  recover_worker flow.
- Read-only file tools run concurrently across agents. They are admitted under
  the exclusive file lock with the usual stop/budget/dependency/delegation/
  reservation checks; writes, Python and Selenium stay exclusive and wait for
  admitted reads. An independent reviewer's reads keep the original single
  exclusive read-and-recheck operation.
- Edit errors say how to recover: a stale `expected_sha256` reports whether the
  file is missing, already exists or was modified (the current hash is not
  disclosed, so write-only folders stay unreadable); `patch_text` reports
  not-found vs N matches and accepts LF-quoted text in CRLF files.
- File tools are not offered when no read or write folder is configured.
- Tool schemas and system prompts are unchanged, so per-request overhead is
  identical to dev46.

## 0.1.1.dev46 — Keep agents working through transient and correctable failures (2026-11-09)

Motivation: agents stopped permanently on a single transient provider error,
a malformed tool call, a worker narrating its next step, or one oversized tool
result, and PMs rarely delegated. Mechanisms follow openai/codex
(`codex-rs/core`): bounded retries that honor server advice, tool-call errors
returned to the model, truncated tool output, and coordinator prompting.

- Provider retries: HTTP 408/425/429/500/502/503/504/529 and connection
  failures are retryable. `Retry-After` / `retry-after-ms` is honored (capped at
  60 s); otherwise exponential backoff with ±10% jitter. Cloud profiles, which
  cannot carry retry keys, now default to 3 retries. Timeouts remain
  non-retryable, so a request the server may still be generating is never
  replayed; the Copilot bridge still never retries.
- Tool-call errors return to the model: empty arguments mean `{}`; malformed
  arguments or a tool not offered in the current turn produce an error result.
  The batch rule is unchanged: if any call in a response is invalid, no call in
  that response runs (including earlier valid ones). Every call receives a
  result, and the model may re-issue the batch at most 2 times before the agent
  stops with an error. Unpairable/duplicate call IDs still reject the reply.
- Workers that used tools in a turn and then reply with prose only are asked
  once to continue with tools or send `finish_work`. A PM's plain-text final
  answer is unchanged.
- Tool results sent to the model are bounded to 1/4 of `max_context_chars`
  (4,000–40,000 characters, head + tail with a notice). The retained original
  keeps the complete text under the same record ID, which the shortened copy
  names so the model can page it with `read_context_history`. Tool schemas are
  unchanged, so per-request overhead stays identical to dev45.
- PM orchestration prompt: plan the critical-path step, delegate independent
  subtasks, spawn workers together in one response with self-contained
  assignments and file ownership, and wait instead of ending with prose while
  workers run. Budget text states that worker calls are expected.
- Defaults for new settings: 200 model calls, 400 tool calls, 40 turns per
  agent, 8,192 output tokens. Existing saved settings are not changed.
- Cockpit: crew roster and mission network redesigned after ORRERY's design
  language (no ORRERY code or assets), and the mission network can be opened in
  its own tab or window (`/?view=network&run=<id>`) showing only the map.
- Fixes from review: mixed-separator UNC paths (`\/host/share`,
  `/\host/share`) are rejected before any filesystem access; settings import
  preview no longer probes UNC paths; reviewing a worker whose report is stale or
  blocked by a dependency is an ordinary tool error instead of pausing the
  reviewing PM.

## 0.1.1.dev30 — Keep credential Enter shortcuts out of IME composition (2026-10-06)

- A production-callback audit found that both provider and search credential
  inputs treated composition-marked Enter as an explicit key-set command. Synthetic
  `isComposing: true` and `isComposing: false, keyCode: 229` events reached
  `preventDefault()` and a mocked `/api/secrets` request, clearing the input.
- Guard only those two keyboard callbacks with `isComposing || keyCode === 229`
  before canceling native behavior or invoking `setCredential()`. Retain ordinary
  Enter and explicit buttons, saved target/revision capture, pending one-flight
  behavior, stale/dirty settings guards, and the existing credential lifecycle.
- The task/message composers have no Enter-to-send callback. Keep their native
  textarea editing and submit-button behavior unchanged, along with draft epochs,
  task-reuse confirmation, the shared API helper and dev29 acknowledgement checks.
  Do not add global composition locks, delayed sends, timers, or dependencies.
- Add registered production-callback cases for both credential targets covering
  active composition, the end-of-composition 229 boundary, later explicit Enter
  and button activation, repeated pending activation, unrelated keys, and existing
  authentication/settings guards. All transport remains synthetic.

Primary-source decisions:
- [MDN keydown events with IME](https://developer.mozilla.org/en-US/docs/Web/API/Element/keydown_event#keydown_events_with_ime):
  check both `isComposing` and legacy `keyCode === 229`; some boundary keydowns
  occur outside the compositionstart/compositionend interval.
- [W3C UI Events composition model](https://www.w3.org/TR/uievents/#events-compositionevents):
  composition and keyboard events are distinct, and composition keys vary by IME.
- [WHATWG implicit form submission](https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#implicit-submission):
  native submit-button activation is separate from the two custom shortcuts.
  Callback-only tests do not establish actual browser default-action behavior.

Local implementation begins from exact dev29 candidate
`72bc2fb46688693367333c06543f6cc9d02836a6`. The new composition regression first failed
against the unchanged dev29 callback. After the guard, all 26 new callback cases
passed, the focused credential/version set passed 47 tests, and aggregate pytest
passed 1,427 tests with 42 skips. Application JavaScript syntax and whitespace
checks passed. A byte comparison confirms that `app.js` differs from dev29 only
by the two guard insertions. Real Japanese OS IME behavior, password-field
composition availability, native Windows Edge keyboard/button behavior, and
remote CI remain unverified. No hosted acceptance, publication, merge, deployment
or release is claimed. Earlier versioned log sections and evidence archives
retain their original scope unchanged.

## 0.1.1.dev29 — Require the message acceptance receipt (2026-10-06)

- Correct the separate dev28 follow-on: a successful HTTP response containing
  `{}` must not clear the message input or display `送信しました。`.
- Require literal `ok === true` only in the message callback, after production
  `api()` parsing and before the existing clear/success path. Missing or invalid
  acknowledgement uses the existing unknown-outcome feedback and retains exact
  input. Explicit rejection continues through the existing error path.
- Preserve selection/draft epochs, same-text edit/restore and selection ABA
  protection, exact captured target/body, pending one-flight behavior, and neutral
  input-presence marks. No auto-resend, storage, endpoint or scheduler is added.
- Document `{ok:true}` as acceptance into the current in-memory engine workflow,
  not model completion or durable delivery. A lost/malformed response may follow
  acceptance; retained text must not be described as definitely unsent.
- Cover actual API parsing plus submit callbacks across receipt types, HTTP and
  transport failures, deferred fetch/JSON, and old-owner completions. Add real HTTP
  server-contract coverage and browser cases that forward the POST once, verify
  real acceptance, and then replace or abort only the browser-facing response.

Primary-source decisions:
- [WHATWG Fetch Response.ok](https://fetch.spec.whatwg.org/#dom-response-ok) and
  [Body.json()](https://fetch.spec.whatwg.org/#dom-body-json): HTTP success and JSON
  parsing do not validate this application's acknowledgement contract.
- [RFC 9110 §9.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2) and
  [AWS Builders' Library](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/):
  non-idempotent requests must not be automatically replayed merely because an
  acknowledgement is missing. No idempotency mechanism is introduced here.

Local implementation begins from exact dev28 candidate
`8d4f6340c75ff4c485fcf09300f7420cdffb880f`. Local verification: 76 focused tests
passed; aggregate pytest passed 1,401 tests with 42 skips; application JavaScript,
the new browser module and its smoke integration pass syntax checks. The shared
API helper and earlier versioned log sections remain byte-identical. The six new
real-HTTP browser cases are written but Windows Edge execution and remote CI are
pending. No hosted acceptance, publication, merge, deployment or release is
claimed. Earlier evidence archives retain their original scope unchanged.

## 0.1.1.dev28 — Neutral input presence and direct owner navigation (2026-10-06)

- Add passive input marks to existing crew/question cards, per-team input-owner
  counts, and one explicit cross-team next-input action in the existing sidebar.
  Keep the cockpit and question mode; no third dashboard or draft collection.
- A nonempty input field, including whitespace, establishes only text presence.
  Pending, unknown and already accepted text can remain after navigation or edits.
  Use neutral `入力あり`, count owners rather than messages, exclude the task editor,
  and never infer unsent state, priority, forgotten intent or current send eligibility.
- Derive known owners from current run/member summaries; preserve exact existing
  strings. Missing owners are not navigated to or silently reassigned/deleted.
  Do not copy message content into cards, search, status metadata or storage.
- Traverse current session-list order and each team's declared member order,
  selecting the exact run/agent once. Preserve both roster searches and mode;
  keep blocked inputs visible without enabling Send. Explicit navigation focuses
  the enabled composer or existing owner heading. Same-owner activation does not
  churn selection/navigation epochs; delayed state never performs that focus move.
- Presence transitions update existing render signatures and a concise polite count.
  Same-presence character edits and unchanged polls do not rebuild cards or rewrite
  count/label/status nodes. Successful existing text clearing updates indicators
  immediately, before the following state request completes.
- Independent source review tightened modal isolation, presence-only DOM updates,
  known-member badges and immediate post-clear rendering. Place navigation before
  search to preserve the existing native search-to-first-card Tab route. Dedicated
  production callback tests cover these cases without changing receipt semantics.

Research decisions:
- [VS Code editing](https://code.visualstudio.com/docs/editing/codebasics#_save-auto-save):
  adopt contextual marks and aggregate counts. Backup/Hot Exit are separate
  capabilities; these marks do not promise storage or restoration.
- [Slack drafts](https://slack.com/help/articles/201457107-Send-and-read-messages)
  and [Teams release notes](https://support.microsoft.com/en-us/teams/platform/what-s-new-in-microsoft-teams):
  cross-conversation discovery is an established messaging pattern. Defer a full
  collection because this smaller feature closes the visibility gap without a
  new lifecycle/filtering surface. Product precedent is not comparative evidence
  proving this design's benefit.
- [Mixed-initiative principles](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/11/chi99horvitz.pdf)
  and [Human-AI Interaction Guidelines](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf):
  interpret uncertainty conservatively, expose a quiet affordance, and leave
  invocation to the user. Reject automatic reminders, reopening and resubmission.
- [W3C status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html),
  [focus order](https://www.w3.org/WAI/WCAG22/Understanding/focus-order.html) and
  [native buttons](https://www.w3.org/WAI/ARIA/apg/patterns/button/): textual marks,
  native activation, count-only announcements and nearby unavailable-control
  fallback, without interrupting typing or announcing message content.

Separate confirmed follow-on: the existing message callback accepts an
object-shaped HTTP 2xx response without requiring the endpoint's `{ok:true}`
receipt. Synthetic production-API/callback reproduction with `200 {}` clears an
unchanged input and displays success. Strict receipt validation is not changed
in this discovery feature; no new accepted-status badge or attempt-state store
is introduced. This remains a distinct correction with its own outcome tests.

Verification uses deterministic production callbacks and the existing synthetic
Windows Edge route at desktop/tablet/narrow widths with 20 retained teams.
Exact-head full local/CI checks, artifact identity, independent source and actual
pixel review are required; earlier screenshots do not accept this revision.
Preserve the preceding dev27 public overview byte-for-byte in historical evidence.
No new endpoint, persistent storage, live inference, local browser retry, user-PC
action, dependency, bundled Python, merge, deployment or release is included.

Hosted acceptance correction:
- The [first exact source run](https://github.com/tyama-ds/agent-workbench/actions/runs/37405818118)
  on `40bbfbce` passed all four matrix jobs. Edge reached the new desktop geometry
  check, then found a real focused-question-card clipping issue: the added sidebar
  controls and active notice left a roughly 222-pixel roster scrollport, smaller
  than the long question card. Independent failure-pixel review confirmed it.
- Keep the strict whole-target clipping assertion. Use concise card previews at
  every width, retaining full identity/question in selected detail and the separate
  team ID, neutral marker and two-line availability reason. Reserve a usable
  question scrollport and let a shorter sidebar scroll instead of hiding controls.
  Add measured clipping diagnostics and native focus coverage for blocked/unknown
  question cards as well as the allowed owner. Fresh exact-head hosted checks and
  actual pixels are required; the failed run does not accept the correction.
- The [second source run](https://github.com/tyama-ds/agent-workbench/actions/runs/37406734628)
  on `15968d32` passed all four matrix jobs and the corrected desktop card checks,
  then the tablet test incorrectly expected a keyboard focus indicator after
  pointer selection followed by programmatic focus. Establish keyboard modality
  with a real Tab from the preceding control, retain the strict outline assertion,
  and include focus-visible diagnostics. Independent review also added actual
  enabled Next pointer clicks alongside Space at every viewport. No production
  focus-style workaround or relaxed clipping check is introduced; rerun the exact
  final source and inspect its artifacts before acceptance.
- The [third source run](https://github.com/tyama-ds/agent-workbench/actions/runs/37407490083)
  on `d2ef8ea3` passed all four matrix jobs and reached narrow card visibility.
  After a direct programmatic card focus, its 240-pixel rectangle was partly
  outside the horizontal strip (left 259, right 499, viewport right 390), while
  vertical bounds and content overflow passed. Keep that measured evidence and
  the strict visibility assertion. Exercise actual search-to-card Tab traversal
  for each enabled/blocked/unknown target, without test-side scrolling, before
  inferring a native keyboard reveal defect or adding production scroll behavior.
- The [fourth source run](https://github.com/tyama-ds/agent-workbench/actions/runs/37408225451)
  on `9d276e0b` reproduced those same narrow horizontal bounds with genuine Tab
  traversal and two-frame settling. This confirms a native reveal issue rather
  than just programmatic test setup. After an unmodified Tab/Shift+Tab, reveal the
  actual currently focused roster card on the next frame using nearest alignment.
  Never change focus/selection, capture an old target or schedule from polling;
  newer focus and modal context win. Production-callback tests cover those guards,
  and the full-card/lower-action native browser assertions remain unchanged.
- The [resumed source run](https://github.com/tyama-ds/agent-workbench/actions/runs/37601859460)
  on `0861c3fa` passed all five jobs, as did its PR run. Independent artifact review
  nevertheless found the tablet full-page question screenshot showing the focused
  card partly clipped, contradicting the immediately preceding native geometry
  assertion. Do not accept that pixel gate solely from green checks. Retain strict
  bounds, add an unchanged-poll settling check, viewport-sized question captures
  before full-page captures, and pre/post focus/scroll geometry in the report.
  No test-side scrolling or production change is added while distinguishing a
  capture effect from a delayed layout/scroll defect.
- The [capture diagnostic source run](https://github.com/tyama-ds/agent-workbench/actions/runs/37603649425)
  on `efb482cd` established that transition: tablet focus remained fully visible
  after a real unchanged poll and before/after viewport capture, with identical
  scroll geometry. Only full-page capture shifted the card by the roster's
  165-pixel scroll offset, causing the strict post-capture assertion to fail.
  Independent report and viewport-pixel review confirmed the capture-induced
  change. Focused-question evidence therefore uses viewport-only screenshots,
  preserving strict full-card/lower-action checks, unchanged polls on both sides
  and recorded pre/post geometry. No production workaround, test-driven reveal,
  restored scroll or weakened visibility assertion is introduced.

## 0.1.1.dev27 — Displayed request text into a protected new-task draft (2026-10-06)

- Reproduced that selecting an older team did not bring its request into the new-task
  editor, while the editor could hold a different meaningful draft. Add one secondary
  action in the selected-team overview and reuse the existing dialog. Only public
  display-redacted request text is adopted; preserve current form choices and all
  agent drafts/navigation. No historical conversation, results, configuration,
  credentials, permissions or budget are copied.
- Protect every nonempty differing draft, including whitespace-only input, with
  explicit Keep/Replace. Identical content opens without draft-epoch churn. Pending
  choices block Start and suppress/invalidate preflight. Adoption or Keep uses the
  existing admission-only preflight; creating a team still needs explicit Start.
- Bind replacement to source ID/raw displayed text, selection/navigation/dialog/
  workspace/draft epochs and the actual current payload. Cancel stale/ABA choices,
  source removal/remasking and intervening edits. Preserve newer focus and feedback;
  guard pending start requests without changing their existing outcome semantics.
- Preserve text and literal redaction markers except native textarea CRLF/CR-to-LF
  normalization, disclosed in the dialog. Compare raw source for freshness, normalized
  text for editor equality and the 16,000 UTF-16-unit limit. Reject unavailable or
  oversized candidates without truncation; whitespace-only and NUL sources are also
  unavailable, matching backend task validation. This is displayed text, not byte-exact
  original data, verified latest state, resumed execution or restored authority.

Hosted acceptance correction:
- The [first source Edge run](https://github.com/tyama-ds/agent-workbench/actions/runs/37401350963)
  on `3559294` reached the new source-removal case but the synthetic compact response
  incorrectly claimed loaded detail after deleting its requested agent. The app
  correctly rejected that inconsistent response and retained its last displayed
  source. Independent review and the failure screenshot confirmed this. Keep strict
  compact validation; assert malformed-response retention, then test accepted removal
  through the explicitly supported legacy full-state fixture. The Engine itself does
  not delete retained runs during its lifetime. All four matrix jobs passed; fresh
  exact-head Edge/aggregate gates are required after this fixture correction.
- Source review also found that polling-driven invalidation left the old preflight
  guidance waiting for a decision that no longer existed. Resume admission-only
  checking of the retained current draft after cancellation, without adopting or
  executing anything; a focused regression verifies the exact preview payload.

- The [second source Edge run](https://github.com/tyama-ds/agent-workbench/actions/runs/37402154387)
  on `88db2ef` passed all matrix jobs and the corrected state cases, then exposed a
  real tablet keyboard-reading issue: End on an already bottom-scrolled preview
  scrolled its surrounding dialog, hiding the still-focused preview. Independent
  failure pixels confirmed it. Reset only a newly opened candidate's preview; keep
  unmodified Home/End inside that focused reading region and contain overscroll.
  Retain strict clipping checks and add repeated-End/Home cases; unchanged polls
  still preserve reading position. New exact-head hosted evidence is required.

Research decisions:
- [GitLab manual pipelines](https://docs.gitlab.com/ci/pipelines/#run-a-pipeline-manually):
  adopt editable preparation separated from an explicit execution action.
- [AWS Step Functions redrive](https://docs.aws.amazon.com/step-functions/latest/dg/redrive-executions.html):
  reject restart/resume semantics, which require preserved execution history and
  definition guarantees that this text-only feature does not provide.
- [Microsoft HAI guidelines](https://www.microsoft.com/en-us/research/uploads/prod/2019/03/AI_Guidelines_Poster_PrintQuality.pdf):
  apply efficient correction, cautious adaptation, short-term references and clear
  consequences through editable drafts and overwrite protection. This is design
  guidance, not a user study or proof of demand.
- [Slack draft discovery](https://slack.com/help/articles/201457107-Send-and-read-messages)
  and [VS Code unsaved editing](https://code.visualstudio.com/docs/editing/codebasics#_save-auto-save):
  a real alternative is finding hidden per-agent drafts. Defer a global draft view
  because nonempty task text can already have been submitted, and blocked/vanished
  owners and unknown send outcomes need separate contracts. Do not imply durable
  recovery, add storage or introduce another dashboard.

Coverage uses production callbacks with deferred transport, non-mutating Engine
preflight checks and Windows Edge native keyboard/layout cases. Exact-head full
local/CI gates, independent source review and actual screenshot inspection are
required before acceptance. Preserve previous verification bytes in the historical
evidence index. No local browser retry, live inference, user-PC action, dependency,
bundled binary, merge, deployment or release is included.


## 0.1.1.dev26 — all-session human questions (2026-10-06)

- Reproduce the visibility gap: the old header counted only the selected team's
  questions, while another running team could contain a paused agent. Reuse the
  existing roster for an explicit global question view; retain the cockpit and
  clearly identify the selected team's center/right context.
- Show independent membership and reply availability, separate visible team IDs,
  question previews, search and per-session counts. Keep blocked/unknown questions
  visible; exclude errors, teammates and stopped residue. Opening is read-only.
  No ranking, unread/resolve state, queue API, persistence or notification service.
- Select the exact run/agent once, preserving drafts and compact detail ownership.
  Guard send completion with selection and draft epochs, including same-text ABA
  edits. Add native full-question keyboard reading, changed-count announcements,
  poll-stable reading position and visible focus fallback after removal.
- Adopt contextual disclosure, efficient invocation and cautious adaptation from
  [Microsoft's Human-AI Interaction guidelines](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf).
  Apply [mixed-initiative interaction research](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/11/chi99horvitz.pdf)
  by exposing needed dialogue without forcing interruption. These are design
  interpretations, not empirical proof of this implementation's user benefit.
- Apply [W3C status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html),
  [focus order](https://www.w3.org/WAI/WCAG22/Understanding/focus-order.html) and
  [native button semantics](https://www.w3.org/WAI/ARIA/apg/patterns/button/).
  Reject inferred priority, auto-navigation and assertive whole-queue announcements.
  No external code or assets are copied. Defer draft badges and stopped-task
  carry-forward as separate features with different state/permission tradeoffs.
- Independent review tightened membership, exposed IDs outside clamped text,
  preserved question scroll and revealed removed-card fallback. Cover real Engine
  pause/peer/deadline/reply/stop transitions, deferred UI races and 20-session
  synthetic Windows Edge interaction at desktop/tablet/narrow widths.
- The first real Edge pass exposed a long-task/long-question composition that
  clipped Send on desktop. Allow the bounded, keyboard-scrollable question region
  to shrink to a usable minimum; retain the strict composer visibility assertions.
  The next Edge pass completed the new feature cases, then exposed an older send
  test expecting stale feedback after editing a draft. Replace that expectation
  with a held exact POST/acceptance check and preserve the newer unsent draft;
  subsequent cross-agent send cases remain unchanged.
- Preserve the exact preceding documentation-revision PR overview and provenance
  in the evidence index. Final local counts, source/PR CI, artifacts and independent
  review belong to the exact-head handoff. No live inference, user-PC execution,
  dependency, permission, binary packaging or five-job CI policy changes.

## Documentation revision 1 — internal deployment review (2026-10-06)

- Add one short Japanese [IT review checklist](IT_REVIEW_CHECKLIST.md), linked from
  README and Windows setup. Its behavior baseline is `0.1.1.dev25`, source commit
  `497b549bec320020dd35696ab0871ef45ca832b9`; the application version stays unchanged.
- Gather separate installation, runtime-destination and data-handling decisions;
  link existing instructions instead of adding another installation procedure.
  Keep approvals blank, and distinguish hashes, private IPs and CI from company approval.
- Cover enabled initial profiles, offline-install versus inference behavior,
  separate proxy/CA settings, retained retired-key masks and explicit state-directory
  ACL caveats. No application, default, dependency, permission or CI behavior changes.
- Check the existing approach against [pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/),
  [local-package installation](https://pip.pypa.io/en/stable/user_guide/#installing-from-local-packages),
  [Python ensurepip](https://docs.python.org/3/library/ensurepip.html) and
  [Microsoft icacls](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls).
  These references explain mechanisms, not approval or compatibility of this deployment.
- Validate Markdown references and source consistency. Fresh exact-head five-job CI
  and independent review belong to the public handoff; prior evidence keeps its scope.

## 0.1.1.dev25 — Python-independent setup help (2026-10-06)

- Reproduce a bootstrap usability gap: the CMD entrypoint checked for an approved
  interpreter before processing `--help`. A user could not read option help before
  Python selection. Add fixed, English ASCII usage/examples for `--help`, `-h` and
  `/?` before that check. Help must be the first and only argument; extra arguments,
  including an explicitly empty quoted argument, return an error without setup.
- Explain the existing temporary `WORKBENCH_PYTHON` selection, separately approved
  standard CPython, preflight, proxy/CA and offline choices. Help does not run
  Python, validate prerequisites, create `.venv`, install packages or use network.
- Keep the normal CMD body and its complete argument forwarding unchanged. Python
  selection, source installation, version support, proxy/CA containment, offline
  behavior and the PowerShell compatibility wrapper retain their existing rules.
- Apply Microsoft's [CMD quoting guidance](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd)
  and [batch parameter semantics](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/call):
  keep help as static echo lines outside command groups, never expanding user
  environment values into its output. Use native Windows tests for actual parsing.
- Defer a new Python-path argument or interactive picker: the existing two-line
  flow already avoids persistent settings, and another selector does not solve
  organizational approval. [SHIFT leaves `%*` unchanged](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/shift),
  so consuming a selector would require a new forwarding contract. Do not promise
  untested drag-and-drop behavior or add discovery through PATH/registry/launchers.
- Retain the launcher restriction because [Python install-manager launch paths](https://docs.python.org/3/using/windows.html#installing-runtimes)
  can install a missing runtime. No new dependency, installer redesign, policy
  bypass, bundled build, UI change, live inference or user-PC execution is added.
- Preserve the exact preceding dev24 public PR description and byte provenance in
  the evidence index. Fresh exact-head source/PR CI and independent review are
  recorded in the public handoff; historical checks retain their named scope.

## 0.1.1.dev24 — clarify data-use limits (2026-10-06)

- Keep the existing readiness destinations, file scope and Web explanation. Add one
  small in-place paragraph distinguishing LOCAL APP from inference location and
  explaining cross-profile sharing and unverified downstream data handling.
- Correct the README/SECURITY Local-only recommendation: private-LAN addresses do
  not establish company approval or rule out server-side forwarding. File reads
  enter model conversations; the copy does not claim that access grants permission
  under organizational policy. All PM and worker endpoints need the relevant review.
- Adopt the transparency principle from [Microsoft's responsible agent design
  guidance](https://learn.microsoft.com/en-us/agents/design-guidelines/responsible-ai):
  explain information use and system limits where users choose the task's models.
  The wording is grounded in this application's provider, teammate and Web flows,
  not in assumptions about any provider's retention or training policies.
- Reject approval badges, private-IP trust labels, automated probes and a new policy
  engine. No extra settings section, control, persistence, telemetry or data-routing
  behavior is added. Existing native forms, styles and asynchronous ownership remain.
- Add repeated Local-only/mixed-provider copy checks and real Edge desktop/narrow
  focus, wrapping and reachable-control checks, retaining the prior browser suite.
  Source-only installation and all five CI jobs remain unchanged. Final exact-head
  CI, screenshot inspection and independent review belong to the public handoff.
- Preserve the full preceding dev23 public PR description and byte provenance in
  the evidence index; historical checks are not relabeled as dev24 acceptance.

## 0.1.1.dev23 — source-only installation (2026-10-05)

- Follow the requirement that Python is separately approved and installed by the
  organization. Discontinue bundled prototypes/builds/distribution preparation,
  including evaluation-only mode, and remove the portable CI job.
- Make the former builder CLI, direct assembly API and PyInstaller spec fail before
  downloads, subprocesses or build output. Keep historical evidence and offline
  synthetic notice helpers without treating them as current distribution support.
- Preserve source Setup/Launch and approved 64-bit CPython 3.11–3.13 support. Require
  the explicit local path of an existing approved interpreter, avoiding install-capable
  launcher aliases rather than relying on environment switches that manager settings
  can override. Do not change the caller's persistent settings.
- The [legacy launcher documentation](https://docs.python.org/3.13/using/windows.html#install-on-demand)
  and [install manager configuration](https://docs.python.org/3/using/windows.html#configuration)
  describe why aliases cannot guarantee read-only discovery. Python itself is not
  installed or upgraded by this change. Hosted CI supplies its own test runtime.
- Based on verified dev21. No unpublished dev22 changes are included. Application
  security behavior, dependencies, frozen compatibility helpers and UI are unchanged.
  Test results apply only to the named source head and are recorded at handoff.

## Cycle 1 — browser acceptance v1 (2026-10-05)

Based on PR #1 head `9067567388d659b4d00109f0d5cb3ecc7b5e7f71`.
Application version is 0.1.1.dev1: browser evidence uncovered a narrow-layout defect,
so this cycle also includes a targeted responsive preservation fix.
The test-only package is version 0.1.1 and the assertion report schema is version 1.

### Adopted

- Run genuine Edge browser acceptance on Windows CI, with a lockfile-pinned test-only
  Playwright driver. No Node/Playwright requirement is added to Windows setup or the app.
- Preserve real bootstrap, cookie session, settings persistence, memory-only secret and
  local models-list checks; label synthetic content and reject off-origin browser requests.
- Retain a controlled UI-state phase for race/draft/limit/XSS checks, correcting its run
  status and rejecting agent fields outside the actual `Agent.public()` contract.
- Add a separate real HTTP/Engine phase with a deterministic injected model client. It
  creates a worker, emits completion mail, asks the human, accepts a reply and is cancelled
  through real endpoints. No LLM endpoint or paid inference is involved.
- Check 1366×768 and 390×844, native-dialog keyboard focus/Escape/restoration, polling
  focus, per-agent drafts, overflow, settings locks and unlocks. Upload only synthetic
  screenshots and JSON assertions, including failure evidence, for 14 days.

### Responsive correction discovered by actual pixels

The first fully passing browser run on head `5b4104c` was
[run 37259217044](https://github.com/tyama-ds/agent-workbench/actions/runs/37259217044).
Independent screenshot review still found overlap after the stop notice at 390px.
A more-specific notice selector retained a viewport-fixed shell height on stacked layouts.

- Match that selector in the responsive auto-height override.
- Keep narrow rails/content in natural document flow, with bounded internally scrolling
  cards/logs, so long Japanese questions and the send form remain reachable.
- Add vertical region/control bounds assertions, active long-question and 820px tablet
  screenshots, plus reset the scrollable settings dialog before its screenshot.
- Desktop structure, colors, interaction and model/security behavior are preserved.
- The correction at `c8e4f51` passed all five jobs in
  [run 37259569652](https://github.com/tyama-ds/agent-workbench/actions/runs/37259569652).
  Actual desktop, tablet and narrow screenshots were inspected; controls are reachable
  without sidebar/workspace overlap. Later commits must retain their own green checks.
- Local suite: 278 passed, 4 Windows-only skips. Full screen-reader/text-zoom audits and
  pixel-baseline comparison remain outside this cycle's evidence.

### Research decisions

- [W3C modal dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/): adopt
  focus containment, Escape and return-focus checks; do not replace native dialogs.
- [VS Code accessibility](https://code.visualstudio.com/docs/configure/accessibility/accessibility):
  adopt keyboard/state observability and reduced-motion test context; defer a complete
  screen-reader audit rather than equating a browser smoke with accessibility certification.
- [Playwright screenshot guidance](https://playwright.dev/docs/test-snapshots): pair images
  with explicit state assertions and record browser version. Defer pixel baselines until
  a stable browser/font runner is chosen; Edge on windows-latest is intentionally updated.
  Screenshots are review evidence, not automatically accepted pixel-regression baselines.
- Defer approval engine, persisted history and new providers to separate reviewed cycles.

### Known limits / next candidates

- Local browser launch is blocked by this executor's process/socket policy. Windows CI
  has now run the real browser; each correction still needs its own exact-head rerun.
- Assignment display/search currently looks for a non-public `agent.task` field. The
  synthetic snapshots no longer mask that gap; a future distinct assignment field must
  not expose the internal asyncio task.
- Waiting status labels can conflate human questions with error/budget waiting. The real
  human-question filter is tested; broader state semantics are a separate change.
- No live model quality, target GPU behavior, company proxy or real user's desktop is tested.

## Cycle 2 — truthful assignment and recovery v1 (2026-10-05)

Application version **0.1.1.dev2**, based on cycle 1 head
`8bf4cb830aef9675a1f902c39ba558dbe453108b`. Retains the same cockpit and scheduler.

### Adopted

- Expose the actual initial PM/worker brief as a distinct `assignment` string, redacted
  by the existing snapshot boundary. Display and search this field. Replies and peer
  messages remain conversation entries; they do not silently replace the original brief.
  Never expose the internal asyncio `task`, pending queue, conversation or configuration.
- Derive `status_reason` from runtime state: human questions, unfinished teammates,
  teammate errors, failed runs, collaboration blocking and mixed attention. Generic
  waiting no longer claims the human owes an answer. Stopped agents with an old question
  are not counted as current human questions. No generated progress percentages.
- Derive PM identity from the actual parent relationship, not a model-provided role name.
  Queueing a human follow-up during inference retains the agent's working state.
- Expose read-only `message_eligibility` with `allowed`, `reason` and explanatory `message`.
  The POST rechecks the same predicate before changing queues/questions/errors/status.
  Stopping, stopped, stale settings, a full queue and exhausted turn/time/model/context
  budgets explain their recovery path. Stopping does not claim writes have finished.
- Preserve allowed human direction after automatic collaboration exhaustion; no budget
  resets. Exhausted tool calls still allow text-only model completion and show a warning.
  Admission is a current-state hint, not a reservation or promise of future model success.
- Extend contract, transition, frontend, DOM-only and real Edge tests. The real HTTP/engine
  browser phase checks assignment search, a human question, hard-turn recovery and stale
  configuration guidance. All inputs remain synthetic and no model endpoint is called.

### Research decisions

- [OpenTelemetry trace API](https://opentelemetry.io/docs/specs/otel/trace/api/): adopt the
  limited principle of explicit operation identity, parent relationships and evidence-based
  status. Reject a tracing SDK, exporter or collector: unnecessary for this in-memory UI.
- [Microsoft Human-AI Interaction guidelines](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf):
  adopt clear capability/state feedback and an actionable recovery explanation. Reject
  inferred completion/progress from model prose and automatic retries that consume budget.
- Defer assignment revision/history, persisted activity, broad state-machine changes,
  new providers, approval flows and telemetry to separate reviewed cycles.

### Screenshot-led correction

The first cycle 2 Edge run passed its assertions, but pixel inspection exposed a stale
send confirmation carried into a newly selected run. Clear composer feedback on run or
automatic agent selection, and bind late send success/error feedback to its original
selected agent. Preserve drafts and queue behavior. Add browser/DOM regression assertions;
the corrected source requires its own exact-head CI and screenshot review. A second
review clarified that the collaboration limit alone does not stop existing work; the
notice must not imply a stopped team can resume. Explicit stopped-team copy and a browser
assertion cover the combined stopped/limit state.

### Verification

Final exact-head CI and screenshot evidence is recorded in the cycle handoff. Historical
cycle 1 browser evidence above remains tied to its named commits and is not reused as
proof for this cycle's changes.

## Cycle 3 — Current-session results and save receipts (0.1.1.dev3)

### Implemented scope

- Keep terminal no-tool assistant responses separate from explicit `finish_work` reports.
  Both are model-authored text, not factual verification. Intermediate narration,
  questions, cancelled turns and errors do not become terminal responses.
- Keep the latest 20 reports (24,000 characters each) and 64 actual file-save receipts
  per agent, separately from the existing 200 log entries. Show retention omissions
  and text truncation explicitly. Records remain in memory for this server session.
- Save receipts come only from successful text/Office tool operations and include the
  actual path, saved byte count, SHA-256, tool, agent/turn, timestamp and create/update
  mode from the validated preimage. The completion observer runs on the event loop,
  including successful writes drained during Stop. Receipt observer failure cannot
  turn a committed save into an apparent save failure.
- A saved hash identifies bytes at save time, not the current path contents or factual
  correctness. No file existence/readability/download promise and no new filesystem
  route. Write-only scope remains write-only. Resume makes prior responses historical.
- Copy/export is an explicit action on selected redacted public text/receipt metadata.
  Exports are plain UTF-8 text, with no hidden reasoning, provider protocol, settings,
  automatic persistence, backups or telemetry. Async clipboard feedback is selection-
  and request-scoped. No Office bytes are copied or downloaded by this feature.

### Research decisions

[W3C PROV-DM](https://www.w3.org/TR/2013/REC-prov-dm-20130430/): adopt the small relationship
between output identity, producing activity and responsible agent. Provenance informs
trust assessment; it does not certify content. Record create/update from successful
operations and preserve save-time hashes. Defer RDF/PROV serialization and source graphs.

Defer file retrieval: a later feature needs opaque receipt IDs, fresh allowed-read and
path/link checks plus hash validation of the exact bytes returned, with changed,
missing and inaccessible states distinguished. Reject arbitrary filesystem path routes,
model-inferred file receipts, automatic archives and persistent history.

### Verification

Final tests, exact-head Windows/Edge CI and screenshot review are recorded in the cycle
handoff. Earlier cycle evidence does not prove this feature's implementation.

### Windows path normalization correction

The first Edge run reached real result export and path copy, then exposed a test-only
assumption: Windows temporary paths may use an 8.3 user-directory alias while the path
guard returns the canonical long path. Compare the copied path with native realpath;
keep exact path verification and leave production permission/receipt behavior unchanged.

## 0.1.1.dev4 — Local preflight and honest provider evidence (2026-10-05)

- Added local-only run admission preview reusing start admission, with potential model/proxy/Web destinations and independent canonical read/write roots plus overriding automatic/app-state exclusions. Empty scope remains usable for text-only tasks; unused worker profiles do not block PM-only work.
- Kept configuration validity, app connectivity, model-list response, inference, and structured tool execution as distinct evidence. Header says Workbench / LOCAL APP. Explicit per-profile list checks are bounded and safely typed; no automatic discovery, inference, paid tests, capability guessing, or credential-persistence change.
- Kept the existing cockpit, results/copy/export, runtime status/reply contract, and task drafts. Preview and diagnostic feedback is invalidated on relevant edits, newer requests, and modal dismissal.

Primary-source research and decisions:
- [LM Studio tool support](https://lmstudio.ai/docs/developer/openai-compat/tools): native support combines model/template and server parsing; default support also exists with varying quality. Adopt uncertainty and structured-call-only execution; reject model-name allowlists and executing raw text as tools.
- [LM Studio models](https://lmstudio.ai/docs/developer/openai-compat/models): JIT can list downloaded rather than loaded models. Do not label listed models as loaded or ready.
- [OpenAI model listing](https://developers.openai.com/api/reference/resources/models/methods/list) and [Claude model listing](https://platform.claude.com/docs/en/api/models/list): list metadata is not an inference test; Claude is paginated. Preserve incomplete-list uncertainty and manual aliases.
- [Open WebUI compatible-provider setup](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/) explains that a failing models endpoint need not mean incompatible inference. Adopt manual IDs and protocol clarity; do not add protocol adapters in this cycle.
- [Open WebUI connection troubleshooting](https://docs.openwebui.com/troubleshooting/connection-error/) explains slow/unreachable endpoints blocking list loading. Keep checks explicit per profile, bounded, and separate from local admission.
- [Microsoft HAX G1](https://www.microsoft.com/en-us/haxtoolkit/guideline/make-clear-what-the-system-can-do/) and [G2](https://www.microsoft.com/en-us/haxtoolkit/guideline/make-clear-how-well-the-system-can-do-what-it-can-do/): separately explain scope and confidence. Adopt a compact task-dialog preview rather than a new onboarding wizard.
- Defer explicit optional inference/tool probes, automatic model loading/downloading, provider expansion, and persistent capability scores. Reject silent cloud fallback, network scanning, credential logging, and TLS/proxy bypasses.

Cycle-4 review correction: actual Edge testing found that native textarea change-on-blur could rebuild the preview and swallow a Start click. Deduplicating the effective preview request and retaining existing content avoids this layout mutation; expanded scope survives legitimate refreshes. Pointer/keyboard and delayed-response regression coverage is retained.

## 0.1.1.dev5 — Experimental Python-bundled Windows ONEDIR (2026-10-05)

- Preserve the source `Setup.cmd` / `Launch.cmd` route, existing cockpit, preflight,
  results and privacy behavior. Add an optional unsigned Windows x64 console build,
  built in a fresh CPython 3.13 environment using separate hash-locked build tools.
- Frozen normal launch runs the server in-process under the existing duplicate-launch
  mutex. Bundled resources and outer installation directory are independently protected
  from agent file access, alongside the state directory. State stays in LOCALAPPDATA.
- Fixed utility helpers isolate Windows DLL-search cleanup from concurrent server
  imports. They accept no arbitrary commands, use bounded pipes and timeouts, and place
  native descendants in a kill-on-close Job. Cancellation finishes acquiring the helper
  handle before killing/reaping it. Browser launch validates the exact loopback bootstrap
  URL and uses the Windows association, ignoring BROWSER command templates.
- Build output includes source/runtime/tool identity, dependency and native notices,
  per-file hashes, and ZIP checksum. Native redistribution review later blocked all
  binary uploads (see decision below); a packaging command is not release evidence.
- Independent early review caught inherited BROWSER command templates and sanitization
  after changing directory. Both were corrected, and browser startup now runs inside
  server cleanup protection. Unit regressions cover those boundaries.

Research decisions:
- [PyInstaller operating model](https://pyinstaller.org/en/stable/operating-mode.html):
  adopt inspectable ONEDIR with bundled Python and native Windows builds; defer one-file,
  MSIX, installers, automatic updates and additional architecture support.
- [PyInstaller runtime information](https://pyinstaller.org/en/stable/runtime-information.html):
  distinguish `_internal` resources from outer EXE location and avoid interpreting
  frozen `sys.executable` as a Python interpreter.
- [PyInstaller external-program guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html):
  isolate DLL-search reset in short-lived helper processes rather than race global
  state against background work. Browser helpers intentionally do not own the browser
  in a kill-on-close Job.
- [PyInstaller license exception](https://pyinstaller.org/en/stable/license.html) and
  [CPython licensing](https://docs.python.org/3/license.html): retain actual interpreter,
  wheel and native-library notices; inventory the distribution rather than assuming
  a freezer removes dependency obligations.
- [Microsoft app reputation guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation):
  Python-free startup does not establish company approval or universal compatibility.
  Reject warning bypasses, self-signed trust changes and claims of unrestricted use.

No live model service, user data, user PC or corporate security configuration is used
for acceptance. Final exact-head CI, ZIP inspection and screenshots are recorded in
handoff; until those pass, the portable binary remains unverified.

First Windows build correction: Git's automatic CRLF conversion changed the exact
bytes of checksum-pinned third-party notice supplements. Mark those reviewed files
as binary-preserved in `.gitattributes`; do not weaken or normalize away their hash
checks. The full source/install/Edge suite passed before the packaging gate caught
this issue. Binary upload remains separately blocked on native redistribution review.

Redistribution decision: actual Windows lxml wheel and matching build configuration
indicate static iconv inclusion. Exact corresponding-source/relink obligations are
not established. The setup-python CPython LICENSE also lacks expected native
component labels, so interpreter dependency notices need build-specific review.
Stop expanding legal packaging in this cycle: require an explicit evaluation-only
build, inventory available notices and unresolved components honestly, retain exact
hashes, and remove binary artifact upload entirely. Only internal execution tests,
reports/screenshots and non-binary manifests may proceed. No source-offer commitment
or distribution clearance is made.

Actual frozen execution reached authenticated Edge startup on the next internal run.
The acceptance driver then compared a Windows 8.3 temporary-directory alias with
the server's canonical long path. Correct the test to compare native filesystem
identities, keep exact protected-root assertions, and record synthetic preflight
scope for diagnostics. No production deny boundary is weakened.

## 0.1.1.dev6 — Selected-detail polling and stable navigation (2026-10-05)

- Preserve the full `/api/state` default contract. Add an explicit selected view
  retaining all public run/agent metadata and live reply eligibility while loading
  full retained logs, reports and save receipts only for the selected agent.
- Filter selected-run activity before the existing 100-item visible limit. Construct
  summaries before history allocation/redaction; never serialize everything first.
- Keep the cockpit layout, providers, configuration, file scopes, result provenance,
  export behavior and experimental portable distribution gates unchanged.
- Treat navigation as a generation, not merely an ID pair. A delayed response cannot
  regain authority after A → B → A. Loading is distinct from an empty history, and
  unchanged polling preserves existing controls and content nodes.
- Benchmark bounded synthetic small/medium/report-retention profiles through the
  real authenticated loopback endpoint. Keep conversation eligibility work in the
  fixture and separate body bytes, snapshot time, JSON time and HTTP measurements.
  These are development-machine observations, not production Windows guarantees.

Research decisions:
- [HTTP representation validators and conditional requests](https://www.rfc-editor.org/rfc/rfc9110.html#section-13):
  defer ETags and 304 optimization. Eligibility can change at a time limit without
  a new event or report; a sequence-only validator would hide a meaningful change.
  Existing authenticated `no-store` responses remain unchanged.
- [Fetch cancellation](https://developer.mozilla.org/en-US/docs/Web/API/AbortController/abort):
  cancellation can reduce unnecessary fetch work, but cannot substitute for checking
  which navigation owns a response. Adopt generation validation and a single-flight
  follow-up request; defer extra cancellation/streaming machinery in this cycle.
- [W3C status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html):
  distinguish loading from a true empty result without moving keyboard focus. Keep
  status updates separate from the agent's report and preserve stable DOM content.
- Defer automatic persistence, history eviction and explicit session forgetting.
  The 20-run admission limit still applies. A future manual forgetting feature needs
  a clear confirmation and race-safe active/question/stop-drain guards; it must never
  delete workspace files as a side effect.

No live inference, user PC, credentials, external telemetry or new runtime dependency
is required. Source changes remain in the existing draft PR; no merge or release is
part of this cycle. Exact-head Windows Edge and all CI jobs remain required evidence.

First Windows cycle-6 CI correction: the expanded deferred-frontend harness passed
its complete JavaScript source through `node -e`, exceeding Windows CreateProcess's
command-line limit. Stream the same source through `node -` stdin instead, with a
70,000-character regression. This changes test transport only; production behavior
and the behavioral assertions stay intact. Fresh exact-head CI is required.

The same Windows run passed all real Edge interaction checks, including compact
navigation and stable nodes, before benchmark-report output hit redirected cp1252
stdout. Emit ASCII-escaped JSON (decoded values unchanged), and test the CLI under
an explicit legacy encoding. This fixes evidence transport, not the measured API
serializer or application character handling. No initial failed job is called green.

## 0.1.1.dev7 — Stable configured-model attribution (2026-10-05)

- Reproduced the old roster relabeling completed work when the same current profile
  was changed or removed. Capture a small original-run descriptor and show it in
  the existing roster and selected-agent header. Both state projections preserve it.
- Mark identity as configured, with the actual response model unverified. Do not
  infer how a remote server resolved an alias or whether inference succeeded.
- Add run/agent/profile identity to the existing explicit report/receipt text export.
  Keep copying, record selection, report provenance and file-save semantics unchanged.
  Quote metadata names/model strings so embedded newlines cannot masquerade as fields.
- Normalize the already-optional profile label/model fields on settings validation.
  Review found that an accepted label-omitted configuration could otherwise fail the
  new descriptor capture and the existing preflight; missing models now reach the
  ordinary admission blocker. Required fields and accepted input scope do not change.
- Independent review found that redaction based only on current environment-key
  references could reveal an old descriptor after profile deletion. Redact the
  allowlisted descriptor at admission while its original references exist, then apply
  ordinary snapshot redaction again. Do not alter private inference configuration.

Research decisions:
- [MLflow run parameters](https://mlflow.org/docs/latest/api_reference/rest-api.html#log-param):
  adopt immutable run-scoped configuration identity rather than a mutable-profile
  join. Reject adding its service, telemetry, database or tracking dependency.
- [W3C PROV-DM](https://www.w3.org/TR/prov-dm/#section-entity-activity): retain the
  distinction between a generating activity's original context and later changed
  configuration. Reuse run/agent IDs; defer graphs and PROV serialization.
- [Microsoft HAX G11](https://www.microsoft.com/en-us/haxtoolkit/guideline/make-clear-why-the-system-did-what-it-did/):
  make explanations factual and limited, because an explanation can itself increase
  trust. Configured identity does not certify the served model or output quality.
- Reject broad configuration export, per-call traces and automatic archives. No
  endpoints, proxy settings, environment names, policy or file scopes are needed
  for this attribution descriptor. No runtime dependency or external call is added.

Deferred next-cycle candidate: `web_fetch` currently decodes all accepted text as
UTF-8 with replacement. A no-network synthetic Shift_JIS HTML response with an
explicit charset silently corrupted Japanese text. [W3C encoding guidance](https://www.w3.org/International/questions/qa-html-encoding-declarations)
and the [WHATWG Encoding Standard](https://encoding.spec.whatwg.org/) support a
separate declaration-aware decoding design, but label mappings, precedence, missing
and malformed declarations, and strict failure behavior need their own reviewed
scope. This cycle intentionally makes no web-fetch change.

Verification: focused descriptor/privacy/frontend tests and the actual Windows Edge
flow cover profile rename, model change, profile removal, new versus retained runs,
byte-identical old exports, and desktop/narrow layout. Final full-suite and exact-head
six-job CI results belong to the cycle handoff; earlier results are not evidence for
this head. Existing no-binary-distribution and no-live-inference gates remain.

First cycle-7 Edge acceptance caught a real tablet regression: the extra configured
identity line displaced the Send control in the long-question view. Narrow roster
identity also obscured assignment text. Keep roster identity to two compact lines
and make the full selected heading a bounded, keyboard-focusable scroll region.
The original strict composer geometry assertion remains, with added maximum-length
identity, keyboard-scroll persistence and narrow assignment-visibility checks.
A fresh exact-head full CI and screenshot review is required after this correction.

## 0.1.1.dev8 — Strict web text decoding with provenance (2026-10-05)

- Fix the reproduced Shift_JIS corruption with explicit supported declarations and
  CP932 compatibility labels; isolate decoding from the unchanged network transport.
- Select BOM, HTTP charset and bounded early HTML meta in precedence order. XHTML
  uses its own anchored XML declaration; JSON stays UTF-8. Report the actual codec,
  selection source and any UTF-8 assumption before long tool text.
- Fail visibly on selected unsupported/ambiguous declarations and malformed byte
  sequences, without echoing response bytes/labels or claiming the source is corrupt.
  Recommend an explicitly supported charset or UTF-8 export. Do not try another codec.
- Keep strict size/security limits and untrusted status. Compute output truncation
  after HTML extraction/control cleanup; flush trailing parser text before measuring.
- Independent review found and regressed five ambiguity paths: Unicode label folding
  (Kelvin sign), self-closing raw/inert HTML tags, double-escaped script content,
  ASCII XML prologs claiming UTF-16 and BOM-less NUL-interleaved JSON. The conservative
  meta scan now stops at the first raw/inert element instead of approximating browser
  script parsing. UTF-32 signatures are rejected before overlapping UTF-16 signatures.
- Add no-network declaration/error/boundary tests, a real local proxy/redirect fixture,
  and frozen-EXE acceptance through a fixed loopback proxy for every supported codec
  family plus malformed UTF-8. The proxy never forwards to the numeric public URL.

Research decisions:
- [WHATWG HTML encoding determination](https://html.spec.whatwg.org/multipage/parsing.html#determining-the-character-encoding):
  adopt BOM/header/meta ordering and the 1,024-byte bound. Defer locale guessing,
  full parsing/restarts and browser state-machine emulation. Stop before raw/inert
  content, documenting the intentional compatibility boundary.
- [WHATWG Encoding](https://encoding.spec.whatwg.org/#names-and-labels): adopt a closed
  label map and HTML legacy-label semantics. Reject arbitrary Python codec lookup,
  UTF-7/UTF-32 and byte transforms. Python legacy decoders are a bounded supported
  subset, not a claim of complete WHATWG decoder parity.
- [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259#section-8.1): keep application/json
  UTF-8 regardless of charset parameters; tolerate only the UTF-8 BOM.
- [RFC 7303](https://www.rfc-editor.org/rfc/rfc7303#section-3.2): keep XHTML separate
  from HTML meta processing, with BOM/header priority and XML declaration/default.
- [Python codec documentation](https://docs.python.org/3/library/codecs.html#standard-encodings):
  use fixed built-in codec names. A local Python 3.12 probe found windows-31j absent
  from runtime aliases despite newer documentation listing it; explicit aliases avoid
  version-dependent behavior. CP932 is intentionally selected for Japanese Windows
  compatibility, and actual frozen codec execution is tested rather than inferred.
- Reject charset-detector dependencies, external services, replacement decoding and
  silent retry guesses. A successful strict decode is not proof that a declaration
  matches the publisher's intended characters. Preserve the baseline interface.

Final local/exact-head Windows and six-job CI results belong to the cycle handoff.
The source PR remains draft; no merge, release or binary distribution is included.
## 0.1.1.dev9 — Bounded credential-mask lifetime (2026-10-05)

- Reproduced old-key exposure in retained tasks, assignments, names, roles,
  questions and mail metadata after replacing/removing a credential reference.
  Existing capture-redacted reports survived, but late responses, errors and
  successful save receipts could be retained raw. Completed-run continuation could
  also re-emit raw private conversation text after the original key was forgotten.
- Keep recognized values in a private, process-lifetime output-only registry,
  capped at 512 distinct values and 2 MiB UTF-8 payload. Preflight key/config changes
  atomically and reject overflow without dropping old masks or changing settings.
  Preserve exact-value matching, raw private protocol and workspace files.
- Separate masks from auth. Resolve new provider/diagnostic/search requests with
  current credentials; keep already-dispatched headers stable. Search uses a
  per-dispatch copy rather than a retained authenticating key. Remove memory auth
  when a provider ID disappears or its kind/endpoint/env source changes; likewise
  for search identity changes. Reserve `search` to remove the namespace collision.
- Independent review found that a large escaped regex alternation still stalled
  on mixed shared-prefix near-matches. Replace it with literal searches and a heap
  bounded by key count. Longest at the earliest match wins; emitted mask markers
  never become new input. Add the exact 512-key/2-MiB counterexample as a regression.
- Preserve full/selected state contracts, compact-history ownership, UI layout,
  strict web decoding, provider transport and the no-binary-distribution gates.

Research decisions:
- [OWASP Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html#data-to-exclude):
  adopt consistent masking of recognized credentials across public output sinks,
  safe failure handling and lifecycle regression tests. Do not add remote logging,
  arbitrary sensitive-data classification or new persistence.
- [OWASP Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html):
  keep credential use distinct from retired output masks. Document the increased
  process-memory lifetime and zeroization limit instead of claiming old secrets
  have been erased. No vault, background rotation or new credentials are added.
- [Python literal string search](https://docs.python.org/3/library/stdtypes.html#str.find)
  and [heap queues](https://docs.python.org/3/library/heapq.html): reuse standard
  library primitives and bound pending matches to the registry size. Reject regex
  alternation after the measured stall and a per-character Python trie because
  payload limits would not adequately bound its object overhead.
- Defer retroactive browser/clipboard/download recall and redaction of editable
  config metadata; those cannot be represented as harmless read-only projection
  changes. Explicitly narrow the public guarantee. No source can certify transformed
  secrets or arbitrary private data have been removed by an exact-value matcher.

Synthetic full/selected HTTP benchmarks now include ordinary and near-count-cap
registries, with a separate maximum-payload adversarial CLI. Exact-head Windows Edge
and all six CI jobs remain required evidence; local tests are not browser verification.
Source stays in draft PR2. No merge, release, binary upload or live inference is added.

The first dev9 Windows matrix exposed a test-only locale assumption: new assertions
read the UTF-8 Japanese settings file using the runner's cp1252 default. Make every
new text-fixture read explicitly UTF-8; production already used that encoding. Edge
passed the memory-key scenario but stopped at the environment replay's expected
synthetic authentication marker. Keep that assertion and add bounded, already-public
diagnostics while investigating; the failed run is not final acceptance evidence.

The next Windows matrix passed, while Edge failed earlier on an incomplete worker
record. Review of the [locked Playwright 1.62.1 polling implementation](https://github.com/microsoft/playwright/blob/v1.62.1/packages/playwright-core/src/server/frames.ts#L1523-L1540)
confirmed the shared test helper's async predicate returned a truthy Promise before
the fetched state was ready. Replace that helper with bounded explicitly awaited
API polling and return the exact satisfying snapshot. Regress delayed false/empty
states and receipt readiness without a browser; retain every original assertion.
Forty concurrent-polling loopback repetitions had passed because they already awaited
their state reads correctly. Production redaction was not changed for this correction.


## 0.1.1.dev10 — Contained corporate setup and actionable failures (2026-10-05)

- Reproduced inherited `PIP_PYTHON` and `global.python` redirecting even a read-only
  pip command into the base interpreter. Pin every pip invocation before config reads,
  reject alternate roots/interpreters and trusted-host settings, and require the
  expected real virtual-environment prefix before installing packages.
- Independent review reproduced quiet/scope flags hiding active forbidden settings
  and inherited pip logging writing captured configuration values elsewhere. Override
  inspection-only output/scope controls and its log destination, require a positive
  environment marker, and retain the original approved install transport settings.
- Report fixed failure stages/recovery guidance without echoing captured config,
  command arguments or raw runner exception strings. Preserve existing environments,
  hash-locked binary dependencies, offline isolation and no-network local app install.
- Add environment/config rejection, old-pip failure, private-prefix, stage privacy,
  real pinned-pip, hidden-config and log-suppression regressions. Preserve basic GUI,
  credential-mask lifetime/auth separation and all prior acceptance assertions.

Research decisions:
- [pip interpreter selection](https://pip.pypa.io/en/stable/topics/python-option/)
  and [configuration precedence](https://pip.pypa.io/en/stable/topics/configuration/):
  use explicit `--python` (introduced in pip 22.3), with safe failure for older pip.
  Inspect effective configuration through the supported CLI, not pip's internal API.
- [pip TLS certificates](https://pip.pypa.io/en/stable/topics/https-certificates/):
  preserve approved PEM and system-store behavior; reject trusted-host bypasses.
  System-store defaults depend on pip version, so do not silently upgrade pip or
  promise that Windows CA registration alone always resolves installation errors.
- [Python venv](https://docs.python.org/3.13/library/venv.html#how-venvs-work):
  validate private environment identity and retain the documented recreate-after-move
  recovery path. Do not delete environments or silently repair global Python.
- [Microsoft App Control events](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/event-id-explanations):
  provide the failure time/file to IT for existing-event diagnosis. Reject security
  bypasses, elevation, firewall changes and automated policy/log reconfiguration.
- Defer Python auto-download, a new installer UI and binary distribution. Existing
  approval, native-license and company-policy limits remain unchanged.

Exact-head Windows matrix, real Edge and evaluation-only package evidence are required
for the handoff. No live inference, binary uploads, release, merge or deployment.


The first dev10 Windows run passed Edge and the other matrix tests, but the new
Japanese-path setup regression failed while capturing `pip --version`. A deterministic
local reproduction using `PYTHONIOENCODING=cp1252` confirmed Windows-style redirected
output could not encode the extraction path. [Python's stream documentation](https://docs.python.org/3/library/sys.html#sys.stdout)
confirms Windows pipes use the ANSI code page. Give captured Python subprocesses a
private UTF-8 output/decoding contract, retain ordinary console behavior and caller
environment, and keep the original strict config-rejection assertion. This is a real
source-installer path fix; the failing run is not final acceptance evidence.

## 0.1.1.dev11 — Start/Stop response ownership and accepted-run recovery (2026-10-05)

- Reproduced a successful creation followed by failed state refresh leaving the
  original form enabled, and delayed creation overriding a newer navigation choice.
  Keep the accepted run ID until ordinary polling observes it, with no automatic
  creation replay. Disable Start while that accepted result remains unobserved.
- Distinguish accepted creation from an unknown response. A transport/server failure
  or malformed successful response does not prove no team was created. Explain the
  uncertainty before any user-directed retry; no server idempotency or persistence
  is claimed. Independent review caught successful JSON `null` bypassing that copy;
  validate response object shape and regress null/arrays/primitives/invalid JSON.
- Give user navigation, task-dialog lifecycle, draft edits, and settings navigation
  their own generations. A late result cannot regain authority after A → B → A or
  close a newly opened dialog. Automatic initial state selection is not a user
  navigation, so state observed before the POST response still reconciles correctly.
- Reproduced a late Stop failure enabling Stop on another completed team. Use one
  current-state predicate in both rendering and the action, with per-run pending
  guards across polling and independent concurrent Stops. Re-render after responses;
  never enable whichever shared button happens to be visible. Feedback names the
  affected run and cannot replace a newer operation's notice.
- Preserve the cockpit, drafts, focus, retained results/export, compact-state
  ownership, server-side stop/write draining, credential handling and settings lock.

Research decisions:
- [W3C status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html):
  use concise, programmatically exposed acceptance/waiting/error feedback without
  forcing focus to follow a late response. Preserve the existing live regions and
  avoid new modal alerts or verbose per-poll announcements.
- [HTTP idempotency and retries](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2):
  distinguish observing an accepted operation from repeating a non-idempotent POST.
  Do not replay an uncertain creation or claim cross-reload exactly-once behavior;
  a server-side idempotency contract is deferred to a separate design.
- [Microsoft HAX correction guidance](https://www.microsoft.com/en-us/haxtoolkit/guideline/support-efficient-correction/):
  adopt recoverable explicit state and retained drafts. Reject automatic retries
  that can duplicate a team's work. These principles do not establish full WCAG
  conformance or a model-quality guarantee.
- Defer a separate confirmed credential-recovery improvement: the server can accept
  a replacement memory-only key during a recoverable run error, but the UI settings
  lock requires stopping first. Unlocking only the correct saved credential identity
  needs its own review; no credential UI or authentication behavior changes here.

Tests use deferred synthetic transport through actual frontend callbacks and real
Windows Edge interactions. They retain all prior source/Engine/browser assertions.
Exact-head six-job CI and screenshot acceptance belong to the final handoff. No
live inference, user-PC operation, binary upload, release, merge or deployment.

## 0.1.1.dev12 — Saved-destination memory-key recovery (2026-10-05)

- Reproduced a recoverable authentication error leaving a run waiting while the
  UI disabled every key field. The server already supported atomic replacement
  followed by an explicit same-run human message without resetting any budget.
- Separate saved provider/Brave credentials from the active-run configuration lock.
  Disclose profile/search scope, saved endpoint/proxy and subsequent-request impact.
  Keep endpoint, model, rights, budgets and diagnostics locked during active work.
  SearXNG/page fetching do not use the search key; no speculative authentication
  error classifier, automatic probe, retry or new scheduler path is introduced.
- Require a server-owned saved-config revision on every key write, including clear.
  Reject missing/stale/malformed values before mutation, without a legacy bypass.
  Keep revision outside persisted config and run eligibility; config/key failures
  remain atomic with the bounded output-mask registry.
- Guard both provider and search keys against dirty/new settings. Add a GET-only
  discard/reload action. Independent review reproduced empty worker selections
  being silently defaulted during discard; preserve the entire task draft, including
  unavailable old choices and an above-new-limit worker count for explicit correction.
- Own pending writes per target across polls and close/reopen. Preserve unrelated
  pending requests and drafts; clear submitted/abandoned password inputs. Validate
  value-free acceptance receipts and report unknown outcomes without replay.
  Separate credential feedback from diagnostic feedback and avoid transiently
  disabling focused password inputs during ordinary polling.

Research decisions:
- [Microsoft HAX correction](https://www.microsoft.com/en-us/haxtoolkit/guideline/support-efficient-correction/)
  and [consequence guidance](https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction-design/):
  adopt a discoverable, bounded correction path with explicit next-request effects.
  Reject silent reruns and claims that storing a key validates authentication.
- [W3C status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html):
  keep concise status regions without moving focus or repeating text on each poll.
  No claim of full assistive-technology or WCAG conformance is made.
- [RFC 9110 conditional requests](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1):
  apply a server-checked stale-write precondition. The JSON configuration revision
  is an application contract, not an implementation claim for HTTP If-Match.
- [OWASP Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
  and [Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html#data-to-exclude):
  retain value-free statuses, authentication/mask separation and bounded retired
  masks. Defer vaults, persistence, automatic account-key rotation and new logging.

Tests use synthetic credentials and local fixtures only. They cover actual callbacks,
concurrent target writes, stale destination/revision races, keyboard and narrow Edge
flows, explicit same-run recovery and unchanged quota/stop/redaction protections.
Exact-head six-job CI, visual review and evaluation-only package evidence belong to
the final handoff. No live inference, real-key entry by the assistant, user-PC work,
binary distribution, merge, release or deployment is included.

The first dev12 push passed both Windows suites and real Edge; the PR Windows 3.11
job exposed an older timing assumption in the provider timeout test. Its 20-ms total
timeout expired before the loopback server observed any request. Preserve the exact
one-request/output-cap assertions, wait for real server receipt and hold the response
until the client's actual timeout instead of racing 20/100-ms sleeps. The bounded
five-second total timeout follows [aiohttp's total-timeout semantics](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientTimeout.total).
No provider production behavior changes. Fresh exact-head full CI remains required;
a passing sibling job does not turn the failed first run into acceptance evidence.

## 0.1.1.dev13 — Truthful first-task guidance (2026-10-05)

- Reproduced the task placeholder suggesting an edit-and-test workflow even though
  the app has no command, build or test runner. Local preflight correctly admitted
  its text, but the UI never explained this fixed execution boundary.
- Replace that example with a text-only memo task, which needs a configured model
  but no file or Web permissions. Keep essential capability/limit text beside the
  textarea with an accessible description, visible after the user starts typing.
- Offer three static examples in one native disclosure: text, permitted files and
  configured public-Web research. Explain existing absolute folders, independent
  read/write permissions, supported formats and non-browser page fetching.
- Preserve task drafts, selections, native disclosure state and Start ownership.
  Examples never fill a field, change settings, grant access or make a request.
  No prompt classifier, engine/API change, provider probe or runtime dependency.
- Align the README's first-use instructions with the current settings, task and
  model-list control labels. Retention guidance remains a separate deferred change.

Research decisions:
- [Microsoft HAX input examples](https://www.microsoft.com/en-us/haxtoolkit/pattern/g1-d-demonstrate-possible-system-inputs/):
  adopt examples grounded in available operations, avoiding its identified pitfall
  of implying unsupported capabilities. Reject clickable recipes that overwrite
  drafts or run tasks. No model-quality guarantee follows from showing an example.
- [Microsoft HAX introductory explanations](https://www.microsoft.com/en-us/haxtoolkit/pattern/g1-a-introductory-blurb/):
  use concise contextual help rather than a repeated onboarding tour or wizard.
- [GOV.UK native disclosure guidance](https://design-system.service.gov.uk/components/details/):
  collapse optional example depth, but keep essential execution limits visible.
  Use the existing cockpit's appearance, not a new imported design system.
- The HAX library's historical [Google Maps input example](https://www.microsoft.com/en-us/haxtoolkit/example/google-maps-demonstrate-possible-system-inputs/)
  illustrates expectation-setting outside agent apps. Adopt the principle, not its
  imagery or a claim about the current Maps interface.

Static tests check semantics and admission without external calls. Real Windows Edge
acceptance checks keyboard/native disclosure, draft/selection/expanded-state
preservation, no hidden actions and desktop/tablet/narrow geometry. Final exact-head
six-job CI and screenshot review belong to the handoff; local browser launch remains
blocked. No live inference, user-PC work, binary distribution, release or merge.


## 0.1.1.dev14 — Contextual history lifetime and safe restart guidance (2026-10-05)

- Reproduced the 21st-run blocker recommending restart without explaining the loss
  of reports, save receipts, conversations and memory-entered keys. Keep the same
  20-run admission boundary and error code, but describe the consequence and existing
  selected-record export first. Closed-server guidance no longer implies a full history.
- Show startup run count against 20 and a compact lifetime reminder beside SESSIONS.
  Keep detailed retention/exit distinctions in a native disclosure inside the existing
  bounded results panel, rather than consuming more crew-list space or showing a modal.
- Explain server lifetime separately from browser-tab close/reload and team Stop.
  Stop retains history and does not free a run slot. A new server restores settings,
  not conversations or memory-entered keys; environment keys use the next process's
  environment. Do not promise draft restoration or authentication after browser exit.
- Keep explicit one-record UTF-8 export, receipt/file separation, current-file-unverified
  notices, redaction, omission counters and all retention enforcement unchanged. Normal
  shutdown does not delete saved workspace files, but a historical receipt cannot
  certify their current existence or content. Download-start feedback is not completion.
- Independent review caught omitted-history wording implying in-memory deletion. Narrow
  it to the display histories: private model conversation retention is separate, and
  truncating a report does not prove the underlying full reply has been erased.

Research decisions:
- [Microsoft HAX feedforward](https://www.microsoft.com/en-us/haxtoolkit/pattern/g16-a-feedforward-convey-the-consequences-of-user-actions-before-the-user-takes-action/):
  adopt concrete pre-action consequences and proportionate noninterrupting indicators.
  Reject vague restart advice and automatic exports presented as safety guarantees.
- [W3C contextual help](https://www.w3.org/WAI/WCAG22/Understanding/help.html)
  and [status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html):
  keep help beside the operation without moving focus; preserve existing concise status
  feedback rather than announcing lifetime text on every poll. This is not a complete
  accessibility audit or a WCAG-conformance claim.
- [GOV.UK native details guidance](https://design-system.service.gov.uk/components/details/):
  keep essential lifetime information visible and optional distinctions in a disclosure.
  Preserve the established cockpit styling and keyboard/scroll behavior.
- Defer durable sessions, automatic backups, bulk export, workspace-file downloads,
  beforeunload prompts and authentication recovery. A missing browser cookie prevents
  authenticated access even while server history remains; no reauthentication promise
  follows from tab-reopen tests in a retained browser context.

Synthetic loopback tests distinguish reload/reconnect, team Stop, server cleanup and a
fresh server at the same settings directory. Real Windows Edge checks same-context
reload/tab reopen, explicit exports, keyboard and desktop/tablet/narrow geometry. Final
exact-head six-job CI and independent screenshots belong to the final handoff. Local
browser launch remains blocked. No live inference, user-PC work, binary distribution,
release, merge or deployment is included.

## 0.1.1.dev15 — Tool-result integrity after ordinary failures (2026-10-05)

- Reproduced a normal merged A1:B1 workbook edit targeting B1 that raised an
  uncaught AttributeError. Earlier writes and receipts survived, but the failed
  call and remaining calls had no results. An admitted human continuation replayed
  unmatched calls through all three provider adapters.
- Reject non-anchor merged-cell destinations with an instructive validation error
  before saving the XLSX request. Preserve the existing merge and workbook bytes;
  an explicitly requested top-left edit remains supported. No automatic unmerge,
  destination substitution or whole-file retry is introduced.
- Unexpected ordinary tool exceptions now close the attempted call and unexecuted
  remainder before entering the existing agent-error state. Preserve successful
  earlier results/receipts, native provider history and existing human admission.
  Keep the ambiguous attempted outcome explicit: a file may already be committed,
  even if its receipt was not recorded. No rollback or no-effects guarantee.
- Independent review expanded the same boundary through result-shape inspection,
  strict JSON serialization and tool-log preparation. These failures also append
  exactly one result per call; a failed logger is not retried. Nonfinite output is
  rejected rather than sent as nonstandard JSON. Fixed errors omit private exception
  details. Cancellation/draining and redaction-capacity fail-closed paths stay separate.

Research decisions:
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling):
  adopt explicit call-ID-linked result strings that can describe failure; preserve
  native output/reasoning replay. Reject dropping history to hide unmatched calls.
- [Claude tool-result handling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls):
  preserve immediate tool-result placement and results before human text. Keep the
  current adapters; defer an SDK/tool-runner migration and optional wire refinements.
- [openpyxl merged-cell implementation](https://openpyxl.readthedocs.io/en/stable/_modules/openpyxl/cell/cell.html):
  treat non-anchor MergedCell instances as invalid write destinations. Do not infer
  user intent to alter merges or target a different cell.
- Reject automatic batch retry, fabricated success/rollback results, broader file
  permissions and UI redesign. This is bounded failure recovery, not a transaction
  manager or a promise that external tools have no side effects.

Real temporary Office files and synthetic loopback providers test every adapter,
partial committed mutations, exact result ordering, explicit continuation and
all-or-none admission of malformed provider batches. Existing stop/drain, budget,
pause/finish, redaction and receipt tests remain. Final exact-head six-job CI,
Windows Edge evidence and evaluation-only package checks belong to the handoff;
no live inference, user-PC action, binary distribution, merge or release is included.

The first dev15 source Edge run exposed an older test synchronization race in the
credential late-rejection flow. It captured a reopened-dialog baseline before the
native queued `close` event cleared the previous pending notice. The sibling PR
Edge run passed, but that does not validate the failed source run. The acceptance
helper now registers before native Escape and waits for the actual close event;
both delayed-success and delayed-409 cases assert the cleared/unknown state before
releasing the real upstream response. Exact post-response equality assertions remain.
A deterministic helper test proves that removing the `open` flag alone is not
completion. Application frontend code is unchanged; fresh full CI is required.

## 0.1.1.dev16 — Provider completion evidence and Local refusals (2026-10-05)

- Reproduced absent/null Local and Anthropic completion reasons being accepted as
  final reports or executable write/finish batches. Non-streaming replies now need
  recognized terminal reasons. Proxies omitting those fields must return protocol
  evidence rather than relying on an HTTP 200 response being treated as completion.
- Reproduced OpenAI output marked incomplete/in-progress, or carrying error/incomplete
  details with optional response status omitted, executing tools. Reject explicit
  negative evidence before returning the normalized response. Preserve documented
  optional response/item status compatibility instead of requiring every field.
- Reproduced a valid Local Chat refusal with null content disappearing from both
  display and native replay. Preserve its text alongside ordinary content, retaining
  display redaction and exact native replay. Reject non-string/non-null refusal
  values and nonempty refusal paired with actual or declared tool calls.
- Keep existing error/waiting states, human continuation, earlier receipts/reports,
  native reasoning and consumed budgets. No rejected response enters conversation
  history. Retain dev15 tool-result closure unchanged.

Research decisions:
- [OpenAI Responses reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
  and the [official response type](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response.py):
  optional status fields are not themselves evidence of failure; explicit negative
  status, error and incomplete details must take precedence over parseable output.
- [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create):
  adopt documented non-streaming finish reasons and the optional refusal string.
  Preserve refusal in native assistant replay, not only in the display projection.
- [Anthropic stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons):
  non-streaming completion needs its stop reason. Empty `end_turn` responses can be
  legitimate, so reject a broad empty-response ban. Keep paused, truncated, context-
  limited and refusal stop reasons on the existing blocked path.
- Reject automatic retries, continuation, fallback, status-schema expansion and SDK
  migration. Defer generic tool-reason/content consistency tightening; Local servers
  returning `stop` with valid structured calls remain compatible. No live model calls.

Deterministic loopback tests cover whole-response admission with text and mutation
batches, preserved prior writes/receipts, budgets and explicit continuation; direct
adapter tests preserve optional metadata and empty terminals. Full local validation,
independent review, exact-head six-job CI, real Windows Edge and evaluation-only
package evidence are required for the handoff. Frontend files remain unchanged.


## 0.1.1.dev17 — Recheck deadlines after filesystem queue waits (2026-10-05)

- Reproduced a writer queued behind another worker's read at 0.024 seconds starting
  and committing at 10.114 seconds despite a configured 10-second run limit. The
  outer tool check happened before lock acquisition; dispatch did not recheck time.
- Recheck the existing deadline immediately inside the shared filesystem lock,
  before any path resolution or executor dispatch. An expired queued operation uses
  the existing safe limit error and ordinary tool-result path. Preserve attempted-call
  accounting, spent turns, exact result closure, earlier reports and save receipts.
- Preserve started-file-operation draining and cancellation unchanged. Do not wrap
  filesystem saves in a new cancellation timer, refund queued attempts, redefine
  model calls as HTTP attempts, or add a scheduler/status/retry/configuration path.

Research decisions:
- [Python asyncio locks](https://docs.python.org/3/library/asyncio-sync.html#asyncio.Lock):
  lock acquisition waits independently of the application's run deadline. Adopt a
  fresh admission check after the asynchronous wait, before filesystem access.
- [Python cancellation shielding](https://docs.python.org/3/library/asyncio-task.html#shielding-from-cancellation):
  preserve the existing shielded operation and explicit drain. Reject forced I/O
  cancellation as a substitute for preventing an operation from starting.
- [HTTP idempotency and retry guidance](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2):
  keep conservative existing transport retry behavior. The audit confirmed bounded
  Local 503 retries use one logical model call; cancellation during backoff prevents
  later attempts and releases the resource slot. No demonstrated bug justifies
  changing that accounting contract or expanding retries.

Deterministic tests isolate the engine clock and synchronize on actual contested
lock acquisition. All three loopback provider protocols cover pre/exact/post-deadline
admission, single and multi-call results, retained output, human rejection, queued
Stop and started-save draining. Direct guards cover every filesystem tool before
path access. Full local validation, independent review, exact-head six-job CI,
Windows Edge and evaluation-only package evidence are required for the handoff.
No live inference, user-PC action, browser retry, binary distribution, merge or release.


## 0.1.1.dev18 — Hash-bound native notice and provenance evidence (2026-10-05)

- Correct the interpretation of cycle 5's keyword flags. The exact reviewed CPython
  3.13.15 LICENSE contains unlabeled OpenSSL Apache 2.0 text and Microsoft Distributable
  Code conditions, plus libffi/bzip2 text with mixed original line endings. Record
  checked original-byte spans without changing or normalizing the copied notice.
- Pin a small offline reference index to its own SHA-256. Bind comparison to exact
  Python implementation/version/platform/architecture, OpenSSL/zlib observations,
  notice size/hash and individual native paths/sizes/hashes from the previously
  verified official embed archive. Unknown or changed identities remain unresolved.
- Keep keyword observations, notice evidence and native-file provenance separate
  from component and distribution-review statuses. Case-insensitive Windows paths
  preserve VCRUNTIME matches; ambiguous case duplicates do not match. UCRT/API-set
  files absent from this archive reference remain explicitly unindexed.
- Keep zlib 1.3.1 and XZ 5.2.5 source references precise. Their missing text in the
  copied notice is an observation, not an automatic legal violation. Do not conflate
  CPython zlib with lxml's separate native copy. Reconfirm the existing LGPL text's
  exact hash against GNU without treating notice possession as source/relink compliance.

Research decisions and remaining requirements are in
[NATIVE_REDISTRIBUTION](NATIVE_REDISTRIBUTION.md). Preserve historical PR snapshots;
link this correction rather than rewriting their original observations. Defer native
rebuilds, library substitution and release decisions. No dependency changes, feature
removal, new downloads during builds, legal acceptance or binary uploads are added.

The evaluated build remains explicitly evaluation-only and distribution-blocked even
when every available reference comparison matches. Full local tests, independent
review and fresh exact-head six-job CI / Windows evidence are required for the handoff.


## 0.1.1.dev19 — Keep keyboard focus on changing logs (2026-10-05)

- Reproduced focus dropping to BODY when a new log replaces the currently focused
  native thinking-detail summary. Unchanged polling and expanded-state retention
  already worked; existing browser tests did not cover focus during changing logs.
- Give summaries a stable run/agent/log focus key. Reuse conditional body-only
  restoration with preventScroll, including direct conversation-render callbacks.
  Missing and ambiguous IDs do not become guessed index-based focus identities.
- If a focused record actually leaves the same owner's loaded retained history,
  prefer the following surviving disclosure, then a preceding survivor, then a new
  disclosure or the existing conversation heading. Loading/selection changes,
  obsolete A→B→A responses and other focused controls never trigger this fallback.
- Independent review identified near-bottom auto-follow as a second way to lose the
  visible reading target. Preserve pane scroll while a disclosure owns focus; leave
  ordinary bottom-follow unchanged when users are elsewhere. Reveal a genuinely
  evicted record's fallback only as needed; a screenshot helper must not hide a
  clipped fallback by scrolling it into view before its visibility assertion. Keep drafts and open
  details, native keyboard behavior, the cockpit design and existing async ownership.

Research decisions:
- [W3C APG keyboard interface](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/#discernibleandpredictablekeyboardfocus):
  adopt logical focus persistence after DOM replacement instead of allowing BODY to
  silently become the active element. Reject unconditional refocusing after updates.
- [WCAG focus-order guidance](https://www.w3.org/WAI/WCAG22/Understanding/focus-order.html):
  keep the current reading context and an explicit nearby fallback when its actual
  record is gone. Do not add positive tabindex values or a custom navigation mode.
- [W3C disclosure pattern](https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/):
  preserve native details/summary and verify Space/Enter after new content arrives.
  Defer broad screen-reader/text-zoom certification, tablist conversion and redesign.

Tests use actual production polling/render callbacks with synthetic focus-removal
semantics, plus Windows Edge keyboard checks and desktop/narrow screenshots for
independent visual review. Full local checks and exact-head source/PR six-job CI are
required. Previous dev18 acceptance is retained in a versioned evidence record; the
frozen original PR archive and dev15 source ZIP remain untouched. No live inference,
new dependency, local browser retry, user-PC action, binary distribution, merge or release.


## 0.1.1.dev20 — Keep settings saves with their owning revision and drafts (2026-10-05)

- Reproduced two tabs reading one revision, one lowering the model-call limit,
  then the other's unrelated-label save silently restoring the older limit.
  Require the existing process-local revision on every configuration PUT. Check
  after body arrival immediately before the synchronous mutation; reject stale,
  missing and malformed ownership without a legacy bypass or partial mutation.
- Reproduced delayed Save selecting explicitly unchecked workers, clamping a newer
  task's worker count and clearing newer feedback. Preserve complete task drafts,
  including removed choices as unavailable, and restore logical worker-control
  focus only when DOM replacement left the document body focused.
- Separate accepted saved-baseline reconciliation from dialog feedback authority.
  Native close/reopen does not make an unchanged submitted form falsely dirty or
  let late success/failure paint a newer context. Dedicated draft generations and
  a captured-form comparison keep newer/ABA/unsignaled changes dirty. Independent
  review extended this through an initially pristine form with an unsignaled edit.
- Validate full value-free acceptance snapshots and the exact next revision. A
  conflict or uncertain outcome preserves the draft but blocks Save, credentials
  and model diagnostics until explicit saved-settings reload. Keep fields editable,
  explain that users should note their changes before discarding, and never replay
  a request or pretend a lost response proves no save occurred.
- Keep active-run locks, memory-only keys, atomic disk/mask behavior, budgets,
  configured destinations, native dialogs and existing cockpit styling. Migrate
  all synthetic API clients to the revision envelope without weakening tests.

Research decisions:
- [RFC 9110 conditional requests](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1):
  adopt a server-checked precondition for the demonstrated lost-update race. Reuse
  the application's JSON revision contract; do not claim HTTP If-Match compliance
  or add a general transaction/idempotency service.
- [W3C status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html):
  preserve concise accessible outcome feedback without moving focus or replacing
  newer feedback. This does not establish full accessibility conformance.
- [Microsoft HAX correction guidance](https://www.microsoft.com/en-us/haxtoolkit/guideline/support-efficient-correction/):
  preserve editable drafts and an explicit recovery path. Reject silent merge,
  automatic resend, guessed defaults and destructive automatic reload.
- Defer cross-tab live synchronization, retained edit history, persistent revision
  tokens, automatic backups and generic undo. Configuration conflicts justify this
  bounded precondition; no new provider, credential storage or runtime dependency.

Real loopback API tests cover two-client/concurrent/streamed-body/ABA races and
atomic failures; production callbacks cover old responses, exact draft retention,
malformed receipts and locks. Real Windows Edge acceptance covers two tabs, actual
queued native close, delayed committed responses, unknown transport and keyboard /
desktop/narrow state. Full local checks, independent source/evidence/pixel review
and exact-head six-job CI belong to the final handoff. Preserve the previous compact
PR overview as a hash-bound historical record, along with all earlier evidence and
the frozen original PR archive. No local browser retry, live inference, user-PC work,
binary distribution, merge or release is included.


## 0.1.1.dev21 — Preserve successful terminal batches at limits (2026-10-05)

- A bounded transition audit first found no discrepancy across 32 seeded schedules
  of 96 action-selection slots. A targeted terminal-state oracle then reproduced
  `finish_work` followed by a skipped sibling at the one-tool limit: the report was
  recorded successfully, but the skipped sibling changed the agent to an error.
  Independent review reproduced the same issue for `ask_user` and for a deadline
  crossed immediately after the successful terminal tool.
- Let the existing closed-batch flag precede budget admission for remaining skipped
  calls. Preserve one result per call, successful completion/question state, spent
  counters, rejection of expired continuation and existing text-only continuation.
  Invalid terminal arguments do not close the batch or bypass budget enforcement.
- Keep four controlled legal-session schedules and a small fixed-seed model as
  regression coverage. Use explicit events and task completion rather than sleeps,
  independent expected acceptance/counters/configuration rather than copying the
  engine's eligibility implementation, and readable normalized traces on failure.

Research decisions:
- [Hypothesis stateful-testing guidance](https://hypothesis.readthedocs.io/en/latest/stateful.html):
  adopt composable actions, returned identities, preconditions and invariants checked
  after each action. Keep a small standard-library scheduler instead of adding a new
  dependency or replacing the existing targeted tests.
- [TLA+ safety-property guidance](https://docs.tlapl.us/creating:safety): preserve
  reachable action traces for counterexamples. Distinguish bounded safety checks
  from exhaustive verification and liveness proofs; neither is claimed here.
- Defer a general model checker, automatic trace minimizer, broad fuzzing framework
  and runtime scheduler rewrite. The demonstrated false terminal error justifies a
  narrow guard-order repair, not new budget semantics or a product feature.

The 30 boundary cases use all three real loopback provider adapters; nine session
cases cover queue saturation/human priority, Stop/completion ordering, captured
gate-waiter credentials versus undispatched mailbox work, config-save ownership,
and four bounded model traces. Full local checks, independent review and exact-head
source/PR six-job CI belong to acceptance. UI design, permissions, runtime dependencies,
historical evidence and the dev15 source ZIP remain unchanged. No local browser retry,
live inference, user-PC action, binary upload, merge or release is included.


## 0.1.1.dev31 — automatic context compaction (local verification)

- Added bounded process-memory original records, source-aware history lookup, structured untrusted summaries, and safe complete native tool-batch retention.
- Added configurable compaction, request-character and optional heuristic model-token budgets, summary size/recent-context/archive controls, and visible compaction/omission status.
- Summary requests share ordinary run budgets/deadlines and preserve current history on failed/non-shrinking attempts; queued messages and cancellation retain their existing semantics.
- No persistent memory, provider-quality guarantee, exact token count, billing cap, live paid API test, deployment or publication is implied.
- Local verification results are recorded separately for this commit; prior published evidence describes its own exact revisions.


## Dev29–31 integration and Windows Edge acceptance (2026-10-07)

- Replayed accepted dev29 strict receipt, dev30 composition guards and dev31
  compaction changes as deliberate local versioned commits onto the final dev28
  source head `39f38227adcb92d8d94cbfd67fe984c3900d553d`. Preserved the final native
  viewport-only focused-question captures and strict pre/post/unchanged-poll geometry.
- Added a no-network compaction provider fixture and a full-engine regression:
  real long assistant/tool groups trigger a summary, then exact retained human and
  assistant originals are read through the actual history tool before completion.
- Added awaited Edge acceptance for Save/reload of compaction opt-out/re-enable and
  budgets; held actual summarizing status, completed status, unavailable record IDs,
  desktop/narrow screenshots and unchanged polls. The fixture release file controls
  only a deterministic provider wait, never production state or API behavior.
- Kept the dev29 six-scenario real-server receipt module imported and awaited. Added
  real-input synthetic composition-flag coverage for both key fields. Native OS IME
  remains untested; synthetic events do not establish IME integration.
- Archived the exact immediately preceding dev28 PR overview and its byte/hash
  manifest; all older evidence payloads remain unchanged. Historical standalone
  dev31 local results are explicitly separate from fresh integrated acceptance.
- Full integrated tests, independent review and exact-head source/PR CI must be
  checked before final acceptance. No local browser retry, live provider call,
  user-PC action, runtime dependency, Python bundling, merge or deployment.

- Independent integration review reproduced a test-fixture mismatch: the old
  credential-recovery fixture compared a human message to an exact two-key dict,
  while dev31 deliberately adds source-record and human-provenance metadata.
  Changed only the fixture assertion to verify exact role/text and human provenance;
  added a full-engine failure/key-replacement/explicit-human-resume regression.
  Both new real-engine fixture regressions pass. No production recovery behavior
  or permission check was relaxed.


### Dev31 first published acceptance correction (2026-10-07)

- Source `de05bc6e2b040397a612f81feca98420c740e4f2` ran on
  [source CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37608842232)
  and [PR CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37608847669).
  Both Edge jobs stopped at the earlier saved-result composer before the new
  receipt/compaction cases: the old deterministic provider emitted arbitrary raw
  protocol dictionaries. Real context sizing correctly rejected these invalid
  replay envelopes and made continuation unavailable.
- Independent review reproduced the cause with the real engine. Corrected only
  synthetic provider replay to valid Local/OpenAI/Anthropic envelopes, preserving
  private-protocol sentinels, exact tool-call/result groups and export exclusions.
  Added three real-engine saved-result/follow-up regressions plus three real-adapter
  replay-sizing regressions. Production validation, budgets and assertions remain
  strict; neither failed Edge job was retried unchanged.
- All four source matrix jobs passed. The initial PR Windows 3.11 job separately
  hit the existing 10-second Node helper subprocess timeout (1 failed, 1,511 passed,
  1 skipped); the other three PR matrix jobs passed. This initial failure remains
  visible. A new corrected head needs fresh source/PR acceptance; no success is
  inferred from the initial runs.
