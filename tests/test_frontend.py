"""UI contract and browser JavaScript checks without any model request."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def run_javascript(source):
    if not NODE:
        pytest.skip("Node is required for JavaScript checks")
    result = subprocess.run([NODE, "-e", source], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_javascript_parses():
    if not NODE:
        pytest.skip("Node is required")
    result = subprocess.run([NODE, "--check", str(STATIC / "app.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_assets_are_local_and_untrusted_content_has_no_html_sink():
    assert not re.search(r'<script[^>]*>(?!\s*</script>)', HTML)
    assert re.findall(r'<script[^>]+src="([^"]+)"', HTML) == ["/app.js"]
    assert re.findall(r'<link[^>]+href="([^"]+)"', HTML) == ["/styles.css"]
    assert not re.search(r"\son(?:click|load|error|submit)\s*=", HTML)
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function(", "localStorage", "sessionStorage"):
        assert sink not in APP
    assert ".textContent=" in APP


def test_settings_ui_covers_every_interface_field_without_persisting_raw_keys():
    prefix = APP[:APP.index("const STATUS_LABELS")]
    result = run_javascript(prefix + "console.log(JSON.stringify({groups:FIELD_GROUPS,profiles:PROFILE_FIELDS}));")
    config = json.loads((ROOT / "docs/interface.json").read_text(encoding="utf-8"))["config"]
    for section in ("paths", "local", "search", "limits"):
        assert {field[0] for field in result["groups"][section]} == set(config[section])
    assert {field[0] for field in result["profiles"]} | {"enabled"} == set(config["providers"][0])
    assert 'id="systemPolicy"' in HTML and 'id="policyPreview"' in HTML
    assert "config.system_policy=$('systemPolicy').value" in APP
    assert "'/api/secrets'" in APP and "secret.value=''" in APP
    assert not any(field[0] == "api_key" for field in result["profiles"])


def test_resource_summary_distinguishes_slots_from_workers_and_gpu_admission():
    function = re.search(r"function resourceLabel\(.*?\n\}", APP, re.S).group()
    result = run_javascript(function + r"""
console.log(JSON.stringify({empty:resourceLabel({}),state:resourceLabel({active:1,queued:2,gpu_readings:[{index:0,used_mb:7168,utilization_percent:35}]})}));
""")
    assert result["empty"] == "リソース情報なし"
    assert result["state"] == "Local 実行 1 · 待機 2 · VRAM 7168 MB · GPU 35%"
    assert "強制的に制限する機能ではありません" in HTML
    assert 'id="maxWorkers" type="number" min="0"' in HTML


def test_bootstrap_drops_token_before_authenticated_requests():
    drop = APP.index("history.replaceState(null,'',location.pathname+location.search)")
    bootstrap = APP.index("await api('/api/bootstrap'")
    config = APP.index("const response=await api('/api/config')")
    assert drop < bootstrap < config
    assert "'X-Workbench-Bootstrap':token},body:{}" in APP
    assert "credentials:'same-origin'" in APP


def test_auto_collaboration_limit_exposes_integer_bounds_and_blocked_run_state():
    prefix = APP[:APP.index("const ACTIVE_STATUSES")]
    result = run_javascript(prefix + "console.log(JSON.stringify({field:FIELD_GROUPS.limits.find(field=>field[0]==='max_auto_collaborations'),bounds:NUMBER_BOUNDS.limits.max_auto_collaborations}));")
    assert result["bounds"] == [0, 1000]
    assert result["field"][2] == "number"
    assert result["field"][4] == "1"
    assert "24" in result["field"][5]
    assert 'id="collaborationLimitNotice"' in HTML
    assert "run.auto_collaborations??0" in APP
    assert "run.max_auto_collaborations??24" in APP
    assert "run.collaboration_limit_reached===true" in APP


def test_run_and_reply_preserve_exact_visible_text_and_default_thinking_is_collapsed():
    assert "const task=$('taskInput').value" in APP
    assert "body:{task,pm_profile:" in APP
    assert "body:{text}" in APP
    assert "detail.open=expanded.has(id)" in APP
    assert "$('messageInput').value===text" in APP
    assert "ui.drafts.get(id)||''" in APP
    assert "if(ui.polling){await ui.pollPromise;if(fresh)return pollState();return;}" in APP


def test_cockpit_has_unique_targets_and_original_local_assets():
    ids = re.findall(r'\bid="([^"]+)"', HTML)
    assert len(ids) == len(set(ids))
    assert set(re.findall(r"\$\('([^']+)'\)", APP)) <= set(ids)
    for target in ('taskDialog', 'settingsDialog', 'agentTabs', 'teamMap', 'needsYou', 'agentSearch'):
        assert target in ids
    assert '<dialog id="taskDialog"' in HTML
    assert '<dialog id="settingsDialog"' in HTML
    assert 'content="dark"' in HTML
    css = (STATIC / 'styles.css').read_text(encoding='utf-8')
    assert 'align-items:safe center' in css
    assert 'min-width:max-content' in css
    assert 'prefers-reduced-motion' in css


def test_cockpit_filter_is_searchable_and_only_flags_real_questions():
    source = re.search(r"function filteredAgents\(.*?\n\}", APP, re.S).group()
    result = run_javascript("""
