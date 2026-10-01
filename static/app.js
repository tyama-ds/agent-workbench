'use strict';

const FIELD_GROUPS = {
  paths: [
    ['read_roots','読み取りを許可する場所','paths','例：C:\\Projects\\research'],
    ['write_roots','書き込みを許可する場所','paths','例：C:\\Projects\\output'],
    ['deny_roots','アクセスを拒否する場所','paths','例：C:\\Users\\you\\.ssh'],
  ],
  search: [
    ['enabled','Web 検索を使う','checkbox'],
    ['provider','検索エンジン','select',[['searxng','SearXNG'],['brave','Brave Search']]],
    ['endpoint','検索の接続先 URL','url'],
    ['api_key_env','API キーの環境変数名','text','BRAVE_SEARCH_API_KEY'],
    ['proxy_url','検索用プロキシ URL（任意）','url'],
    ['timeout_seconds','検索タイムアウト（秒）','number',1],
    ['max_response_bytes','検索応答の最大サイズ（byte）','number',1024],
  ],
  local: [
    ['max_concurrent_requests','同時リクエスト数','number',1],
    ['queue_timeout_seconds','キューの待機上限（秒）','number',1],
    ['request_timeout_seconds','リクエスト上限（秒）','number',1],
    ['min_interval_seconds','開始間隔の下限（秒）','number',0,'any'],
    ['max_retries','再試行回数','number',0],
    ['retry_backoff_seconds','再試行の待機時間（秒）','number',0,'any'],
    ['gpu_guard_enabled','GPU の状態を確認してから開始','checkbox'],
    ['gpu_guard_fail_closed','GPU の状態を取得できない場合は開始しない','checkbox'],
    ['gpu_index','確認する GPU の番号','number',0],
    ['max_vram_mb','使用 VRAM のしきい値（MB）','number',0,'any','0 はこの条件を無効にします'],
    ['max_gpu_utilization_percent','GPU 使用率のしきい値（%）','number',0,'any','0 はこの条件を無効にします',100],
    ['gpu_wait_timeout_seconds','GPU の待機上限（秒）','number',0],
    ['gpu_poll_interval_seconds','GPU の確認間隔（秒）','number',0.1,'any'],
  ],
  limits: [
    ['max_workers','作業者数の最大値','number',0],
    ['max_model_calls','モデル呼び出し上限','number',1],
    ['max_tool_calls','ツール呼び出し上限','number',1],
    ['max_turns_per_agent','1エージェントのターン上限','number',1],
    ['max_run_seconds','1つの作業の制限時間（秒）','number',1],
    ['max_context_chars','コンテキスト上限（文字）','number',1000],
    ['max_output_tokens','1回の出力上限（token）','number',1],
    ['max_file_bytes','1ファイルのサイズ上限（byte）','number',1],
  ],
};
const PROFILE_FIELDS = [
  ['id','プロファイル ID','text','local-model'], ['label','表示名','text','Local LLM'],
  ['kind','接続方式','select',[['local','Local / OpenAI 互換'],['openai','OpenAI'],['anthropic','Anthropic']]],
  ['base_url','API の接続先 URL','url','http://127.0.0.1:11434/v1'],
  ['model','モデル名','text','サーバー上のモデル名をそのまま入力'],
  ['api_key_env','API キーの環境変数名','text','OPENAI_API_KEY'],
  ['proxy_url','クラウド用プロキシ URL（任意）','url'],
  ['request_timeout_seconds','リクエスト上限（秒）','number',1,'1','Local は共通設定の上限も適用されます'],
];
const STATUS_LABELS = {queued:'順番待ち',working:'作業中',running:'実行中',waiting:'回答待ち',waiting_human:'回答待ち',needs_input:'回答待ち',done:'完了',completed:'完了',error:'エラー',failed:'エラー',stopping:'停止処理中',stopped:'停止',idle:'待機'};
const NUMBER_BOUNDS={local:{max_concurrent_requests:[1,16],queue_timeout_seconds:[1,3600],request_timeout_seconds:[5,1800],min_interval_seconds:[0,120],max_retries:[0,3],retry_backoff_seconds:[0,60],gpu_index:[0,31],max_vram_mb:[0,1048576],max_gpu_utilization_percent:[0,100],gpu_wait_timeout_seconds:[1,3600],gpu_poll_interval_seconds:[.1,60]},limits:{max_workers:[0,16],max_model_calls:[1,1000],max_tool_calls:[1,5000],max_turns_per_agent:[1,100],max_run_seconds:[10,86400],max_context_chars:[4000,2000000],max_output_tokens:[128,65536],max_file_bytes:[1024,52428800]},search:{timeout_seconds:[1,60],max_response_bytes:[1024,4194304]}};
const ACTIVE_STATUSES = new Set(['queued','working','running','waiting','waiting_human','needs_input','idle','stopping']);
const ui = {config:null,secretStatus:{},state:{runs:[],agents:[],events:[],resources:{}},selectedRun:null,selectedAgent:null,settingsDirty:false,settingsLocked:false,authenticated:false,polling:false,drafts:new Map(),logSignature:'',busyMessage:false};
const $ = id => document.getElementById(id);

