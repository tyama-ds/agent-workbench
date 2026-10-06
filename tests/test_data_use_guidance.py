"""Copy-only data-use guidance preserves the existing readiness and network boundary."""
from pathlib import Path

from test_frontend import APP, run_javascript


ROOT = Path(__file__).resolve().parents[1]


def test_repeated_local_and_mixed_previews_keep_one_truthful_note_and_existing_scope():
    source = APP[APP.index('async function refreshPreflight('):APP.index('function setBriefOpen(')]
    result = run_javascript(r"""
const assert=require('node:assert/strict');
class Node {
  constructor(tag='p',className='',text=''){this.tag=tag;this.className=className;this.textContent=text;this.children=[];this.open=false;this.attrs={};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(name,value){this.attrs[name]=value;}
  querySelector(selector){return this.children.find(node=>selector==='.'+node.className)||null;}
}
const element=(...args)=>new Node(...args),nodes={preflightDetails:new Node(),preflightStatus:new Node(),preflightPending:new Node(),taskDialog:{open:true}};
const $=id=>nodes[id],ui={settingsRevision:1,settingsDirty:false,preflightRequest:0};
const inlineStatus=(node,text)=>{node.textContent=text;},errorText=error=>String(error),settleStartPointer=async()=>{};
const request={task:'Synthetic private draft',pm_profile:'local',worker_profiles:['openai'],max_workers:0};
const runPayload=()=>structuredClone(request),calls=[];
let response;
const api=async(url,options)=>{assert.equal(url,'/api/run-preflight');assert.equal(options.method,'POST');calls.push(options.body);return structuredClone(response);};
const local={role:'PM',label:'Local fixture',model:'synthetic',endpoint:'http://192.168.10.2:1234/v1/chat/completions',proxy:''};
const cloud={role:'worker',label:'Cloud fixture',model:'synthetic',endpoint:'https://model.example/responses',proxy:'https://proxy.example'};
const initial=JSON.stringify(request),observed=[];
""" + source + r"""
(async()=>{
  for(const mixed of [false,true,false,true]){
    request.max_workers=mixed?1:0;
    response={can_start:true,destinations:mixed?[local,cloud]:[local],scope:{read_roots:['/synthetic/input'],write_roots:['/synthetic/output'],deny_roots:['/synthetic/private']},web:{enabled:mixed,search_configured:mixed,fetch_enabled:mixed,search_endpoint:'https://search.example',proxy:'https://web-proxy.example'}};
    await refreshPreflight(++ui.preflightRequest);
    const target=nodes.preflightDetails,notes=target.children.filter(node=>node.textContent.startsWith('LOCAL APP は'));
    assert.equal(notes.length,1);assert.equal(notes[0].tag,'p');assert.equal(notes[0].className,'small');
    assert.equal(notes[0].children.length,0,'Guidance is text, not a new control');
    const text=target.children.map(node=>node.textContent).join('\n');
    for(const phrase of ['依頼・会話・作業方針・許可パス','ファイル内容やツール結果','検索語・取得 URL','プライベート LAN','別の PC','別のモデル接続先','PM・作業者すべての接続先・プロキシ','保存・再転送・学習利用','社内の承認範囲','判定しません'])assert(text.includes(phrase));
    assert(text.includes(local.endpoint));assert.equal(text.includes(cloud.endpoint),mixed);
    assert.equal(text.includes(cloud.proxy),mixed);assert.equal(text.includes('https://web-proxy.example'),mixed);
    const scope=target.querySelector('.readiness-scope');
    if(observed.length)assert.equal(scope.open,true,'Expanded scope survives every refresh');
    scope.open=true;
    observed.push({mixed,count:notes.length,children:target.children.length});
  }
  request.max_workers=0;assert.equal(JSON.stringify(request),initial);
  console.log(JSON.stringify({observed,calls:calls.length,status:nodes.preflightStatus.textContent}));
})().catch(error=>{console.error(error);process.exitCode=1;});
""")
    assert result['calls'] == 4
    assert [item['mixed'] for item in result['observed']] == [False, True, False, True]
    assert '外部通信・推論テストは行っていません' in result['status']


def test_docs_do_not_equate_file_access_local_address_or_web_off_with_approval():
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    security = (ROOT / 'SECURITY.md').read_text(encoding='utf-8')
    assert 'PM・作業者すべての接続先' in readme
    assert '会社の承認や外部への再転送がないことを保証しません' in readme
    assert '外部送信できない仕事では Local のみ・Web 無効にしてください' not in readme
    assert 'Reading a file authorizes' not in security
    assert 'Content read by a file tool enters the selected model conversation' in security
    assert 'every PM and worker endpoint and its downstream handling' in security
    assert 'does not establish organizational approval or prevent an endpoint from forwarding data' in security
    assert 'does not verify endpoint retention, training use, or onward transfer' in security