const ui={needsOnly:false};let search='';const $=()=>({value:search});
""" + source + """
const agents=[{id:'pm',name:'PM',status:'waiting',question:'Which team?'},{id:'w',name:'レビュー担当',task:'仕様の確認',status:'working'},{id:'q',name:'Queue',status:'queued'}];
search='レビュー';const searched=filteredAgents(agents).map(a=>a.id);
search='';ui.needsOnly=true;const needed=filteredAgents(agents).map(a=>a.id);
console.log(JSON.stringify({searched,needed}));
""")
    assert result == {'searched': ['w'], 'needed': ['pm']}


def test_dialog_repeated_open_close_preserves_drafts_and_focus():
    source = APP[APP.index('function showView('):APP.index('function filteredAgents(')]
    result = run_javascript("""
const nodes={taskDialog:{open:false,opens:0,closes:0,showModal(){this.open=true;this.opens++},close(){this.open=false;this.closes++}},settingsDialog:{open:false,opens:0,closes:0,showModal(){this.open=true;this.opens++},close(){this.open=false;this.closes++}}};const $=id=>nodes[id];
""" + source + """
setBriefOpen(true);setBriefOpen(true);setBriefOpen(false);setBriefOpen(false);
showView('settings');showView('settings');showView('work');showView('work');
console.log(JSON.stringify(Object.fromEntries(Object.entries(nodes).map(([k,v])=>[k,{open:v.open,opens:v.opens,closes:v.closes}]))));
""")
    assert all(value == {'open': False, 'opens': 1, 'closes': 1} for value in result.values())
    assert 'ui.startingRun=true' in APP and '||ui.startingRun' in APP
    assert 'ui.settingsLocked||ui.settingsSaving' in APP
    assert "window.addEventListener('popstate'" in APP
    assert 'dialog.close()' in APP


def test_poll_restores_same_logical_keyboard_control_and_does_not_steal_other_focus():
    source = re.search(r"function preserveControlFocus\(.*?\n\}", APP, re.S).group()
    result = run_javascript("""
const body={};let calls=0;const replacement={dataset:{focusKey:'agent:pm'},focus(){calls++}};
const document={body,activeElement:{dataset:{focusKey:'agent:pm'}},querySelectorAll:()=>[replacement]};
""" + source + """
preserveControlFocus(()=>{document.activeElement=body});
document.activeElement={dataset:{focusKey:'agent:pm'}};
preserveControlFocus(()=>{document.activeElement={dataset:{},id:'messageInput'}});
console.log(JSON.stringify({calls}));
""")
    assert result['calls'] == 1
    assert 'if(signature===ui.rosterSignature)return' in APP
    assert 'if(signature===ui.mapSignature)return' in APP
    assert 'if(signature===ui.tabsSignature)return' in APP
    assert 'if(signature===ui.runsSignature)return' in APP