function element(tag, className, text) {
  const node=document.createElement(tag);
  if(className)node.className=className;
  if(text!==undefined)node.textContent=String(text);
  return node;
}
function statusLabel(value) { return STATUS_LABELS[value]||String(value||'待機'); }
function profileLabel(profile) { return profile ? `${profile.label||profile.id}${profile.model?' · '+profile.model:''}` : '未設定'; }
function lines(value) { return String(value||'').split(/\r?\n/).map(s=>s.trim()).filter(Boolean); }
function localTime(value) {
  if(!value)return '';
  const date=new Date(typeof value==='number'?(value<1e12?value*1000:value):value);
  return Number.isNaN(date.getTime())?'':date.toLocaleTimeString('ja-JP',{hour:'2-digit',minute:'2-digit'});
}
function getRun() { return ui.state.runs.find(run=>run.id===ui.selectedRun)||null; }
function getAgent() { return ui.state.agents.find(agent=>agent.id===ui.selectedAgent)||null; }
function errorText(error) { return error&&error.message?error.message:String(error||'処理に失敗しました'); }
function notice(text,error=false) { $('globalNotice').hidden=!text;$('globalNotice').textContent=text;$('globalNotice').classList.toggle('error',error); }
function inlineStatus(node,text,error=false) { node.textContent=text;node.classList.toggle('error',error); }
function setConnection(online,text) { $('connectionDot').classList.toggle('online',online);$('connectionDot').classList.toggle('error',!online);$('connectionStatus').textContent=text; }

async function api(path,options={}) {
  const headers={'Accept':'application/json',...(options.headers||{})};
  if(options.body!==undefined)headers['Content-Type']='application/json';
  let response;
  try { response=await fetch(path,{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(30000),...options,headers,body:options.body===undefined?undefined:JSON.stringify(options.body)}); }
  catch (error) { throw new Error(error.name==='TimeoutError'?'応答を確認できませんでした。再送信する前に、実行一覧と作業の状態を確認してください。':'接続できません。Agent Workbench のサーバーが起動しているか確認してください。'); }
  let data={};try { data=await response.json(); } catch (_) { /* report the HTTP status below */ }
  if(!response.ok||data.ok===false) {
    if(response.status===401) { ui.authenticated=false;setConnection(false,'認証が必要です');throw new Error('起動時に表示された専用リンクから開き直してください。'); }
    throw new Error(String(data.error||`リクエストに失敗しました（${response.status}）`));
  }
  return data;
}

function makeField(spec,value,prefix) {
  const [key,label,type,extra,step,help,max]=spec,id=`${prefix}-${key}`;
  const wrap=element('div','field'+(type==='checkbox'?' checkbox-field':''));
  const name=element('label','',label);name.htmlFor=id;
  let input;
  if(type==='select') { input=element('select');for(const [v,t] of extra){const option=element('option','',t);option.value=v;input.appendChild(option);} }
  else if(type==='paths') { input=element('textarea','path-input');input.rows=4;input.placeholder=extra||''; }
  else { input=element('input');input.type=type;if(['text','url'].includes(type))input.placeholder=extra||''; }
  input.id=id;input.dataset.key=key;input.autocomplete='off';
  if(type==='number'){const bounds=prefix.startsWith('profile-')?[5,1800]:NUMBER_BOUNDS[prefix]?.[key];input.min=String(bounds?.[0]??extra??0);input.step=step||'1';input.required=true;if(bounds||max!==undefined)input.max=String(bounds?.[1]??max);if(key==='max_vram_mb')input.step='1';}
  if(type==='checkbox'){input.checked=value===true;wrap.append(input,name);}
  else {input.value=type==='paths'?(Array.isArray(value)?value.join('\n'):''):String(value??'');wrap.append(name,input);}
  if(help)wrap.appendChild(element('small','',help));
  return wrap;
}
function inputValue(input) {
  if(input.type==='checkbox')return input.checked;
  if(input.type==='number'){const n=Number(input.value);if(!Number.isFinite(n)||input.value==='')throw new Error('数値の設定を確認してください。');return n;}
  if(input.classList.contains('path-input'))return lines(input.value);
  return input.value.trim();
}
function markSettingsDirty() { ui.settingsDirty=true;inlineStatus($('settingsStatus'),'未保存の変更があります。'); }

function appendProfile(profile,index,expanded=true) {
  const card=element('section','profile-editor');card.dataset.index=String(index);card._original={...profile};
  const toolbar=element('div','profile-toolbar'),heading=element('div','profile-heading-group');
  const title=element('h3','profile-title',profile.label||profile.id||'新しいプロファイル');
  const enabled=makeField(['enabled','使用する','checkbox'],profile.enabled!==false,`profile-${index}`);enabled.classList.add('choice');
  heading.append(title,enabled);toolbar.appendChild(heading);
  const actions=element('div','profile-actions'),toggle=element('button','button minor',expanded?'閉じる':'編集'),probe=element('button','button minor','接続確認'),remove=element('button','button minor remove','削除');
  toggle.type='button';toggle.dataset.readonly='true';toggle.setAttribute('aria-expanded',String(expanded));probe.type='button';remove.type='button';actions.append(toggle,probe,remove);toolbar.appendChild(actions);card.appendChild(toolbar);
  const content=element('div','profile-content');content.hidden=!expanded;card.classList.toggle('collapsed',!expanded);content.id=`profile-content-${index}`;toggle.setAttribute('aria-controls',content.id);
  toggle.addEventListener('click',()=>{content.hidden=!content.hidden;card.classList.toggle('collapsed',content.hidden);toggle.textContent=content.hidden?'編集':'閉じる';toggle.setAttribute('aria-expanded',String(!content.hidden));});
  const fields=element('div','profile-fields');PROFILE_FIELDS.forEach(spec=>fields.appendChild(makeField(spec,profile[spec[0]],`profile-${index}`)));content.appendChild(fields);card.appendChild(content);
  card.querySelector('[data-key="id"]').required=true;card.querySelector('[data-key="id"]').pattern='[A-Za-z][A-Za-z0-9_-]{0,63}';
  card.querySelector('[data-key="id"]').title='英字で始まる64文字以内の半角英数字・ハイフン・アンダースコア';
  card.querySelector('[data-key="base_url"]').required=true;
  card.querySelector('[data-key="label"]').addEventListener('input',event=>{title.textContent=event.target.value||'新しいプロファイル';});
  const secretRow=element('div','profile-secret'),secretField=element('div','field'),secretLabel=element('label','', '今回の起動中だけ使う API キー（任意）');
  const secret=element('input');secret.type='password';secret.autocomplete='new-password';secret.id=`profile-${index}-secret`;secretLabel.htmlFor=secret.id;
  secret.placeholder='未入力のままなら、指定した環境変数を使用';secretField.append(secretLabel,secret);
  const saveSecret=element('button','button secondary','キーをセット');saveSecret.type='button';
  const secretState=element('p','secret-status',ui.secretStatus[profile.id]?'キー設定あり。値は画面に取得しません。':'キーは設定ファイルに保存されません。再起動するとメモリ内のキーは消えます。');
  secretRow.append(secretField,saveSecret,secretState);content.appendChild(secretRow);
  const result=element('p','inline-status');result.setAttribute('role','status');card.appendChild(result);
  const kind=card.querySelector('[data-key="kind"]'),proxy=card.querySelector('[data-key="proxy_url"]');
  const updateKind=()=>{proxy.disabled=ui.settingsLocked||kind.value==='local';proxy.title=kind.value==='local'?'Local はプロキシを使わず直接接続します':'';};
  kind.addEventListener('change',()=>{if(kind.value==='local')proxy.value='';updateKind();});updateKind();
  remove.addEventListener('click',()=>{card.remove();markSettingsDirty();});
  probe.addEventListener('click',async()=>{
    if(ui.settingsDirty){inlineStatus(result,'接続確認の前に、設定を保存してください。',true);return;}
    probe.disabled=true;inlineStatus(result,'接続先を確認しています…');
    try { const response=await api('/api/provider-test',{method:'POST',body:{provider_id:card.querySelector('[data-key="id"]').value}});const models=Array.isArray(response.models)?response.models.slice(0,8).join(', '):'';inlineStatus(result,response.message||response.detail||`接続先から応答がありました。モデル実行は行っていません。${models?' モデル: '+models:''}`); }
    catch(error){inlineStatus(result,errorText(error),true);}finally{probe.disabled=ui.settingsLocked;}
  });
  saveSecret.addEventListener('click',async()=>{
    if(ui.settingsDirty){inlineStatus(result,'先にプロファイルの設定を保存してください。',true);return;}
    if(!secret.value){inlineStatus(result,'セットする API キーを入力してください。',true);return;}
    const key=secret.value,id=card.querySelector('[data-key="id"]').value;secret.value='';saveSecret.disabled=true;
    try { await api('/api/secrets',{method:'POST',body:{id,key}});ui.secretStatus[id]=true;secretState.textContent='今回の起動中に使うキーをセットしました。値は保存・再表示しません。';inlineStatus(result,'キーをセットしました。'); }
    catch(error){inlineStatus(result,errorText(error),true);}finally{saveSecret.disabled=ui.settingsLocked;}
  });
  $('profilesEditor').appendChild(card);
}
function renderSettings() {
  $('profilesEditor').replaceChildren();(ui.config.providers||[]).forEach((profile,index)=>appendProfile(profile,index,index===0));
  const containers={paths:'pathFields',search:'searchFields',local:'localFields',limits:'budgetFields'};
  for(const [group,specs] of Object.entries(FIELD_GROUPS)){const container=$(containers[group]);container.replaceChildren();specs.forEach(spec=>container.appendChild(makeField(spec,ui.config[group]?.[spec[0]],group)));}
  $('systemPolicy').value=ui.config.system_policy||'';ui.settingsDirty=false;inlineStatus($('settingsStatus'),'');setSettingsLock(true);
}
function collectConfig() {
  const config=structuredClone(ui.config);
  config.providers=[...$('profilesEditor').querySelectorAll('.profile-editor')].map(card=>{
    const profile={...card._original};card.querySelectorAll('[data-key]').forEach(input=>{profile[input.dataset.key]=inputValue(input);});return profile;
  });
  const ids=config.providers.map(profile=>profile.id);
  if(new Set(ids).size!==ids.length)throw new Error('プロファイル ID が重複しています。別の ID を指定してください。');
  if(!config.providers.length)throw new Error('プロファイルを1つ以上追加してください。');
  const containers={paths:'pathFields',search:'searchFields',local:'localFields',limits:'budgetFields'};
  for(const [group,id] of Object.entries(containers)){config[group]={...config[group]};$(id).querySelectorAll('[data-key]').forEach(input=>{config[group][input.dataset.key]=inputValue(input);});}
  config.system_policy=$('systemPolicy').value;
  return config;
}
function setSettingsLock(force=false) {
  const locked=ui.state.runs.some(run=>ACTIVE_STATUSES.has(run.status));ui.settingsLocked=locked;
  const disabled=locked||ui.settingsSaving===true;
  if(!force&&ui.lastSettingsDisabled===disabled)return;ui.lastSettingsDisabled=disabled;
  $('settingsForm').querySelectorAll('input,textarea,select,button').forEach(node=>{node.disabled=disabled&&node.dataset.readonly!=='true';});$('saveSettings').disabled=disabled;
  if(!disabled)$('profilesEditor').querySelectorAll('.profile-editor').forEach(card=>{card.querySelector('[data-key="proxy_url"]').disabled=card.querySelector('[data-key="kind"]').value==='local';});
  if(locked)inlineStatus($('settingsStatus'),'作業の実行中は設定を変更できません。チームが完了するか、停止してから変更してください。');
  else if(!ui.settingsDirty&&$('settingsStatus').textContent.startsWith('作業の実行中'))inlineStatus($('settingsStatus'),'');
}
function renderProfileChoices() {
  const previous=$('pmProfile').value,checked=new Set([...$('workerProfiles').querySelectorAll('input:checked')].map(input=>input.value));
  const profiles=(ui.config.providers||[]).filter(profile=>profile.enabled!==false&&profile.model&&profile.base_url);
  $('pmProfile').replaceChildren();$('workerProfiles').replaceChildren();
  if(!profiles.length){const empty=element('option','','設定でモデル名を指定してください');empty.value='';$('pmProfile').appendChild(empty);$('workerProfiles').appendChild(element('span','muted small','設定でプロファイルを完成させると選択できます。'));}
  profiles.forEach(profile=>{const option=element('option','',profileLabel(profile));option.value=profile.id;$('pmProfile').appendChild(option);});
  if(profiles.some(profile=>profile.id===previous))$('pmProfile').value=previous;
  profiles.forEach(profile=>{const label=element('label','choice'),input=element('input');input.type='checkbox';input.value=profile.id;input.checked=checked.size?checked.has(profile.id):profile.id===$('pmProfile').value;label.append(input,element('span','',profile.label||profile.id));$('workerProfiles').appendChild(label);});
  const limit=Number(ui.config.limits?.max_workers??3);$('maxWorkers').max=String(limit);$('maxWorkers').value=String(Math.min(Number($('maxWorkers').value),limit));
  $('policyPreview').textContent=ui.config.system_policy||'設定された共通方針はありません。';$('startRun').disabled=!profiles.length;
}
function showView(view) {
  const settings=view==='settings';$('workView').hidden=settings;$('settingsView').hidden=!settings;
  for(const [id,on] of [['navWork',!settings],['navSettings',settings]]){$(id).classList.toggle('active',on);if(on)$(id).setAttribute('aria-current','page');else $(id).removeAttribute('aria-current');}
  $('pageTitle').textContent=settings?'設定':'チームで作業';
  window.scrollTo(0,0);
}
function setBriefOpen(open) { $('runForm').hidden=!open;$('toggleBrief').textContent=open?'折りたたむ':'新しい依頼を入力';$('toggleBrief').setAttribute('aria-expanded',String(open));$('toggleBrief').closest('.task-panel').classList.toggle('compact',!open); }
function saveAgentDraft() { if(ui.selectedAgent)ui.drafts.set(ui.selectedAgent,$('messageInput').value); }
function selectAgent(id) { if(ui.selectedAgent!==id){saveAgentDraft();ui.selectedAgent=id;$('messageInput').value=ui.drafts.get(id)||'';ui.logSignature='';inlineStatus($('messageStatus'),'');}renderRun(); }
function selectRun(id) { saveAgentDraft();ui.selectedRun=id;const agents=ui.state.agents.filter(agent=>agent.run_id===id);ui.selectedAgent=agents.find(agent=>agent.role==='pm')?.id||agents[0]?.id||null;$('messageInput').value=ui.drafts.get(ui.selectedAgent)||'';ui.logSignature='';showView('work');setBriefOpen(false);renderState(); }

function renderRunList() {
  $('runCount').textContent=String(ui.state.runs.length);$('runList').replaceChildren();
  if(!ui.state.runs.length){$('runList').appendChild(element('p','sidebar-empty','ここにチームの作業が並びます'));return;}
  [...ui.state.runs].reverse().forEach(run=>{const button=element('button','run-link'+(run.id===ui.selectedRun?' selected':''));button.type='button';button.append(element('span','run-link-title',String(run.task||'作業').split('\n')[0]),element('span','run-link-meta',`${statusLabel(run.status)} · ${localTime(run.created_at)}`));button.addEventListener('click',()=>selectRun(run.id));$('runList').appendChild(button);});
}
function badge(status) { return element('span','status-badge '+(Object.hasOwn(STATUS_LABELS,status)?status:''),statusLabel(status)); }
function renderAgents(agents) {
  $('agentCount').textContent=String(agents.length);$('agentCards').replaceChildren();
  agents.forEach((agent,index)=>{
    const card=element('button','agent-card'+(agent.id===ui.selectedAgent?' selected':''));card.type='button';card.dataset.agentId=agent.id;card.setAttribute('aria-pressed',String(agent.id===ui.selectedAgent));
    const top=element('div','agent-card-top');top.append(element('span','agent-avatar',agent.role==='pm'?'PM':`W${index}`),badge(agent.status));
    const profile=ui.config?.providers?.find(item=>item.id===agent.profile_id);
    card.append(top,element('span','agent-name',agent.name||agent.id),element('span','agent-model',profileLabel(profile)),element('span','agent-task',agent.task||agent.question||agent.last_error||(agent.role==='pm'?'チームの作業を管理':'割り当てられた作業を担当')));
    card.addEventListener('click',()=>selectAgent(agent.id));$('agentCards').appendChild(card);
  });
}
function renderConversation(agent) {
  const available=Boolean(agent),run=getRun();$('messageForm').hidden=!available;
  $('conversationTitle').textContent=agent?(agent.name||agent.id):'作業ログ';
  $('conversationMeta').textContent=agent?`${agent.role==='pm'?'PM':'作業者'} · ${agent.profile_id} · ${agent.turns||0} turns`:'';
  $('conversationStatus').hidden=!agent;
  if(agent){$('conversationStatus').className='status-badge '+(Object.hasOwn(STATUS_LABELS,agent.status)?agent.status:'');$('conversationStatus').textContent=statusLabel(agent.status);}
  const question=agent?.question||'';$('humanQuestion').hidden=!question;$('humanQuestion').textContent=question?`判断が必要です\n${question}`:'';
  $('messageLabel').textContent=question?'質問への回答':'追加の指示';$('messageInput').placeholder=question?'選択肢や条件を確認し、回答を入力してください':'このエージェントへ追加の指示を送る';
  const stopping=['stopping','stopped'].includes(run?.status);$('sendMessage').disabled=!agent||ui.busyMessage||stopping;$('messageInput').disabled=!agent||stopping;
  const logs=Array.isArray(agent?.logs)?agent.logs:[],signature=JSON.stringify([agent?.id,logs]);
  if(signature===ui.logSignature)return;ui.logSignature=signature;
  const container=$('conversationLog'),atBottom=container.scrollHeight-container.scrollTop-container.clientHeight<70;
  const expanded=new Set([...container.querySelectorAll('details[open]')].map(node=>node.dataset.logId));container.replaceChildren();
  if(!logs.length){container.appendChild(element('div','empty-small',agent?'まだログはありません。作業が進むとここに表示されます。':'エージェントを選ぶと、作業の経過が表示されます。'));return;}
  logs.forEach((log,index)=>{
    const id=String(log.id??index),kind=String(log.kind||'assistant');
    if(log.thinking||kind==='thinking') {const detail=element('details','thinking');detail.dataset.logId=id;detail.open=expanded.has(id);detail.append(element('summary','',`モデルが返した思考の詳細${localTime(log.at)?' · '+localTime(log.at):''}`),element('pre','log-text',log.thinking||log.text||''));container.appendChild(detail);}
    if(kind==='thinking'||!log.text)return;
    const entry=element('article','log-entry '+(['user','tool'].includes(kind)?kind:'')),meta=element('div','log-meta');
    meta.append(element('span','log-role',({user:'あなた',assistant:agent.name||'エージェント',tool:'ツール',system:'システム',error:'エラー'})[kind]||kind),element('span','',localTime(log.at)));
    entry.append(meta,element('pre','log-text',log.text));container.appendChild(entry);
  });
  if(atBottom)container.scrollTop=container.scrollHeight;
}
function renderActivity(run) {
  const feed=$('activityFeed'),events=ui.state.events.filter(event=>event.run_id===run.id).slice(-100).reverse();feed.replaceChildren();
  if(!events.length){feed.appendChild(element('p','empty-small','エージェント同士の連絡や作業の進捗がここに表示されます。'));return;}
  events.forEach(event=>{const row=element('article','activity-item'),content=element('div');let title;
    if(event.kind==='mail')title=`${event.from||'エージェント'} → ${Array.isArray(event.to)?event.to.join(', '):event.to||'チーム'}`;
    else title=({spawn:'作業者が参加',question:'人への質問',error:'エラー',done:'作業完了',stopped:'作業を停止',tool:'ツール実行'})[event.kind]||event.kind||'進捗';
    content.append(element('div','activity-title',title),element('div','activity-body',event.text||''));row.append(element('time','activity-time',localTime(event.at)),content);feed.appendChild(row);
  });
}
function renderRun() {
  const run=getRun();$('activeRunSection').hidden=!run;$('workEmpty').hidden=Boolean(run);if(!run)return;
  $('activeRunTitle').textContent='チームの作業';$('activeRunStatus').className='status-badge '+(Object.hasOwn(STATUS_LABELS,run.status)?run.status:'');$('activeRunStatus').textContent=statusLabel(run.status);$('activeRunTask').textContent=run.task||'';
  $('stopRun').disabled=!ACTIVE_STATUSES.has(run.status)||run.status==='stopping';
  const metrics=$('runMetrics');metrics.replaceChildren();for(const [label,value] of [['モデル呼び出し',run.model_calls||0],['ツール実行',run.tool_calls||0],['作業者の上限',run.max_workers||0]]){const metric=element('span','metric',label);metric.appendChild(element('b','',value));metrics.appendChild(metric);}
  const agents=ui.state.agents.filter(agent=>agent.run_id===run.id);
  if(!agents.some(agent=>agent.id===ui.selectedAgent)){saveAgentDraft();ui.selectedAgent=agents.find(agent=>agent.role==='pm')?.id||agents[0]?.id||null;$('messageInput').value=ui.drafts.get(ui.selectedAgent)||'';}
  renderAgents(agents);renderConversation(getAgent());renderActivity(run);
}
function resourceLabel(resources,gpuIndex=0) {
  if(!resources||!Object.keys(resources).length)return 'リソース情報なし';
  const local=resources.local||resources,parts=[];
  if(local.active!==undefined)parts.push(`Local 実行 ${local.active}`);
  if(local.queued!==undefined)parts.push(`待機 ${local.queued}`);
  const gpu=resources.gpu||local.gpu||(local.gpu_readings||[]).find(row=>row.index===gpuIndex);
  if(gpu){const used=gpu.used_mb??gpu.used_memory_mb;if(used!==undefined)parts.push(`VRAM ${used} MB`);if(gpu.utilization_percent!==undefined)parts.push(`GPU ${gpu.utilization_percent}%`);}
  return parts.join(' · ')||'リソース情報を取得済み';
}
function renderState() {
  if(!ui.state.runs.some(run=>run.id===ui.selectedRun))ui.selectedRun=ui.state.runs.at(-1)?.id||null;
  renderRunList();renderRun();setSettingsLock();$('resourceSummary').textContent=resourceLabel(ui.state.resources,ui.config?.local?.gpu_index||0);
}
async function pollState(fresh=false) {
  if(!ui.authenticated)return;
  if(ui.polling){await ui.pollPromise;if(fresh)return pollState();return;}
  ui.polling=true;ui.pollPromise=(async()=>{
    try {const state=await api('/api/state');ui.state={runs:Array.isArray(state.runs)?state.runs:[],agents:Array.isArray(state.agents)?state.agents:[],events:Array.isArray(state.events)?state.events:[],resources:state.resources||{}};renderState();setConnection(true,'接続中');}
    catch(error){setConnection(false,'接続を確認してください');if(!ui.authenticated)notice(errorText(error),true);}
    finally{ui.polling=false;}
  })();return ui.pollPromise;
}
async function initialize() {
  $('navWork').addEventListener('click',()=>showView('work'));$('navSettings').addEventListener('click',()=>showView('settings'));
  $('toggleBrief').addEventListener('click',()=>setBriefOpen($('runForm').hidden));
  $('settingsForm').addEventListener('input',event=>{if(event.target.type!=='password')markSettingsDirty();});
  $('settingsForm').addEventListener('change',event=>{if(event.target.type!=='password')markSettingsDirty();});
  $('settingsForm').addEventListener('invalid',event=>{const card=event.target.closest('.profile-editor');if(card&&card.querySelector('.profile-content').hidden)card.querySelector('[data-readonly]').click();},true);
  $('addProfile').addEventListener('click',()=>{const indexes=[...$('profilesEditor').children].map(node=>Number(node.dataset.index));const index=Math.max(-1,...indexes)+1;appendProfile({id:`profile-${index+1}`,label:'新しいプロファイル',kind:'local',base_url:'http://127.0.0.1:11434/v1',model:'',api_key_env:'',proxy_url:'',enabled:true,request_timeout_seconds:180},index);markSettingsDirty();});
  $('settingsForm').addEventListener('submit',async event=>{
    event.preventDefault();if(ui.settingsLocked)return;
    ui.settingsSaving=true;setSettingsLock(true);inlineStatus($('settingsStatus'),'保存しています…');
    try {const config=collectConfig();const response=await api('/api/config',{method:'PUT',body:config});ui.config=response.config||config;ui.settingsDirty=false;renderProfileChoices();inlineStatus($('settingsStatus'),'設定を保存しました。');notice('');}
    catch(error){inlineStatus($('settingsStatus'),errorText(error),true);}finally{ui.settingsSaving=false;setSettingsLock(true);}
  });
  $('runForm').addEventListener('submit',async event=>{
    event.preventDefault();const task=$('taskInput').value;if(!task.trim())return;
    const workerProfiles=[...$('workerProfiles').querySelectorAll('input:checked')].map(input=>input.value);
    if(!workerProfiles.length&&Number($('maxWorkers').value)>0){inlineStatus($('runFormStatus'),'作業者に使ってよいプロファイルを1つ以上選んでください。',true);return;}
    $('startRun').disabled=true;inlineStatus($('runFormStatus'),'チームを準備しています…');
    try {const response=await api('/api/runs',{method:'POST',body:{task,pm_profile:$('pmProfile').value,worker_profiles:workerProfiles,max_workers:Number($('maxWorkers').value)}});const id=response.run?.id||response.id||response.run_id;await pollState(true);if(id)selectRun(id);inlineStatus($('runFormStatus'),'チームを開始しました。');notice('');}
    catch(error){inlineStatus($('runFormStatus'),errorText(error),true);}finally{$('startRun').disabled=!$('pmProfile').value;}
  });
  $('stopRun').addEventListener('click',async()=>{const run=getRun();if(!run)return;$('stopRun').disabled=true;try{await api(`/api/runs/${encodeURIComponent(run.id)}/stop`,{method:'POST',body:{}});await pollState(true);notice('チームに停止を要求しました。');}catch(error){notice(errorText(error),true);$('stopRun').disabled=false;}});
  $('messageInput').addEventListener('input',saveAgentDraft);
  $('messageForm').addEventListener('submit',async event=>{
    event.preventDefault();const agent=getAgent(),text=$('messageInput').value;if(!agent||!text.trim()||ui.busyMessage)return;ui.busyMessage=true;$('sendMessage').disabled=true;
    try {await api(`/api/agents/${encodeURIComponent(agent.id)}/message`,{method:'POST',body:{text}});if(ui.drafts.get(agent.id)===text)ui.drafts.delete(agent.id);if(ui.selectedAgent===agent.id&&$('messageInput').value===text)$('messageInput').value='';inlineStatus($('messageStatus'),'送信しました。');await pollState(true);}
    catch(error){inlineStatus($('messageStatus'),errorText(error),true);}finally{ui.busyMessage=false;renderConversation(getAgent());}
  });
  $('setSearchSecret').addEventListener('click',async()=>{const key=$('searchSecret').value;if(!key)return;$('searchSecret').value='';$('setSearchSecret').disabled=true;try{await api('/api/secrets',{method:'POST',body:{id:'search',key}});inlineStatus($('searchSecretStatus'),'今回の起動中に使うキーをセットしました。');}catch(error){inlineStatus($('searchSecretStatus'),errorText(error),true);}finally{$('setSearchSecret').disabled=ui.settingsLocked;}});
  try {
    const fragment=new URLSearchParams(location.hash.slice(1)),token=fragment.get('token');
    if(token){history.replaceState(null,'',location.pathname+location.search);await api('/api/bootstrap',{method:'POST',headers:{'X-Workbench-Bootstrap':token},body:{}});}
    const response=await api('/api/config');ui.config=response.config;ui.secretStatus=response.secret_status||{};ui.authenticated=true;renderSettings();renderProfileChoices();await pollState();
  }catch(error){notice(errorText(error),true);setConnection(false,'接続待ち');$('startRun').disabled=true;}
  window.setInterval(()=>pollState(),1000);
}
document.addEventListener('DOMContentLoaded',initialize,{once:true});
