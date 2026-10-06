'use strict';

const FIELD_GROUPS = {
  paths: [
    ['read_roots','読み取りを許可する場所','paths','例：C:\\Projects\\research'],
    ['write_roots','書き込みを許可する場所','paths','例：C:\\Projects\\output'],
    ['deny_roots','アクセスを拒否する場所','paths','例：C:\\Users\\you\\.ssh'],
  ],
  search: [
    ['enabled','Web 検索・ページ取得を使う','checkbox'],
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
    ['max_auto_collaborations','自動連携回数の上限','number',0,'1','初期値24回。委任・メール・完了通知の合計。0 は自動連携なし。',1000],
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
  ['kind','接続方式','select',[['local','Local / Chat Completions'],['openai','OpenAI / Responses'],['anthropic','Anthropic / Messages']]],
  ['base_url','API の接続先 URL','url','http://127.0.0.1:11434/v1'],
  ['model','モデル名','text','サーバー上のモデル名をそのまま入力'],
  ['api_key_env','API キーの環境変数名','text','OPENAI_API_KEY'],
  ['proxy_url','クラウド用プロキシ URL（任意）','url'],
  ['request_timeout_seconds','リクエスト上限（秒）','number',1,'1','Local は共通設定の上限も適用されます'],
];
const STATUS_LABELS = {queued:'順番待ち',working:'作業中',running:'実行中',waiting:'待機',waiting_human:'回答待ち',needs_input:'回答待ち',done:'完了',completed:'完了',error:'エラー',failed:'エラー',stopping:'停止処理中',stopped:'停止',idle:'待機'};
const NUMBER_BOUNDS={local:{max_concurrent_requests:[1,16],queue_timeout_seconds:[1,3600],request_timeout_seconds:[5,1800],min_interval_seconds:[0,120],max_retries:[0,3],retry_backoff_seconds:[0,60],gpu_index:[0,31],max_vram_mb:[0,1048576],max_gpu_utilization_percent:[0,100],gpu_wait_timeout_seconds:[1,3600],gpu_poll_interval_seconds:[.1,60]},limits:{max_workers:[0,16],max_auto_collaborations:[0,1000],max_model_calls:[1,1000],max_tool_calls:[1,5000],max_turns_per_agent:[1,100],max_run_seconds:[10,86400],max_context_chars:[4000,2000000],max_output_tokens:[128,65536],max_file_bytes:[1024,52428800]},search:{timeout_seconds:[1,60],max_response_bytes:[1024,4194304]}};
const ACTIVE_STATUSES = new Set(['queued','working','running','waiting','waiting_human','needs_input','idle','stopping']);
const ui = {config:null,secretStatus:{},state:{runs:[],agents:[],events:[],resources:{}},selectedRun:null,selectedAgent:null,selectionGeneration:0,compactState:false,loadedDetail:null,loadedEventsRun:null,detailError:false,settingsDirty:false,settingsLocked:false,authenticated:false,polling:false,pollAgain:false,drafts:new Map(),conversationViews:new Map(),logContext:'',logSignature:'',busyMessage:false,outputSelections:new Map(),outputContext:'',outputRequest:0,outputSignature:'',settingsRevision:0,preflightRequest:0,preflightTimer:null,preflightKey:'',startPointerActive:false,startPointerWaiters:[]};
Object.assign(ui,{navigationGeneration:0,taskDialogGeneration:0,taskDraftGeneration:0,taskDraftKey:'',workspaceGeneration:0,noticeGeneration:0,startOperation:null,stoppingRuns:new Map()});
Object.assign(ui,{configRevision:null,configStale:false,settingsReloading:false,credentialGeneration:0,credentialOperations:new Map()});
Object.assign(ui,{settingsDraftGeneration:0,settingsSaveOperation:null});
Object.assign(ui,{draftRevisions:new Map(),questionSearch:'',crewSearch:''});
Object.assign(ui,{taskReuseCandidate:null,taskReuseSource:null});
const $ = id => document.getElementById(id);

function element(tag, className, text) {
  const node=document.createElement(tag);
  if(className)node.className=className;
  if(text!==undefined)node.textContent=String(text);
  return node;
}
function statusLabel(value) { return STATUS_LABELS[value]||String(value||'待機'); }
function profileLabel(profile) { return profile ? `${profile.label||profile.id}${profile.model?' · '+profile.model:''}` : '未設定'; }
const PROFILE_KINDS={local:'Local / Chat Completions',openai:'OpenAI / Responses',anthropic:'Anthropic / Messages'};
function configuredProfile(agent) {
  const profile=agent?.configured_profile;
  return profile&&['id','label','kind','model'].every(key=>typeof profile[key]==='string')&&profile.id===agent.profile_id&&Object.hasOwn(PROFILE_KINDS,profile.kind)?profile:null;
}
function configuredProfileLabel(agent) {
  const profile=configuredProfile(agent);
  return profile?`開始時の設定: ${profileLabel(profile)} · ${PROFILE_KINDS[profile.kind]}`:'開始時の設定情報なし';
}
function lines(value) { return String(value||'').split(/\r?\n/).map(s=>s.trim()).filter(Boolean); }
function localTime(value) {
  if(!value)return '';
  const date=new Date(typeof value==='number'?(value<1e12?value*1000:value):value);
  return Number.isNaN(date.getTime())?'':date.toLocaleTimeString('ja-JP',{hour:'2-digit',minute:'2-digit'});
}
function getRun() { return ui.state.runs.find(run=>run.id===ui.selectedRun)||null; }
function getAgent() { return ui.state.agents.find(agent=>agent.id===ui.selectedAgent&&agent.run_id===ui.selectedRun)||null; }
function errorText(error) { return error&&error.message?error.message:String(error||'処理に失敗しました'); }
function notice(text,error=false) { ui.noticeGeneration++;$('globalNotice').hidden=!text;$('globalNotice').textContent=text;$('globalNotice').classList.toggle('error',error); }
function actionNotice(action,text,error=false) {
  if(action.noticeGeneration!==ui.noticeGeneration)return;
  notice(text,error);action.noticeGeneration=ui.noticeGeneration;
}
function inlineStatus(node,text,error=false) { node.textContent=text;node.classList.toggle('error',error); }
function setConnection(online,text) { $('connectionDot').classList.toggle('online',online);$('connectionDot').classList.toggle('error',!online);$('connectionStatus').textContent=text; }

async function api(path,options={}) {
  const headers={'Accept':'application/json',...(options.headers||{})};
  if(options.body!==undefined)headers['Content-Type']='application/json';
  let response;
  try { response=await fetch(path,{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(30000),...options,headers,body:options.body===undefined?undefined:JSON.stringify(options.body)}); }
  catch (error) { const failure=new Error(error.name==='TimeoutError'?'応答を確認できませんでした。再送信する前に、実行一覧と作業の状態を確認してください。':'接続できません。Agent Workbench のサーバーが起動しているか確認してください。');failure.outcomeUnknown=true;throw failure; }
  let data;try { data=await response.json(); } catch (_) { /* report the HTTP status below */ }
  if(!data||typeof data!=='object'||Array.isArray(data)){
    if(response.ok){const failure=new Error('応答の形式を確認できませんでした。');failure.outcomeUnknown=true;throw failure;}
    data={};
  }
  if(!response.ok||data.ok===false) {
    if(response.status===401) { ui.authenticated=false;setConnection(false,'認証が必要です');throw new Error('起動時に表示された専用リンクから開き直してください。'); }
    const failure=new Error(String(data.error||`リクエストに失敗しました（${response.status}）`));failure.outcomeUnknown=response.status>=500;failure.code=data.code;throw failure;
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
function invalidateDiagnostics() { ui.settingsRevision++;document.querySelectorAll('[data-probe-result]').forEach(node=>{node.textContent='設定または画面が変わりました。必要ならモデル一覧を再確認してください。';node.classList.remove('error');}); }
function markSettingsDirty() { ui.settingsDraftGeneration++;invalidateDiagnostics();ui.credentialGeneration++;ui.settingsDirty=true;clearCredentialInputs();setSettingsLock(true);inlineStatus($('settingsStatus'),'未保存の変更があります。キーの入力前に設定を保存するか、変更を破棄してください。'); }
function secretStatusText(configured) { return configured?'キー設定あり。値は画面に取得しません。':'キー未設定。必要ならキーを入力するか、環境変数の参照先を確認してください。'; }
function refreshSecretStatus(status) {
  ui.secretStatus=status||{};
  $('profilesEditor').querySelectorAll('.profile-editor').forEach(card=>{const id=card.querySelector('[data-key="id"]').value.trim();card.querySelector('.secret-status').textContent=secretStatusText(ui.secretStatus[id]);});
  inlineStatus($('searchSecretStatus'),secretStatusText(ui.secretStatus.search));
}

function savedCredentialTarget(id) {
  if(id==='search'){
    const search=ui.config?.search;
    return search?.provider==='brave'&&search.endpoint?{id,kind:'Brave Search',endpoint:search.endpoint,proxy:search.proxy_url||''}:null;
  }
  const profile=ui.config?.providers?.find(item=>item.id===id);
  return profile?{id,kind:PROFILE_KINDS[profile.kind],endpoint:profile.base_url,proxy:profile.proxy_url||''}:null;
}
function credentialTargetText(id) {
  const target=savedCredentialTarget(id);
  if(target)return `保存済み接続先: ${target.id} · ${target.kind} · ${target.endpoint} · プロキシ: ${target.proxy||'なし'}`;
  if(id==='search')return ui.config?.search?.provider==='searxng'?'保存済み設定は SearXNG です。この接続方式とページ取得では API キーを使用しません。':'Brave Search の接続先 URL を入力して設定を保存してから、キーを入力してください。';
  return '新しいプロファイルは、接続先の設定を保存してからキーを入力してください。';
}
function credentialControls() {
  const controls=[...$('profilesEditor').querySelectorAll('.profile-editor')].flatMap(card=>card._credential?[card._credential]:[]);
  return [...controls,{id:'search',input:$('searchSecret'),button:$('setSearchSecret'),status:$('searchSecretStatus'),result:$('searchSecretStatus'),target:$('searchCredentialTarget')}];
}
function clearCredentialInputs() { credentialControls().forEach(control=>{control.input.value='';}); }
function canSetCredential(id) {
  return ui.authenticated&&Number.isInteger(ui.configRevision)&&!ui.configStale&&!ui.settingsDirty&&!ui.settingsSaving&&!ui.settingsReloading&&
    !ui.credentialOperations.has(id)&&Boolean(savedCredentialTarget(id));
}
function refreshCredentialControls() {
  for(const control of credentialControls()){
    control.input.disabled=control.button.disabled=!canSetCredential(control.id);
    if(control.target)control.target.textContent=credentialTargetText(control.id);
  }
}
async function setCredential(control) {
  const id=control.id;
  if(!canSetCredential(id))return;
  if(!control.input.value){inlineStatus(control.result,'セットする API キーを入力してください。',true);return;}
  const key=control.input.value;control.input.value='';
  const action={revision:ui.configRevision,generation:ui.credentialGeneration,workspace:ui.workspaceGeneration};
  const current=()=>ui.credentialOperations.get(id)===action&&action.revision===ui.configRevision&&action.generation===ui.credentialGeneration&&
    action.workspace===ui.workspaceGeneration&&$('settingsDialog').open&&control.id===id&&!ui.settingsDirty;
  ui.credentialOperations.set(id,action);invalidateDiagnostics();setSettingsLock(true);
  inlineStatus(control.result,'保存済み接続先のキーをセットしています…');
  try {
    const response=await api('/api/secrets',{method:'POST',body:{id,key,config_revision:action.revision}});
    if(response.ok!==true||response.id!==id||response.config_revision!==action.revision||response.configured!==true){
      const failure=new Error('キーの更新応答を確認できませんでした。');failure.outcomeUnknown=true;throw failure;
    }
    if(!current())return;
    ui.secretStatus[id]=true;
    control.status.textContent='今回の起動中に使うキーをセットしました。値は保存・再表示しません。';
    inlineStatus(control.result,'キーをセットしました。有効性は未確認です。エラーで待機中の作業は、対象エージェントに指示を送って再試行してください。');
  } catch(error) {
    if(!current())return;
    if(error.code==='settings_changed'){ui.configStale=true;clearCredentialInputs();}
    inlineStatus(control.result,errorText(error)+(error.outcomeUnknown?' 更新されたかどうかは未確認です。自動再送信はしません。キー設定の有無だけでは今回の更新を確認できません。':''),true);
  } finally {
    if(ui.credentialOperations.get(id)===action)ui.credentialOperations.delete(id);
    invalidateDiagnostics();setSettingsLock(true);schedulePreflight();
  }
}
async function discardSettings() {
  if(ui.settingsSaving||ui.settingsReloading||ui.credentialOperations.size)return;
  const workspace=ui.workspaceGeneration;ui.settingsReloading=true;ui.credentialGeneration++;clearCredentialInputs();setSettingsLock(true);
  inlineStatus($('settingsStatus'),'保存済み設定を読み直しています…');
  try {
    const response=await api('/api/config');
    if(workspace!==ui.workspaceGeneration||!$('settingsDialog').open)return;
    if(!validSavedSettings(response,response.config_revision))throw new Error('保存済み設定を確認できませんでした。');
    ui.config=response.config;ui.configRevision=response.config_revision;ui.configStale=false;ui.secretStatus=response.secret_status||{};
    renderSettings();invalidateDiagnostics();renderProfileChoices(true);inlineStatus($('settingsStatus'),'未保存の変更を破棄し、保存済み設定を読み直しました。');
  } catch(error){if(workspace===ui.workspaceGeneration&&$('settingsDialog').open)inlineStatus($('settingsStatus'),errorText(error),true);}
  finally{ui.settingsReloading=false;setSettingsLock(true);schedulePreflight();}
}

function validSavedSettings(response,revision) {
  const record=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
  if(!record(response)||!Number.isSafeInteger(response.config_revision)||response.config_revision<0||response.config_revision!==revision)return false;
  const config=response.config,status=response.secret_status;
  if(!record(config)||config.version!==1||typeof config.system_policy!=='string'||!record(status)||typeof status.search!=='boolean')return false;
  if(!Array.isArray(config.providers)||!config.providers.length||new Set(config.providers.map(p=>p?.id)).size!==config.providers.length)return false;
  if(!config.providers.every(p=>record(p)&&PROFILE_FIELDS.every(([key,,type])=>type==='number'?Number.isFinite(p[key]):typeof p[key]==='string')&&
    p.id&&Object.hasOwn(PROFILE_KINDS,p.kind)&&typeof p.enabled==='boolean'&&typeof status[p.id]==='boolean'))return false;
  return Object.entries(FIELD_GROUPS).every(([group,specs])=>record(config[group])&&specs.every(([key,,type])=>{
    const value=config[group][key];
    if(type==='paths')return Array.isArray(value)&&value.every(path=>typeof path==='string');
    if(type==='checkbox')return typeof value==='boolean';
    return type==='number'?Number.isFinite(value):typeof value==='string';
  }));
}
async function saveSettings(event) {
  event.preventDefault();if(ui.settingsLocked||ui.settingsSaving||ui.settingsReloading||ui.credentialOperations.size||ui.configStale)return;
  let config;
  try{config=collectConfig();}catch(error){inlineStatus($('settingsStatus'),errorText(error),true);return;}
  if(!Number.isSafeInteger(ui.configRevision)||ui.configRevision<0){ui.configStale=true;setSettingsLock(true);return;}
  const action={config,revision:ui.configRevision,draft:ui.settingsDraftGeneration,workspace:ui.workspaceGeneration};
  const owns=()=>ui.settingsSaveOperation===action&&action.workspace===ui.workspaceGeneration&&action.draft===ui.settingsDraftGeneration&&$('settingsDialog').open;
  ui.settingsSaveOperation=action;ui.settingsSaving=true;clearCredentialInputs();setSettingsLock(true);inlineStatus($('settingsStatus'),'保存しています…');
  try {
    const response=await api('/api/config',{method:'PUT',body:{config_revision:action.revision,config:action.config}});
    if(!validSavedSettings(response,action.revision+1)){const failure=new Error('設定の保存応答を確認できませんでした。');failure.outcomeUnknown=true;throw failure;}
    if(ui.settingsSaveOperation!==action||ui.configRevision!==action.revision)return;
    // Acceptance updates the saved baseline even after close. It never submits,
    // discards, defaults or clamps the separate current task/settings drafts.
    let sameDraft=false;try{sameDraft=action.draft===ui.settingsDraftGeneration&&JSON.stringify(collectConfig())===JSON.stringify(action.config);}catch(_){}
    ui.config=response.config;ui.configRevision=response.config_revision;ui.configStale=false;ui.secretStatus=response.secret_status;ui.credentialGeneration++;
    ui.settingsDirty=!sameDraft;
    if(sameDraft)$('profilesEditor').querySelectorAll('.profile-editor').forEach(card=>{card._credential.id=inputValue(card.querySelector('[data-key="id"]'));});
    if(owns())invalidateDiagnostics();else ui.settingsRevision++;
    preserveControlFocus(()=>renderProfileChoices(true),()=>$('pmProfile'));
    if(owns()&&sameDraft){refreshSecretStatus(response.secret_status);inlineStatus($('settingsStatus'),'設定を保存しました。');}
  } catch(error) {
    if(ui.settingsSaveOperation!==action)return;
    if(error.outcomeUnknown||error.code==='settings_changed'){ui.configStale=true;if(owns()){clearCredentialInputs();invalidateDiagnostics();}else ui.settingsRevision++;}
    if(owns())inlineStatus($('settingsStatus'),errorText(error)+(error.outcomeUnknown?' 保存されたかどうかは未確認です。自動再送信はしません。変更内容を控えてから、保存済み設定を読み直してください。':error.code==='settings_changed'?' この下書きは保存していません。変更内容を控えてから、保存済み設定を読み直してください。':''),true);
  } finally {
    if(ui.settingsSaveOperation===action){ui.settingsSaveOperation=null;ui.settingsSaving=false;}
    setSettingsLock(true);schedulePreflight();
  }
}

function appendProfile(profile,index,expanded=true,saved=true) {
  const card=element('section','profile-editor');card.dataset.index=String(index);card._original={...profile};
  const toolbar=element('div','profile-toolbar'),heading=element('div','profile-heading-group');
  const title=element('h3','profile-title',profile.label||profile.id||'新しいプロファイル');
  const enabled=makeField(['enabled','使用する','checkbox'],profile.enabled!==false,`profile-${index}`);enabled.classList.add('choice');
  heading.append(title,enabled);toolbar.appendChild(heading);
  const actions=element('div','profile-actions'),toggle=element('button','button minor',expanded?'閉じる':'編集'),probe=element('button','button minor','モデル一覧を確認'),remove=element('button','button minor remove','削除');
  toggle.type='button';toggle.dataset.readonly='true';toggle.setAttribute('aria-expanded',String(expanded));probe.type='button';probe.dataset.probe='true';remove.type='button';actions.append(toggle,probe,remove);toolbar.appendChild(actions);card.appendChild(toolbar);
  const content=element('div','profile-content');content.hidden=!expanded;card.classList.toggle('collapsed',!expanded);content.id=`profile-content-${index}`;toggle.setAttribute('aria-controls',content.id);
  toggle.addEventListener('click',()=>{content.hidden=!content.hidden;card.classList.toggle('collapsed',content.hidden);toggle.textContent=content.hidden?'編集':'閉じる';toggle.setAttribute('aria-expanded',String(!content.hidden));});
  const fields=element('div','profile-fields');PROFILE_FIELDS.forEach(spec=>fields.appendChild(makeField(spec,profile[spec[0]],`profile-${index}`)));content.appendChild(fields);card.appendChild(content);
  card.querySelector('[data-key="id"]').required=true;card.querySelector('[data-key="id"]').pattern='[A-Za-z][A-Za-z0-9_-]{0,63}';
  card.querySelector('[data-key="id"]').title='英字で始まる64文字以内の半角英数字・ハイフン・アンダースコア';
  card.querySelector('[data-key="base_url"]').required=true;
  card.querySelector('[data-key="label"]').addEventListener('input',event=>{title.textContent=event.target.value||'新しいプロファイル';});
  const secretRow=element('div','profile-secret'),secretField=element('div','field'),secretLabel=element('label','', '今回の起動中だけ使う API キー（任意）');
  const secret=element('input');secret.type='password';secret.autocomplete='new-password';secret.id=`profile-${index}-secret`;secretLabel.htmlFor=secret.id;
  secret.dataset.credential='true';
  secret.placeholder='空欄では現在のキー設定を変更しません';secretField.append(secretLabel,secret);
  const saveSecret=element('button','button secondary','キーをセット');saveSecret.type='button';
  saveSecret.dataset.credential='true';
  const secretState=element('p','secret-status',secretStatusText(ui.secretStatus[profile.id]));
  secretRow.append(secretField,saveSecret,secretState);content.appendChild(secretRow);
  const target=element('p','credential-target muted small');content.appendChild(target);
  const result=element('p','inline-status');result.dataset.probeResult='true';result.setAttribute('role','status');card.appendChild(result);
  const secretResult=element('p','inline-status credential-result');secretResult.setAttribute('role','status');content.appendChild(secretResult);
  const kind=card.querySelector('[data-key="kind"]'),proxy=card.querySelector('[data-key="proxy_url"]');
  const updateKind=()=>{proxy.disabled=ui.settingsLocked||kind.value==='local';proxy.title=kind.value==='local'?'Local はプロキシを使わず直接接続します':'';};
  kind.addEventListener('change',()=>{if(kind.value==='local')proxy.value='';updateKind();});updateKind();
  remove.addEventListener('click',()=>{card.remove();markSettingsDirty();});
  probe.addEventListener('click',async()=>{
    if(ui.settingsDirty||ui.configStale){inlineStatus(result,ui.configStale?'モデル一覧の確認前に、保存済み設定を読み直してください。':'モデル一覧の確認前に、設定を保存してください。',true);return;}
    const revision=ui.settingsRevision,profileId=card.querySelector('[data-key="id"]').value;
    const current=()=>revision===ui.settingsRevision&&card.isConnected&&$('settingsDialog').open&&card.querySelector('[data-key="id"]').value===profileId;
    probe.disabled=true;inlineStatus(result,'保存済み接続先のモデル一覧を確認しています。推論は実行しません…');
    try {
      const response=await api('/api/provider-test',{method:'POST',body:{provider_id:profileId}});
      if(!current())return;
      const models=Array.isArray(response.models)?response.models.slice(0,8).join(', '):'';
      const observed=response.selected_model==='observed'?'指定モデルが一覧にあります。':'指定モデルの利用可否は一覧だけでは判断できません。手入力の別名も使用できます。';
      inlineStatus(result,`モデル一覧を取得しました。${models?' モデル: '+models:' 一覧は空です。'} ${observed}${response.list_incomplete?' 一覧には続き・省略がある可能性があります。':''} 推論・ツール動作は未確認です。`);
    } catch(error){if(current())inlineStatus(result,errorText(error)+' 推論・ツール動作は未確認です。',true);}
    finally{probe.disabled=Boolean(ui.settingsLocked||ui.settingsSaving||ui.settingsReloading||ui.configStale||ui.credentialOperations.size);}
  });
  card._credential={id:saved?profile.id:null,input:secret,button:saveSecret,status:secretState,result:secretResult,target};
  saveSecret.addEventListener('click',()=>setCredential(card._credential));
  secret.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();setCredential(card._credential);}});
  $('profilesEditor').appendChild(card);
}
function renderSettings() {
  ui.settingsDraftGeneration++;
  ui.credentialGeneration++;
  $('profilesEditor').replaceChildren();(ui.config.providers||[]).forEach((profile,index)=>appendProfile(profile,index,index===0));
  const containers={paths:'pathFields',search:'searchFields',local:'localFields',limits:'budgetFields'};
  for(const [group,specs] of Object.entries(FIELD_GROUPS)){const container=$(containers[group]);container.replaceChildren();specs.forEach(spec=>container.appendChild(makeField(spec,ui.config[group]?.[spec[0]],group)));}
  $('systemPolicy').value=ui.config.system_policy||'';ui.settingsDirty=false;inlineStatus($('settingsStatus'),'');refreshSecretStatus(ui.secretStatus);setSettingsLock(true);
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
  const disabled=locked||ui.settingsSaving===true||ui.settingsReloading||ui.credentialOperations.size>0;
  $('settingsForm').querySelectorAll('input,textarea,select,button').forEach(node=>{if(node.dataset.credential!=='true')node.disabled=disabled&&node.dataset.readonly!=='true'||ui.configStale&&(node.type==='submit'||node.dataset.probe==='true');});$('saveSettings').disabled=disabled||ui.configStale;
  if(!disabled)$('profilesEditor').querySelectorAll('.profile-editor').forEach(card=>{card.querySelector('[data-key="proxy_url"]').disabled=card.querySelector('[data-key="kind"]').value==='local';});
  refreshCredentialControls();$('discardSettings').disabled=Boolean(ui.settingsSaving||ui.settingsReloading||ui.credentialOperations.size);
  const lockText=(locked?'作業の実行中は接続先・モデル・権限を変更できません。保存済み接続先のキーだけ変更できます。':'')+(ui.configStale?' 保存済み設定が変わったか、保存結果が未確認です。変更内容を控えてから「変更を破棄・保存済み設定を読み直す」で確認してください。保存・キー更新・モデル確認はそれまで行いません。':'');
  if($('settingsLockStatus').textContent!==lockText)$('settingsLockStatus').textContent=lockText;
}
function renderProfileChoices(preserveDraft=false) {
  const previous=$('pmProfile').value,checked=new Set([...$('workerProfiles').querySelectorAll('input:checked')].map(input=>input.value));
  const profiles=(ui.config.providers||[]).filter(profile=>profile.enabled!==false&&profile.model&&profile.base_url);
  $('pmProfile').replaceChildren();$('workerProfiles').replaceChildren();
  if(!profiles.length){const empty=element('option','','設定でモデル名を指定してください');empty.value='';$('pmProfile').appendChild(empty);$('workerProfiles').appendChild(element('span','muted small','設定でプロファイルを完成させると選択できます。'));}
  profiles.forEach(profile=>{const option=element('option','',profileLabel(profile));option.value=profile.id;$('pmProfile').appendChild(option);});
  if(preserveDraft&&previous&&!profiles.some(profile=>profile.id===previous)){const option=element('option','',`${previous}（保存済み設定では利用不可）`);option.value=previous;$('pmProfile').appendChild(option);}
  if(preserveDraft||profiles.some(profile=>profile.id===previous))$('pmProfile').value=previous;
  const choices=[...profiles,...(preserveDraft?[...checked].filter(id=>!profiles.some(profile=>profile.id===id)).map(id=>({id,label:`${id}（保存済み設定では利用不可）` })):[])];
  choices.forEach(profile=>{const label=element('label','choice'),input=element('input');input.type='checkbox';input.value=profile.id;input.dataset.focusKey=`task-worker:${profile.id}`;input.checked=preserveDraft||checked.size?checked.has(profile.id):profile.id===$('pmProfile').value;label.append(input,element('span','',profile.label||profile.id));$('workerProfiles').appendChild(label);});
  const limit=Number(ui.config.limits?.max_workers??3);$('maxWorkers').max=String(limit);if(!preserveDraft)$('maxWorkers').value=String(Math.min(Number($('maxWorkers').value),limit));
  $('policyPreview').textContent=ui.config.system_policy||'設定された共通方針はありません。';trackTaskDraft();syncStartControl();
}
function showView(view) {
  if(view==='settings') { if(!$('settingsDialog').open){ui.workspaceGeneration++;$('settingsDialog').showModal();} }
  else { if($('settingsDialog').open){ui.workspaceGeneration++;$('settingsDialog').close();} }
  reconcileTaskReuse();
}
function runPayload() {
  return {task:$('taskInput').value,pm_profile:$('pmProfile').value,worker_profiles:[...$('workerProfiles').querySelectorAll('input:checked')].map(input=>input.value),max_workers:Number($('maxWorkers').value)};
}
function trackTaskDraft(event) {
  // An actual edit also invalidates a choice when numeric parsing would hide
  // it (0 → blank, 1 → 01), or when the user re-enters the same value.
  if(ui.taskReuseCandidate&&['input','change'].includes(event?.type))clearTaskReuse('入力を変更したため、置き換えを取り消しました。現在の入力は残しています。');
  const key=JSON.stringify(runPayload());
  if(key!==ui.taskDraftKey){ui.taskDraftKey=key;ui.taskDraftGeneration++;}
  reconcileTaskReuse();
  if(ui.taskReuseSource&&$('taskInput').value!==ui.taskReuseSource.text){ui.taskReuseSource=null;$('taskReuseProvenance').hidden=true;}
  showPendingStart();
}
function syncStartControl() { $('startRun').disabled=Boolean(ui.startingRun||ui.taskReuseCandidate)||!$('pmProfile').value;syncTaskReuseControl(); }
function taskEditorText(text) { return text.replace(/\r\n?/g,'\n'); }
function taskReuseDraftKey() { return JSON.stringify([runPayload(),$('maxWorkers').value]); }
function taskReuseIssue(run) {
  if(typeof run?.task!=='string'||!run.task.trim()||run.task.includes('\0'))return '表示用の依頼文を取得できないため、下書きには使えません。';
  if(taskEditorText(run.task).length>16000)return '表示用の依頼文が入力欄の上限（16,000文字・UTF-16）を超えています。省略せずに移せないため、内容を確認して入力してください。';
  return '';
}
function syncTaskReuseControl() {
  const issue=taskReuseIssue(getRun()),pending=Boolean(ui.startingRun||ui.startOperation);
  $('reuseTask').disabled=Boolean(issue)||pending;
  $('taskReuseAvailability').hidden=!issue&&!pending;
  $('taskReuseAvailability').textContent=pending?'開始要求の結果を確認中です。確認できるまで、別の依頼文は下書きに移せません。':issue;
}
function ownsTaskReuse(candidate) {
  const run=getRun();
  return ui.taskReuseCandidate===candidate&&$('taskDialog').open&&!$('settingsDialog').open&&!ui.startingRun&&!ui.startOperation&&
    candidate.run===run?.id&&candidate.rawText===run.task&&candidate.navigation===ui.navigationGeneration&&
    candidate.selection===ui.selectionGeneration&&candidate.dialog===ui.taskDialogGeneration&&candidate.draft===ui.taskDraftGeneration&&
    candidate.workspace===ui.workspaceGeneration&&candidate.payload===taskReuseDraftKey()&&!taskReuseIssue(run);
}
function clearTaskReuse(message='') {
  const pending=Boolean(ui.taskReuseCandidate),focused=[$('keepTaskDraft'),$('replaceTaskDraft'),$('taskReusePreview')].includes(document.activeElement);
  ui.taskReuseCandidate=null;$('taskReuseConfirm').hidden=true;$('taskReusePreview').textContent='';
  if(message&&$('taskDialog').open&&!$('settingsDialog').open)inlineStatus($('taskReuseStatus'),message);
  else if(pending)inlineStatus($('taskReuseStatus'),'');
  syncStartControl();
  if(focused&&$('taskDialog').open&&!$('settingsDialog').open)$('taskInput').focus({preventScroll:true});
}
function reconcileTaskReuse() {
  if(ui.taskReuseCandidate&&!ownsTaskReuse(ui.taskReuseCandidate)){
    clearTaskReuse('入力または表示が変わったため、置き換えを取り消しました。現在の入力は残しています。');
    if($('taskDialog').open&&!$('settingsDialog').open)schedulePreflight();
  }
}
function adoptTaskReuse(source) {
  clearTaskReuse();
  if($('taskInput').value!==source.text){$('taskInput').value=source.text;trackTaskDraft();}
  ui.taskReuseSource={run:source.run,text:source.text};
  $('taskReuseProvenance').textContent=`依頼文の元：チーム ${String(source.run).slice(-8)}（最後に取得した表示用の内容）`;
  $('taskReuseProvenance').hidden=false;$('taskReuseHelp').hidden=false;
  inlineStatus($('taskReuseStatus'),'表示用の依頼文を下書きに入れました。まだ開始していません。');
  setBriefOpen(true);$('taskInput').focus();
}
function beginTaskReuse() {
  const run=getRun();if(ui.startingRun||ui.startOperation||taskReuseIssue(run))return;
  // Preserve the raw display source for freshness checks; only native textarea
  // newline normalization is applied to the candidate, never trimming.
  const source={run:run.id,rawText:run.task,text:taskEditorText(run.task)};
  if($('taskInput').value===''||$('taskInput').value===source.text){adoptTaskReuse(source);return;}
  clearTaskReuse();setBriefOpen(true,false);trackTaskDraft();
  ui.taskReuseCandidate={...source,navigation:ui.navigationGeneration,selection:ui.selectionGeneration,dialog:ui.taskDialogGeneration,
    draft:ui.taskDraftGeneration,workspace:ui.workspaceGeneration,payload:taskReuseDraftKey()};
  // A pending replacement must never preview the candidate as if adopted.
  ++ui.preflightRequest;clearTimeout(ui.preflightTimer);ui.preflightKey='';
  $('preflightStatus').setAttribute('aria-busy','false');$('preflightPending').textContent='';
  inlineStatus($('preflightStatus'),'依頼文を選んだ後に、保存済み設定を確認します。');$('preflightDetails').replaceChildren();
  $('taskReuseConfirm').hidden=false;$('taskReusePreview').textContent=source.text;
  $('taskReuseCandidateSource').textContent=`チーム ${shortRunId(run)} の表示用の依頼文`;
  $('taskReuseHelp').hidden=false;inlineStatus($('taskReuseStatus'),'現在の入力を残しています。置き換えるか選んでください。');
  syncStartControl();$('keepTaskDraft').focus();
}
function replaceTaskDraft() {
  const candidate=ui.taskReuseCandidate;
  if(!candidate)return;
  if(!ownsTaskReuse(candidate)){reconcileTaskReuse();return;}
  adoptTaskReuse(candidate);
}
function keepTaskDraft() {
  if(!ui.taskReuseCandidate)return;
  clearTaskReuse('現在の入力を残しました。');schedulePreflight();$('taskInput').focus();
}
function ownsTaskDialog(action) {
  return $('taskDialog').open&&!$('settingsDialog').open&&action.dialogGeneration===ui.taskDialogGeneration&&
    action.draftGeneration===ui.taskDraftGeneration&&action.navigationGeneration===ui.navigationGeneration&&action.workspaceGeneration===ui.workspaceGeneration;
}
function acceptedStartText(action) { return `作業 ${action.runId} の開始は受け付けられました。実行一覧への表示を確認しています。再送信は不要です。`; }
function showPendingStart() {
  const action=ui.startOperation;if(!action||!$('taskDialog').open)return;
  inlineStatus($('runFormStatus'),(action.runId?acceptedStartText(action):'送信済みの開始要求の応答を待っています。')+(ownsTaskDialog(action)?'':' 現在の下書きは送信していません。'));
}
function reconcileStartedRun() {
  const action=ui.startOperation;
  if(!action?.runId||!ui.state.runs.some(run=>run.id===action.runId))return;
  const owned=ownsTaskDialog(action);
  ui.startOperation=null;ui.startingRun=false;syncStartControl();
  if(owned){inlineStatus($('runFormStatus'),'チームを開始しました。');selectRun(action.runId);}
  else if($('taskDialog').open)inlineStatus($('runFormStatus'),`作業 ${action.runId} を開始しました。実行一覧から確認できます。現在の下書きは送信していません。`);
  actionNotice(action,`作業 ${action.runId} を開始しました。実行一覧から確認できます。`);
}
function canStopRun(run) { return Boolean(run)&&ACTIVE_STATUSES.has(run.status)&&run.status!=='stopping'&&!ui.stoppingRuns.has(run.id); }
function schedulePreflight() {
  if(!$('taskDialog').open||ui.taskReuseCandidate)return;
  const key=JSON.stringify([runPayload(),ui.settingsRevision,ui.settingsDirty]);
  if(key===ui.preflightKey)return;
  ui.preflightKey=key;
  if(!ui.startingRun)inlineStatus($('runFormStatus'),'');
  const request=++ui.preflightRequest;clearTimeout(ui.preflightTimer);
  // A textarea change event also fires on blur. Do not rebuild the preview or
  // move Start between pointer-down and pointer-up for an unchanged payload.
  $('preflightStatus').setAttribute('aria-busy','true');$('preflightPending').textContent='更新中';
  if(!$('preflightStatus').textContent)inlineStatus($('preflightStatus'),'保存済み設定を確認しています…');
  ui.preflightTimer=setTimeout(()=>refreshPreflight(request),180);
}
async function settleStartPointer() {
  // Keep preview layout stable through the native pointer click/default submit.
  // Releasing this wait only renders guidance; it never submits a form.
  while(ui.startPointerActive)await new Promise(resolve=>ui.startPointerWaiters.push(resolve));
}
function releaseStartPointer() {
  if(!ui.startPointerActive)return;
  window.setTimeout(()=>{ui.startPointerActive=false;ui.startPointerWaiters.splice(0).forEach(resolve=>resolve());},0);
}
async function refreshPreflight(request) {
  const revision=ui.settingsRevision;
  const current=()=>request===ui.preflightRequest&&revision===ui.settingsRevision&&$('taskDialog').open&&!ui.taskReuseCandidate;
  try {
    const response=await api('/api/run-preflight',{method:'POST',body:runPayload()});await settleStartPointer();if(!current())return;
    const parts=[];
    parts.push(ui.settingsDirty?'未保存の変更は含みません。開始には保存済み設定を使います。':'保存済み設定の確認です。外部通信・推論テストは行っていません。');
    for(const issue of [...(response.blockers||[]),...(response.warnings||[])])parts.push(issue.message);
    inlineStatus($('preflightStatus'),(response.can_start?'開始に必要な設定を確認しました。推論・ツール動作は未確認です。':'開始前に修正が必要です。')+' '+parts.join(' '),!response.can_start);
    const target=$('preflightDetails'),scopeOpen=Boolean(target.querySelector('.readiness-scope')?.open);target.replaceChildren();
    if(response.destinations){
      target.append(element('p','small','送信される可能性のある接続先（実際の呼び出し記録ではありません）'));
      for(const p of response.destinations)target.append(element('p','readiness-destination',`${p.role} · ${p.label} · ${p.model} — ${p.endpoint}${p.proxy?' · proxy: '+p.proxy:''}`));
      const scope=response.scope||{};
      const details=element('details','readiness-scope');details.open=scopeOpen;details.append(element('summary','','許可・拒否するフォルダーを確認'));
      for(const [key,label] of [['read_roots','読み取り'],['write_roots','書き込み'],['deny_roots','拒否（アプリ・設定保存先の自動保護を含む）']])details.append(element('p','small',`${label}: ${(scope[key]||[]).join(' / ')||'なし'}`));
      details.append(element('p','small','拒否が優先されます。読み取りと書き込みは独立した権限です。各ファイルの操作時にも確認します。'));target.append(details);
      const web=response.web||{};
      target.append(element('p','small',`Web 検索: ${web.search_configured?'設定あり（未接続確認）':'使用不可'} · 公開ページ取得: ${web.fetch_enabled?'有効':'無効'}${web.enabled?' · 検索先: '+web.search_endpoint+' · ページ取得先: モデルが選ぶ公開 HTTP(S) サイト'+(web.proxy?' · proxy: '+web.proxy:''):''}`));
      target.append(element('p','small','依頼・会話・作業方針・許可パスと、必要に応じたファイル内容やツール結果は、選択したモデル接続先へ送られます。Web 有効時は検索語・取得 URL も各接続先へ送られます。'));
      target.append(element('p','small','LOCAL APP はアプリの実行場所です。Local はこの PC またはプライベート LAN の API に接続し、別の PC の場合もあります。チーム内の連絡で内容が別のモデル接続先へ共有される場合があります。PM・作業者すべての接続先・プロキシと、保存・再転送・学習利用の条件が社内の承認範囲に収まるか確認してください。アプリは会社の承認状況や接続先でのデータの取り扱いを判定しません。'));
    }
  }catch(error){await settleStartPointer();if(current())inlineStatus($('preflightStatus'),errorText(error)+' 開始時にも設定を再確認します。',true);}
  finally{if(current()){$('preflightStatus').setAttribute('aria-busy','false');$('preflightPending').textContent='';}}
}
function setBriefOpen(open,preview=true) {
  if(open) { if(!$('taskDialog').open){ui.taskDialogGeneration++;$('taskDialog').showModal();}showPendingStart();syncStartControl();if(preview)schedulePreflight(); }
  else if($('taskDialog').open)$('taskDialog').close();
}
function needsHuman(agent) { return agent.status_reason==='human_input'||(Boolean(agent.question)&&['waiting','waiting_human','needs_input'].includes(agent.status)); }
function filteredAgents(agents) {
  const query=$('agentSearch').value.trim().toLocaleLowerCase();
  return agents.filter(agent=>(!ui.needsOnly||needsHuman(agent))&&(!query||[agent.name,agent.id,agent.assignment,agent.profile_id].join(' ').toLocaleLowerCase().includes(query)));
}
function questionEntries() {
  // Current runtime pauses, not unread messages or an inferred priority queue.
  const agents=new Map(ui.state.agents.map(agent=>[agent.id,agent]));
  return [...ui.state.runs].sort((a,b)=>(Number(a.created_at)||0)-(Number(b.created_at)||0)).flatMap(run=>{
    if(['stopping','stopped'].includes(run.status))return [];
    const members=Array.isArray(run.agent_ids)?run.agent_ids.map(id=>agents.get(id)):ui.state.agents.filter(agent=>agent.run_id===run.id);
    return members.filter(agent=>agent&&agent.run_id===run.id&&agent.status==='waiting'&&
      typeof agent.question==='string'&&agent.question.trim()&&agent.status_reason==='human_input')
      .map(agent=>({run,agent}));
  });
}
function questionAvailability(agent) {
  const eligibility=agent.message_eligibility;
  if(eligibility?.allowed===true)return {label:'回答可能',message:eligibility.message||''};
  if(eligibility?.allowed===false)return {label:'回答不可',message:eligibility.message||'現在は送信できません。作業ログで状態を確認してください。'};
  return {label:'送信可否未確認',message:'作業ログで最新の状態を確認してください。'};
}
function shortRunId(run) { return String(run.id).slice(-8); }
function questionMatches(entry) {
  const query=$('agentSearch').value.trim().toLocaleLowerCase(),{run,agent}=entry;
  return !query||[run.task,run.id,agent.name,agent.id,agent.assignment,agent.profile_id,agent.question].join(' ').toLocaleLowerCase().includes(query);
}
function renderQuestionSummary(entries) {
  const count=entries.length,allowed=entries.filter(({agent})=>agent.message_eligibility?.allowed===true).length,
    blocked=entries.filter(({agent})=>agent.message_eligibility?.allowed===false).length,unknown=count-allowed-blocked;
  $('questionCount').textContent=String(count);
  const status=`全チームの質問 ${count}件。回答可能 ${allowed}件、回答不可 ${blocked}件${unknown?`、送信可否未確認 ${unknown}件`:''}。`;
  if($('questionQueueStatus').textContent!==status)$('questionQueueStatus').textContent=status;
}
function toggleQuestionView() {
  if(ui.needsOnly)ui.questionSearch=$('agentSearch').value;else ui.crewSearch=$('agentSearch').value;
  ui.needsOnly=!ui.needsOnly;$('needsYou').setAttribute('aria-pressed',String(ui.needsOnly));
  $('agentSearch').value=ui.needsOnly?ui.questionSearch:ui.crewSearch;renderRun();
}
function openQuestion(id) {
  const entry=questionEntries().find(item=>item.agent.id===id);
  if(!entry){renderState();return;}
  ui.navigationGeneration++;
  const changed=changeSelection(entry.run.id,id);
  renderState();
  // This explicit navigation has current summary text immediately. Polling never
  // performs this focus move, including when a late detail response arrives.
  $('humanQuestion').focus();
  if(changed)void pollState();
}
function questionFocusFallback() {
  const cards=[...$('agentCards').querySelectorAll('[data-focus-key]')],index=cards.indexOf(document.activeElement);
  if(index<0||!cards[index].dataset.focusKey.startsWith('question:'))return null;
  const keys=[...cards.slice(index+1),...cards.slice(0,index).reverse()].map(card=>card.dataset.focusKey);
  return ()=>{
    const current=[...$('agentCards').querySelectorAll('[data-focus-key]')];
    const target=keys.map(key=>current.find(card=>card.dataset.focusKey===key)).find(Boolean)||current[0]||$('needsYou');
    target.scrollIntoView({block:'nearest',inline:'nearest'});return target;
  };
}
function renderQuestions(entries) {
  const filtered=entries.filter(questionMatches),signature=JSON.stringify(['questions',ui.selectedRun,ui.selectedAgent,$('agentSearch').value,entries.length,
    filtered.map(({run,agent})=>[run.id,run.task,run.created_at,agent.id,agent.name,agent.parent_id,agent.profile_id,agent.configured_profile,agent.question,agent.message_eligibility])]);
  if(signature===ui.rosterSignature)return;ui.rosterSignature=signature;
  const fallback=questionFocusFallback(),focusedKey=document.activeElement?.dataset.focusKey;
  preserveControlFocus(()=>{
    $('agentCount').textContent=`${filtered.length} / ${entries.length}`;$('agentCards').replaceChildren();
    $('rosterEmpty').hidden=filtered.length>0;$('rosterEmpty').textContent=entries.length?'検索条件に一致する質問はありません。':'現在、人への質問で待っているエージェントはいません。';
    for(const {run,agent} of filtered){
      const card=element('button','agent-card question-card'+(agent.id===ui.selectedAgent&&run.id===ui.selectedRun?' selected':''));
      card.type='button';card.dataset.agentId=agent.id;card.dataset.focusKey=`question:${agent.id}`;
      card.setAttribute('aria-pressed',String(agent.id===ui.selectedAgent&&run.id===ui.selectedRun));
      const availability=questionAvailability(agent),profile=configuredProfile(agent);
      const source=element('span','question-run');
      source.append(element('span','question-run-id',`チーム ${shortRunId(run)}`),element('span','question-run-title',String(run.task||'作業').split('\n')[0]));
      card.append(source,
        element('span','agent-name',`${!agent.parent_id?'PM':'作業者'} · ${agent.name||agent.id}`),
        element('span','question-preview',agent.question.length>180?agent.question.slice(0,180)+'…':agent.question),
        element('span','question-availability',availability.label+(availability.message?' · '+availability.message:'')));
      const model=element('span','agent-model',profile?profileLabel(profile):'開始時の設定情報なし');
      model.title=configuredProfileLabel(agent)+'（応答モデル未確認）';card.append(model,element('span','question-open','質問と作業ログを開く'));
      card.addEventListener('click',()=>openQuestion(agent.id));$('agentCards').appendChild(card);
    }
  },fallback);
  if(focusedKey?.startsWith('question:')&&document.activeElement?.dataset.focusKey===focusedKey)
    document.activeElement.scrollIntoView({block:'nearest',inline:'nearest'});
}
function renderTeamMap(agents) {
  const signature=JSON.stringify([ui.selectedAgent,agents.map(agent=>[agent.id,agent.parent_id,agent.name,agent.role])]);if(signature===ui.mapSignature)return;ui.mapSignature=signature;
  const map=$('teamMap');map.replaceChildren();$('teamMapMeta').textContent=`${agents.length} AGENTS`;
  if(!agents.length){map.appendChild(element('p','empty-small','チームの親子関係を表示します'));return;}
  const ids=new Set(agents.map(agent=>agent.id));
  const roots=agents.filter(agent=>!agent.parent_id||!ids.has(agent.parent_id));
  const visited=new Set();
  function node(agent,root=false) {
    const group=element('div','map-branch'),button=element('button',root?'map-root':'map-node');button.type='button';button.dataset.focusKey=`map:${agent.id}`;button.setAttribute('aria-label',`${agent.name||agent.id} の作業ログ`);button.setAttribute('aria-pressed',String(agent.id===ui.selectedAgent));
    button.append(element('span','map-medallion',!agent.parent_id?'PM':'W'),element('span','map-label',agent.name||agent.id));button.addEventListener('click',()=>selectAgent(agent.id));group.appendChild(button);visited.add(agent.id);
    const children=agents.filter(child=>child.parent_id===agent.id&&!visited.has(child.id));
    if(children.length){const row=element('div','map-children');children.forEach(child=>row.appendChild(node(child)));group.appendChild(row);}return group;
  }
  roots.forEach(agent=>map.appendChild(node(agent,true)));
  agents.forEach(agent=>{if(!visited.has(agent.id))map.appendChild(node(agent,true));});
}
function renderAgentTabs(agents) {
  const signature=JSON.stringify([ui.selectedAgent,agents.map(agent=>[agent.id,agent.name,agent.role,agent.parent_id])]);if(signature===ui.tabsSignature)return;ui.tabsSignature=signature;
  const tabs=$('agentTabs');tabs.replaceChildren();
  agents.forEach(agent=>{const button=element('button','agent-tab'+(agent.id===ui.selectedAgent?' active':''),`${!agent.parent_id?'◉':'○'} ${agent.name||agent.id}`);button.type='button';button.dataset.focusKey=`tab:${agent.id}`;button.setAttribute('aria-pressed',String(agent.id===ui.selectedAgent));button.addEventListener('click',()=>selectAgent(agent.id));tabs.appendChild(button);});
}
function saveAgentDraft(event) {
  if(!ui.selectedAgent)return;
  const value=$('messageInput').value;
  if(event?.type==='input'||ui.drafts.get(ui.selectedAgent)!==value)ui.draftRevisions.set(ui.selectedAgent,(ui.draftRevisions.get(ui.selectedAgent)||0)+1);
  ui.drafts.set(ui.selectedAgent,value);
}
function rememberConversationView() {
  if(!ui.logContext)return;
  const container=$('conversationLog');
  ui.conversationViews.set(ui.logContext,{scroll:container.scrollTop,atBottom:container.scrollHeight-container.scrollTop-container.clientHeight<70,expanded:new Set([...container.querySelectorAll('details[open]')].map(node=>node.dataset.logId))});
}
function changeSelection(runId,id) {
  if(ui.selectedRun===runId&&ui.selectedAgent===id)return false;
  saveAgentDraft();rememberConversationView();ui.selectedRun=runId;ui.selectedAgent=id;
  // An epoch, rather than an ID comparison, also rejects an old A response after A → B → A.
  ui.selectionGeneration++;ui.loadedDetail=null;ui.detailError=false;ui.logContext='';ui.logSignature='';ui.outputRequest++;
  if(ui.polling)ui.pollAgain=true;
  $('messageInput').value=ui.drafts.get(id)||'';inlineStatus($('messageStatus'),'');inlineStatus($('resultActionStatus'),'');
  return true;
}
function selectAgent(id) { if(!ui.state.agents.some(agent=>agent.id===id&&agent.run_id===ui.selectedRun))return;ui.navigationGeneration++;const changed=changeSelection(ui.selectedRun,id);renderRun();if(changed)void pollState(); }
function selectRun(id) { if(!ui.state.runs.some(run=>run.id===id))return;ui.navigationGeneration++;const agents=ui.state.agents.filter(agent=>agent.run_id===id),changed=changeSelection(id,agents.find(agent=>!agent.parent_id)?.id||agents[0]?.id||null);inlineStatus($('messageStatus'),'');showView('work');setBriefOpen(false);renderState();if(changed)void pollState(); }

function renderRunList() {
  const counts=new Map();for(const {run} of questionEntries())counts.set(run.id,(counts.get(run.id)||0)+1);
  const signature=JSON.stringify([ui.selectedRun,ui.state.runs.map(run=>[run.id,run.task,run.status,run.status_reason,run.created_at,counts.get(run.id)||0])]);if(signature===ui.runsSignature)return;ui.runsSignature=signature;
  $('runCount').textContent=`${ui.state.runs.length} / 20`;$('runList').replaceChildren();
  if(!ui.state.runs.length){$('runList').appendChild(element('p','sidebar-empty','ここにチームの作業が並びます'));return;}
  [...ui.state.runs].reverse().forEach(run=>{const button=element('button','run-link'+(run.id===ui.selectedRun?' selected':''));button.type='button';button.dataset.focusKey=`run:${run.id}`;button.append(element('span','run-link-title',String(run.task||'作業').split('\n')[0]),element('span','run-link-meta',`${stateLabel(run)} · ${localTime(run.created_at)} · ${shortRunId(run)}${counts.get(run.id)?` · 質問 ${counts.get(run.id)}件`:''}`));button.addEventListener('click',()=>selectRun(run.id));$('runList').appendChild(button);});
}
const REASON_LABELS = {human_input:'回答待ち',teammates:'作業者待ち',teammate_error:'作業者エラー',collaboration_limit:'連携上限',needs_attention:'要確認',error:'エラー'};
function stateLabel(item) { return REASON_LABELS[item?.status_reason]||statusLabel(item?.status); }
function badge(status,reason) { return element('span','status-badge '+(Object.hasOwn(STATUS_LABELS,status)?status:''),REASON_LABELS[reason]||statusLabel(status)); }
function renderAgents(agents) {
  const signature=JSON.stringify([ui.selectedAgent,ui.needsOnly,$('agentSearch').value,agents.map(agent=>[agent.id,agent.parent_id,agent.name,agent.profile_id,agent.configured_profile,agent.status,agent.status_reason,agent.assignment,agent.question,agent.last_error])]);if(signature===ui.rosterSignature)return;ui.rosterSignature=signature;
  $('agentCount').textContent=String(agents.length);$('agentCards').replaceChildren();$('rosterEmpty').hidden=filteredAgents(agents).length>0;$('rosterEmpty').textContent=agents.length?'条件に一致するエージェントはいません。':'チームを開始すると、ここに担当者が並びます。';
  filteredAgents(agents).forEach((agent,index)=>{
    const card=element('button','agent-card'+(agent.id===ui.selectedAgent?' selected':''));card.type='button';card.dataset.agentId=agent.id;card.dataset.focusKey=`agent:${agent.id}`;card.setAttribute('aria-pressed',String(agent.id===ui.selectedAgent));
    const top=element('div','agent-card-top');top.append(element('span','agent-avatar',!agent.parent_id?'PM':`W${agents.filter(item=>item.parent_id).findIndex(item=>item.id===agent.id)+1}`),badge(agent.status,agent.status_reason));
    const profile=configuredProfile(agent),model=element('span','agent-model',profile?profileLabel(profile):'開始時の設定情報なし');
    model.title=configuredProfileLabel(agent)+'（応答モデル未確認）';
    card.append(top,element('span','agent-name',agent.name||agent.id),model,element('span','agent-task',agent.assignment||agent.question||agent.last_error||(!agent.parent_id?'チームの作業を管理':'割り当てられた作業を担当')));
    card.addEventListener('click',()=>selectAgent(agent.id));$('agentCards').appendChild(card);
  });
}
function outputRecords(agent) {
  const reports=Array.isArray(agent?.results)?agent.results:[],receipts=Array.isArray(agent?.output_receipts)?agent.output_receipts:[];
  return [...reports.slice().reverse().map(record=>({key:`result:${record.id}`,kind:'result',record})),...receipts.slice().reverse().map(record=>({key:`receipt:${record.id}`,kind:'receipt',record}))];
}
function agentDetailLoaded(agent) {
  return Boolean(agent)&&(!ui.compactState||(ui.loadedDetail?.generation===ui.selectionGeneration&&ui.loadedDetail.run===ui.selectedRun&&ui.loadedDetail.agent===agent.id));
}
function outputOwner() { return JSON.stringify([ui.selectedRun,ui.selectedAgent]); }
function selectedOutput() { const agent=getAgent();return agentDetailLoaded(agent)?outputRecords(agent).find(item=>item.key===ui.outputSelections.get(outputOwner()))||null:null; }
function historicalResult(agent,result) {
  return result.revision!==agent.result_revision||result.turn!==agent.turns||['queued','working','running','waiting','waiting_human','needs_input','stopping'].includes(agent.status);
}
function resultSource(result) { return result.source==='finish_work'?'完了報告':'最終応答'; }
function resultSourceTag(result) { return result.source==='finish_work'?'finish_work':'assistant_response'; }
function resultPosition(agent,result) { return historicalResult(agent,result)?'過去の報告':'このターンの報告'; }
function outputTimestamp(value) {
  const date=new Date(typeof value==='number'?(value<1e12?value*1000:value):value);
  return value===undefined||value===null||Number.isNaN(date.getTime())?'時刻なし':date.toISOString();
}
function receiptText(receipt) {
  return [`パス: ${receipt.path??''}`,`保存操作: ${receipt.operation==='updated'?'更新':'新規作成'}`,`ツール: ${receipt.tool??''}`,`保存時のサイズ: ${receipt.bytes??'不明'} bytes`,`保存時の SHA-256: ${receipt.sha256??'不明'}`].join('\n');
}
function exportOutputText(agent,item) {
  const record=item.record,heading=item.kind==='result'?'モデルの報告':'ファイル保存記録',profile=configuredProfile(agent);
  const meta=[heading,`作業 ID: ${agent.run_id??'不明'}`,`担当: ${JSON.stringify(agent.name||agent.id||'不明')}`,
    `エージェント ID: ${agent.id??'不明'}`,`プロファイル ID: ${agent.profile_id??'不明'}`];
  if(profile)meta.push(`開始時の表示名: ${JSON.stringify(profile.label)}`,`開始時の接続方式: ${PROFILE_KINDS[profile.kind]}`,
    `開始時のモデル設定: ${JSON.stringify(profile.model)}`);
  else meta.push('開始時の設定情報なし');
  meta.push('モデル名は開始時の設定値です。接続先が実際に使ったモデルの確認ではありません。',
    `時刻: ${outputTimestamp(record.at)}`,`ターン: ${record.turn??'不明'}`);
  if(item.kind==='result')meta.push(`出典: ${resultSource(record)}（${resultSourceTag(record)}）`,`状態: ${resultPosition(agent,record)}`,`本文の省略: ${record.truncated?'あり（保持された範囲のみ）':'なし'}`,'モデルによる報告です。内容の正しさや作業の完了を検証したものではありません。');
  else meta.push('保存時点の記録です。現在のファイルの存在・内容は未確認です。ファイル本体は含みません。');
  return meta.join('\n')+'\n\n'+(item.kind==='result'?String(record.text??''):receiptText(record))+'\n';
}
function syncOutputContext(item) {
  const context=JSON.stringify([ui.selectedRun,ui.selectedAgent,ui.selectionGeneration,item?.key??null]);
  if(context!==ui.outputContext){ui.outputContext=context;ui.outputRequest++;inlineStatus($('resultActionStatus'),'');}
}
function renderResults(agent) {
  if(agent&&!agentDetailLoaded(agent)) {
    syncOutputContext(null);$('resultsPanel').hidden=false;
    const signature=JSON.stringify([outputOwner(),ui.selectionGeneration,'loading']);if(signature===ui.outputSignature)return;ui.outputSignature=signature;
    $('resultsCount').textContent='読み込み中';const option=element('option','','成果・保存記録を読み込み中…');option.value='';$('resultSelection').replaceChildren(option);$('resultSelection').disabled=true;
    $('copyResult').disabled=true;$('exportResult').disabled=true;$('resultMeta').textContent='';$('resultText').textContent='';$('resultText').hidden=true;$('resultsOmitted').textContent='';$('resultsOmitted').hidden=true;
    $('resultNotice').textContent='選択したエージェントの成果・保存記録を取得しています。';return;
  }
  const records=outputRecords(agent),owner=outputOwner();
  if(!records.some(item=>item.key===ui.outputSelections.get(owner)))ui.outputSelections.set(owner,records[0]?.key??null);
  const selected=records.find(item=>item.key===ui.outputSelections.get(owner))||null;
  const previousContext=ui.outputContext;syncOutputContext(selected);
  $('resultsPanel').hidden=!agent;
  const signature=JSON.stringify([owner,selected?.key,agent?.result_revision,agent?.turns,agent?.status,records,agent?.results_omitted,agent?.receipts_omitted]);
  if(signature===ui.outputSignature)return;ui.outputSignature=signature;
  const results=records.filter(item=>item.kind==='result'),receipts=records.filter(item=>item.kind==='receipt');
  $('resultsCount').textContent=`報告 ${results.length} · 保存 ${receipts.length}`;
  const select=$('resultSelection'),scroll=previousContext===ui.outputContext?$('resultText').scrollTop:0,panelScroll=$('resultsPanel').scrollTop;
  select.replaceChildren();
  for(const [label,items] of [['モデルの報告（新しい順）',results],['ファイル保存記録（新しい順）',receipts]]) {
    if(!items.length)continue;
    const group=element('optgroup');group.label=label;
    for(const item of items){const record=item.record,title=item.kind==='result'?`${resultPosition(agent,record)} · ${resultSource(record)}${record.truncated?' · 本文省略あり':''}`:`保存時の記録 · ${record.path??''}`;const option=element('option','',`${title} · turn ${record.turn??'?'}${localTime(record.at)?' · '+localTime(record.at):''}`);option.value=item.key;group.appendChild(option);}
    select.appendChild(group);
  }
  if(!selected){const option=element('option','','まだ報告・保存記録はありません');option.value='';select.appendChild(option);}
  select.value=selected?.key??'';select.disabled=!selected;$('copyResult').disabled=!selected;$('exportResult').disabled=!selected;
  $('copyResult').textContent=selected?.kind==='receipt'?'パスをコピー':'本文をコピー';
  $('exportResult').textContent=selected?.kind==='receipt'?'記録を .txt 保存':'報告を .txt 保存';
  const omissions=[];
  if(Number(agent?.results_omitted)>0)omissions.push(`古い報告 ${agent.results_omitted} 件`);
  if(Number(agent?.receipts_omitted)>0)omissions.push(`古い保存記録 ${agent.receipts_omitted} 件`);
  $('resultsOmitted').textContent=omissions.length?`保持上限により省略: ${omissions.join('、')}`:'';$('resultsOmitted').hidden=!omissions.length;
  const record=selected?.record;
  $('resultMeta').textContent=!selected?'':selected.kind==='result'?`${resultPosition(agent,record)} · ${resultSource(record)}（${resultSourceTag(record)}） · turn ${record.turn??'?'} · ${outputTimestamp(record.at)}${record.truncated?' · 本文省略あり（保持された範囲のみ）':''}`:`保存時の記録 · turn ${record.turn??'?'} · ${outputTimestamp(record.at)}`;
  $('resultNotice').textContent=!selected?'報告や対応ツールによる保存記録が届くと、ここで確認できます。':selected.kind==='result'?'モデルによる報告です。内容の正しさや作業の完了を検証したものではありません。':'保存時点の記録です。現在のファイルの存在・内容は未確認です。ファイル本体のダウンロードはできません。';
  $('resultText').textContent=!selected?'':selected.kind==='result'?String(record.text??''):receiptText(record);
  $('resultText').hidden=!selected;
  $('resultText').scrollTop=scroll;$('resultsPanel').scrollTop=panelScroll;
}
function beginOutputAction(item) {
  return {run:ui.selectedRun,agent:ui.selectedAgent,generation:ui.selectionGeneration,key:item.key,request:++ui.outputRequest};
}
function outputActionCurrent(action) {
  return action.request===ui.outputRequest&&action.generation===ui.selectionGeneration&&action.run===ui.selectedRun&&action.agent===ui.selectedAgent&&action.key===selectedOutput()?.key;
}
function outputFeedback(action,text,error=false) { if(outputActionCurrent(action))inlineStatus($('resultActionStatus'),text,error); }
async function copySelectedOutput() {
  const item=selectedOutput();if(!item)return;const action=beginOutputAction(item),path=item.kind==='receipt';
  outputFeedback(action,'コピーしています…');
  try {
    if(!navigator.clipboard?.writeText)throw new Error('Clipboard API unavailable');
    await navigator.clipboard.writeText(String(path?item.record.path??'':item.record.text??''));
    outputFeedback(action,path?'パスをコピーしました。':'本文をコピーしました。');
  }catch(_){outputFeedback(action,'コピーできませんでした。表示されたテキストを選択してコピーするか、.txt 保存を使ってください。',true);}
}
function downloadPlainText(text,filename) {
  const blob=new Blob([text],{type:'text/plain;charset=utf-8'}),url=URL.createObjectURL(blob);let link;
  try {link=element('a');link.href=url;link.download=filename;link.hidden=true;document.body.appendChild(link);link.click();}
  finally {link?.remove();window.setTimeout(()=>URL.revokeObjectURL(url),1000);}
}
function exportSelectedOutput() {
  const item=selectedOutput(),agent=getAgent();if(!item||!agent)return;const action=beginOutputAction(item);
  try {downloadPlainText(exportOutputText(agent,item),item.kind==='receipt'?'workbench-save-receipt.txt':'workbench-result.txt');outputFeedback(action,'選択した記録の .txt ダウンロードを開始しました（UTF-8）。');}
  catch(_){outputFeedback(action,'.txt ダウンロードを開始できませんでした。表示されたテキストを選択してコピーしてください。',true);}
}
function renderConversation(agent) {
  renderResults(agent);
  const available=Boolean(agent),run=getRun();$('messageForm').hidden=!available;
  const loaded=agentDetailLoaded(agent),loading=available&&!loaded,detailStatus=$('detailStatus');
  detailStatus.hidden=!loading;
  const detailMessage=loading?(ui.detailError?'詳細を取得できませんでした。接続を確認しながら再試行しています。':'選択したエージェントのログと成果を読み込み中…'):'';
  if(detailStatus.textContent!==detailMessage)detailStatus.textContent=detailMessage;
  $('conversationLog').setAttribute('aria-busy',String(loading));$('resultsPanel').setAttribute('aria-busy',String(loading));
  $('conversationTitle').textContent=agent?(agent.name||agent.id):'作業ログ';
  $('conversationMeta').textContent=agent?`${!agent.parent_id?'PM':'作業者'} · ${agent.profile_id} · ${agent.turns||0} turns`:'';
  $('conversationProfile').textContent=agent?configuredProfileLabel(agent)+'（応答モデル未確認）':'';
  $('conversationStatus').hidden=!agent;
  if(agent){$('conversationStatus').className='status-badge '+(Object.hasOwn(STATUS_LABELS,agent.status)?agent.status:'');$('conversationStatus').textContent=stateLabel(agent);}
  const question=agent&&needsHuman(agent)?agent.question||'':'';
  const questionLostFocus=!question&&document.activeElement===$('humanQuestion');
  const questionContext=JSON.stringify([ui.selectedRun,agent?.id,question]);
  $('humanQuestion').hidden=!question;
  if(ui.questionContext!==questionContext){ui.questionContext=questionContext;$('humanQuestion').textContent=question?`判断が必要です\n${question}`:'';$('humanQuestion').scrollTop=0;}
  if(questionLostFocus)$('conversationHeading').focus({preventScroll:true});
  $('messageLabel').textContent=question?'質問への回答':'追加の指示';$('messageInput').placeholder=question?'選択肢や条件を確認し、回答を入力してください':'このエージェントへ追加の指示を送る';
  const stopping=['stopping','stopped'].includes(run?.status),eligibility=agent?.message_eligibility;
  const blocked=stopping||eligibility?.allowed!==true;
  $('sendMessage').disabled=!agent||ui.busyMessage||blocked;$('messageInput').disabled=!agent||blocked;
  $('messageEligibility').textContent=eligibility?.message||(stopping?'停止したチームは再開できません。新しい仕事を開始してください':agent&&eligibility?.allowed!==true?'送信できる状態か確認できません。最新の状態を取得してから確認してください。':'');
  $('messageEligibility').hidden=!$('messageEligibility').textContent;
  const logs=loaded&&Array.isArray(agent?.logs)?agent.logs:[],signature=JSON.stringify([ui.selectedRun,agent?.id,loading,logs]);
  if(signature===ui.logSignature)return;ui.logSignature=signature;
  rememberConversationView();
  const container=$('conversationLog'),context=outputOwner(),view=ui.conversationViews.get(context),atBottom=view?.atBottom??true,expanded=view?.expanded||new Set();
  const fallback=evictedLogFocusFallback(container,context,logs,loaded);
  const readingDisclosure=loaded&&ui.logContext===context&&[...container.querySelectorAll('details.thinking > summary')].includes(document.activeElement);
  const idCounts=new Map();for(const log of logs){const id=logRecordId(log);if(id!==null)idCounts.set(id,(idCounts.get(id)||0)+1);}
  preserveControlFocus(()=>{
  container.replaceChildren();
  ui.logContext=loaded?context:'';
  if(loading){container.appendChild(element('div','detail-loading','作業ログを読み込み中…'));return;}
  if(!logs.length){container.appendChild(element('div','empty-small',agent?'まだログはありません。作業が進むとここに表示されます。':'エージェントを選ぶと、作業の経過が表示されます。'));return;}
  logs.forEach((log,index)=>{
    const id=String(log.id??index),kind=String(log.kind||'assistant');
    if(log.thinking||kind==='thinking') {const detail=element('details','thinking'),summary=element('summary','',`モデルが返した思考の詳細${localTime(log.at)?' · '+localTime(log.at):''}`);detail.dataset.logId=id;detail.open=expanded.has(id);const stableId=logRecordId(log);if(stableId!==null&&idCounts.get(stableId)===1)summary.dataset.focusKey=`log:${JSON.stringify([ui.selectedRun,agent.id,stableId])}`;detail.append(summary,element('pre','log-text',log.thinking||log.text||''));container.appendChild(detail);}
    if(kind==='thinking'||!log.text)return;
    const entry=element('article','log-entry '+(['user','tool'].includes(kind)?kind:'')),meta=element('div','log-meta');
    meta.append(element('span','log-role',({user:'あなた',assistant:agent.name||'エージェント',tool:'ツール',system:'システム',error:'エラー'})[kind]||kind),element('span','',localTime(log.at)));
    entry.append(meta,element('pre','log-text',log.text));container.appendChild(entry);
  });
  container.scrollTop=atBottom&&!readingDisclosure?container.scrollHeight:(view?.scroll||0);
  },fallback);
}
function logRecordId(log) {
  return typeof log.id==='string'&&log.id?log.id:Number.isSafeInteger(log.id)?String(log.id):null;
}
function evictedLogFocusFallback(container,context,logs,loaded) {
  // Only a focused disclosure that actually left this owner's retained history
  // needs a fallback. Loading/selection changes must never move the user's focus.
  if(!loaded||ui.logContext!==context)return null;
  const summaries=[...container.querySelectorAll('details.thinking > summary')],index=summaries.indexOf(document.activeElement);
  if(index<0||!summaries[index].dataset.focusKey)return null;
  const id=summaries[index].parentElement.dataset.logId;
  if(logs.some(log=>logRecordId(log)===id))return null;
  const generation=ui.selectionGeneration,nearby=[...summaries.slice(index+1),...summaries.slice(0,index).reverse()].map(node=>node.dataset.focusKey).filter(Boolean);
  return ()=>{
    if(generation!==ui.selectionGeneration||ui.logContext!==context||outputOwner()!==context)return null;
    const available=[...container.querySelectorAll('details.thinking > summary')];
    const target=nearby.map(key=>available.find(node=>node.dataset.focusKey===key)).find(Boolean)||available[0]||$('conversationHeading');
    // A removed reading target cannot retain its old visual position. Reveal
    // only its fallback; retained summaries never use this scroll adjustment.
    if(target===$('conversationHeading'))target.scrollIntoView({block:'nearest',inline:'nearest'});
    else {
      const box=target.getBoundingClientRect(),paneTop=container.getBoundingClientRect().top+container.clientTop;
      const top=Math.max(0,paneTop),bottom=Math.min(window.innerHeight,paneTop+container.clientHeight);
      if(bottom>top&&box.top<top)container.scrollTop+=box.top-top;
      else if(bottom>top&&box.bottom>bottom)container.scrollTop+=box.bottom-bottom;
      const revealed=target.getBoundingClientRect();
      if(bottom<=top||revealed.top<0||revealed.bottom>window.innerHeight)target.scrollIntoView({block:'nearest',inline:'nearest'});
    }
    return target;
  };
}
function renderActivity(run) {
  const feed=$('activityFeed'),loading=Boolean(run)&&ui.compactState&&ui.loadedEventsRun!==run.id,events=!run||loading?[]:ui.state.events.filter(event=>event.run_id===run.id).slice(-100).reverse();
  const signature=JSON.stringify([run?.id,loading,events]);if(signature===ui.activitySignature)return;ui.activitySignature=signature;
  const scroll=ui.activityRun===run?.id?feed.scrollTop:0;ui.activityRun=run?.id;feed.replaceChildren();feed.setAttribute('aria-busy',String(loading));
  if(loading){feed.appendChild(element('p','detail-loading','チームのメールと進捗を読み込み中…'));return;}
  if(!events.length){feed.appendChild(element('p','empty-small','エージェント同士の連絡や作業の進捗がここに表示されます。'));return;}
  events.forEach(event=>{const row=element('article','activity-item'),content=element('div');let title;
    if(event.kind==='mail')title=`${event.from||'エージェント'} → ${Array.isArray(event.to)?event.to.join(', '):event.to||'チーム'}`;
    else title=({spawn:'作業者が参加',question:'人への質問',error:'エラー',done:'作業完了',stopped:'作業を停止',tool:'ツール実行',collaboration_limit:'自動連携が上限に到達'})[event.kind]||event.kind||'進捗';
    content.append(element('div','activity-title',title),element('div','activity-body',event.text||''));row.append(element('time','activity-time',localTime(event.at)),content);feed.appendChild(row);
  });
  feed.scrollTop=scroll;
}
function preserveControlFocus(render,fallback=null) {
  const key=document.activeElement?.dataset.focusKey;
  render();
  if(key&&document.activeElement===document.body) {
    const replacement=[...document.querySelectorAll('[data-focus-key]')].find(node=>node.dataset.focusKey===key);
    (replacement||fallback?.())?.focus({preventScroll:true});
  }
}
function renderRun() { preserveControlFocus(renderRunContent); }
function renderRunContent() {
  reconcileTaskReuse();syncTaskReuseControl();
  const run=getRun();$('workEmpty').hidden=Boolean(run);$('runOverview').hidden=!run;document.querySelector('.conversation-panel').hidden=!run;
  const agents=ui.state.agents.filter(agent=>agent.run_id===run?.id),questions=questionEntries();renderQuestionSummary(questions);
  $('rosterHeading').textContent=ui.needsOnly?'質問':'CREW';
  $('rosterScope').textContent=ui.needsOnly?'全チーム · チームの開始順。開くだけでは回答・再開しません。':run?`表示中のチーム · ${shortRunId(run)}`:'選択したチームの担当者';
  $('agentSearchLabel').textContent=ui.needsOnly?'全チームの質問・依頼・担当者を検索':'エージェントを検索';
  $('agentSearch').placeholder=ui.needsOnly?'質問・チームの依頼・担当者で検索':'エージェント・担当で検索';
  $('agentCards').classList.toggle('question-list',Boolean(ui.needsOnly));
  if(ui.needsOnly)renderQuestions(questions);else renderAgents(agents);
  if(!run){renderTeamMap(agents);renderAgentTabs(agents);renderConversation(null);renderActivity(null);return;}
  $('activeRunTitle').textContent=`表示中のチーム · ${shortRunId(run)}`;$('activeRunStatus').className='status-badge '+(Object.hasOwn(STATUS_LABELS,run.status)?run.status:'');$('activeRunStatus').textContent=stateLabel(run);$('activeRunTask').textContent=run.task||'';
  const collaborationBlocked=run.collaboration_limit_reached===true;
  $('collaborationLimitNotice').hidden=!collaborationBlocked;
  $('collaborationLimitNotice').textContent=collaborationBlocked?'自動連携が上限に達したため、新しい委任・メール・完了通知を停止しました。この連携上限だけでは、開始済み・待機中の作業は停止しません。停止したチームは再開できません。上限を変更して続ける場合は、作業の停止後に設定を保存し、新しい作業を開始してください。追加の指示や回答では回数はリセットされません。':'';
  $('stopRun').disabled=!canStopRun(run);
  const metricValues=[['自動連携',`${run.auto_collaborations??0} / ${run.max_auto_collaborations??24}`],['モデル呼び出し',run.model_calls||0],['ツール実行',run.tool_calls||0],['作業者の上限',run.max_workers||0]],metricSignature=JSON.stringify([run.id,metricValues]);
  if(metricSignature!==ui.metricSignature){ui.metricSignature=metricSignature;const metrics=$('runMetrics');metrics.replaceChildren();for(const [label,value] of metricValues){const metric=element('span','metric',label);metric.appendChild(element('b','',value));metrics.appendChild(metric);}}
  renderTeamMap(agents);renderAgentTabs(agents);renderConversation(getAgent());renderActivity(run);
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
  // Reconcile before automatic initial selection can change the navigation epoch.
  reconcileStartedRun();
  const runId=ui.state.runs.some(run=>run.id===ui.selectedRun)?ui.selectedRun:ui.state.runs.at(-1)?.id||null,agents=ui.state.agents.filter(agent=>agent.run_id===runId);
  const agentId=agents.some(agent=>agent.id===ui.selectedAgent)?ui.selectedAgent:agents.find(agent=>!agent.parent_id)?.id||agents[0]?.id||null;
  changeSelection(runId,agentId);
  preserveControlFocus(()=>{renderRunList();renderRun();});setSettingsLock();$('resourceSummary').textContent=resourceLabel(ui.state.resources,ui.config?.local?.gpu_index||0);
}
function selectedStatePath(selection) {
  const query=new URLSearchParams({view:'selected'});
  if(selection.run)query.set('run_id',selection.run);
  if(selection.run&&selection.agent)query.set('agent_id',selection.agent);
  return '/api/state?'+query.toString();
}
function applyState(state,request) {
  const compact=Object.hasOwn(state,'selection'),selection=state.selection;
  // Legacy full-state fixtures remain supported; compact detail must name its exact request owner.
  if(compact&&(!selection||selection.run_id!==request.run||selection.agent_id!==request.agent||selection.detail_loaded!==Boolean(request.agent)))throw new Error('選択した詳細の応答を確認できませんでした。');
  const next={...state,runs:Array.isArray(state.runs)?state.runs:[],agents:Array.isArray(state.agents)?state.agents:[],events:Array.isArray(state.events)?state.events:[],resources:state.resources||{}};
  if(compact&&request.agent&&!next.agents.some(agent=>agent.run_id===request.run&&agent.id===request.agent&&['logs','results','output_receipts'].every(key=>Array.isArray(agent[key]))))throw new Error('選択した詳細の応答を確認できませんでした。');
  ui.state=next;ui.compactState=compact;ui.detailError=false;
  ui.loadedDetail=compact&&selection.detail_loaded?{...request}:null;ui.loadedEventsRun=compact?request.run:null;
}
async function pollState(fresh=false) {
  if(!ui.authenticated)return;
  if(ui.polling){await ui.pollPromise;if(fresh)return pollState();return;}
  ui.polling=true;ui.pollPromise=(async()=>{
    try {
      do {
        ui.pollAgain=false;
        const request={run:ui.selectedRun,agent:ui.selectedAgent,generation:ui.selectionGeneration};
        try {
          const state=await api(selectedStatePath(request));
          if(request.generation!==ui.selectionGeneration){ui.pollAgain=true;continue;}
          applyState(state,request);renderState();setConnection(true,'Workbench 接続中');
        } catch(error) {
          if(request.generation!==ui.selectionGeneration){ui.pollAgain=true;continue;}
          setConnection(false,'接続を確認してください');ui.detailError=true;renderConversation(getAgent());if(!ui.authenticated)notice(errorText(error),true);
        }
        // Initial summary or a removed selection can choose the latest run/root during renderState.
        if(request.generation!==ui.selectionGeneration)ui.pollAgain=true;
      } while(ui.pollAgain&&ui.authenticated);
    } finally {ui.polling=false;}
  })();return ui.pollPromise;
}
async function initialize() {
  $('resultSelection').addEventListener('change',()=>{ui.outputSelections.set(outputOwner(),$('resultSelection').value);renderResults(getAgent());$('resultText').scrollTop=0;});
  $('copyResult').addEventListener('click',copySelectedOutput);$('exportResult').addEventListener('click',exportSelectedOutput);
  $('navWork').addEventListener('click',()=>showView('work'));$('navSettings').addEventListener('click',()=>showView('settings'));
  $('startRun').addEventListener('pointerdown',event=>{if(event.isPrimary)ui.startPointerActive=true;});
  window.addEventListener('pointerup',releaseStartPointer);
  window.addEventListener('pointercancel',releaseStartPointer);
  window.addEventListener('blur',releaseStartPointer);
  $('runForm').addEventListener('input',event=>{trackTaskDraft(event);schedulePreflight();});
  $('runForm').addEventListener('change',event=>{trackTaskDraft(event);schedulePreflight();});
  $('taskDialog').addEventListener('close',()=>{ui.taskDialogGeneration++;clearTaskReuse();releaseStartPointer();ui.preflightKey='';ui.preflightRequest++;clearTimeout(ui.preflightTimer);});
  $('settingsDialog').addEventListener('close',()=>{ui.workspaceGeneration++;clearCredentialInputs();if(ui.settingsSaving)inlineStatus($('settingsStatus'),'設定を送信しました。閉じても保存要求は取り消されません。必要なら応答後に保存済み設定を読み直してください。');for(const control of credentialControls())if(ui.credentialOperations.has(control.id)){control.status.textContent='キーの更新結果は未確認です。保存済み設定を読み直しても、キー設定の有無だけでは今回の更新を確認できません。';if(control.result!==control.status)inlineStatus(control.result,'');}invalidateDiagnostics();schedulePreflight();});
  $('discardSettings').addEventListener('click',discardSettings);
  $('preflightSettings').addEventListener('click',()=>{setBriefOpen(false);showView('settings');});
  $('toggleBrief').addEventListener('click',()=>setBriefOpen(false));
  $('reuseTask').addEventListener('click',beginTaskReuse);
  $('replaceTaskDraft').addEventListener('click',replaceTaskDraft);
  $('keepTaskDraft').addEventListener('click',keepTaskDraft);
  for(const id of ['newRun','launchTask','emptyNewRun'])$(id).addEventListener('click',()=>setBriefOpen(true));
  $('emptySettings').addEventListener('click',()=>showView('settings'));
  $('closeSettings').addEventListener('click',()=>showView('work'));
  $('agentSearch').addEventListener('input',()=>renderRun());
  $('needsYou').addEventListener('click',toggleQuestionView);
  for(const id of ['taskDialog','settingsDialog']) { const dialog=$(id);dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();}); }
  window.addEventListener('popstate',()=>{setBriefOpen(false);showView('work');});
  $('settingsForm').addEventListener('input',event=>{if(event.target.type!=='password')markSettingsDirty();});
  $('settingsForm').addEventListener('change',event=>{if(event.target.type!=='password')markSettingsDirty();});
  $('settingsForm').addEventListener('invalid',event=>{const card=event.target.closest('.profile-editor');if(card&&card.querySelector('.profile-content').hidden)card.querySelector('[data-readonly]').click();},true);
  $('addProfile').addEventListener('click',()=>{const indexes=[...$('profilesEditor').children].map(node=>Number(node.dataset.index));const index=Math.max(-1,...indexes)+1;appendProfile({id:`profile-${index+1}`,label:'新しいプロファイル',kind:'local',base_url:'http://127.0.0.1:11434/v1',model:'',api_key_env:'',proxy_url:'',enabled:true,request_timeout_seconds:180},index,true,false);markSettingsDirty();});
  $('settingsForm').addEventListener('submit',saveSettings);
  $('runForm').addEventListener('submit',async event=>{
    event.preventDefault();const task=$('taskInput').value;if(!task.trim()||ui.startingRun||ui.taskReuseCandidate)return;
    const workerProfiles=[...$('workerProfiles').querySelectorAll('input:checked')].map(input=>input.value);
    if(!workerProfiles.length&&Number($('maxWorkers').value)>0){inlineStatus($('runFormStatus'),'作業者に使ってよいプロファイルを1つ以上選んでください。',true);return;}
    trackTaskDraft();notice('');
    const action={navigationGeneration:ui.navigationGeneration,dialogGeneration:ui.taskDialogGeneration,draftGeneration:ui.taskDraftGeneration,workspaceGeneration:ui.workspaceGeneration,noticeGeneration:ui.noticeGeneration,runId:null};
    ui.startOperation=action;ui.startingRun=true;syncStartControl();inlineStatus($('runFormStatus'),'チームを準備しています…');
    try {
      const response=await api('/api/runs',{method:'POST',body:{task,pm_profile:$('pmProfile').value,worker_profiles:workerProfiles,max_workers:Number($('maxWorkers').value)}});
      const id=response.run?.id||response.id||response.run_id;
      if(typeof id!=='string'||!id){const failure=new Error('開始応答の実行 ID を確認できませんでした。');failure.outcomeUnknown=true;throw failure;}
      action.runId=id;
      // A successful mutation remains accepted even if observing its state fails.
      // Polling may discover it later; it must never repeat the creation request.
      showPendingStart();
      actionNotice(action,acceptedStartText(action));reconcileStartedRun();await pollState(true);
    }catch(error){
      const message=errorText(error)+(error.outcomeUnknown?' 開始したかどうかは未確認です。実行一覧と接続状態を確認してから、再送信が必要か判断してください。':'');
      if($('taskDialog').open)inlineStatus($('runFormStatus'),(ownsTaskDialog(action)?'':'以前に送信した開始要求: ')+message+(ownsTaskDialog(action)?'':' 現在の下書きは送信していません。'),true);
      actionNotice(action,'送信した開始要求: '+message,true);
      if(ui.startOperation===action){ui.startOperation=null;ui.startingRun=false;}
    }finally{syncStartControl();}
  });
  $('stopRun').addEventListener('click',async()=>{
    const run=getRun();if(!canStopRun(run))return;notice('');const action={noticeGeneration:ui.noticeGeneration};
    ui.stoppingRuns.set(run.id,action);renderRun();
    try{await api(`/api/runs/${encodeURIComponent(run.id)}/stop`,{method:'POST',body:{}});await pollState(true);actionNotice(action,`作業 ${run.id} の停止を受け付けました。現在の状態は実行一覧で確認できます。`);}
    catch(error){actionNotice(action,`作業 ${run.id} の停止要求: ${errorText(error)}`,true);}
    finally{if(ui.stoppingRuns.get(run.id)===action)ui.stoppingRuns.delete(run.id);renderRun();}
  });
  $('messageInput').addEventListener('input',saveAgentDraft);
  $('messageForm').addEventListener('submit',async event=>{
    event.preventDefault();const agent=getAgent(),text=$('messageInput').value;
    if(!agent||!text.trim()||ui.busyMessage||agent.message_eligibility?.allowed!==true||['stopping','stopped'].includes(getRun()?.status))return;
    saveAgentDraft();const action={agent:agent.id,run:agent.run_id,selection:ui.selectionGeneration,draft:ui.draftRevisions.get(agent.id)};
    const owns=()=>ui.selectedAgent===action.agent&&ui.selectedRun===action.run&&ui.selectionGeneration===action.selection&&ui.draftRevisions.get(action.agent)===action.draft;
    const unchanged=()=>ui.draftRevisions.get(action.agent)===action.draft&&ui.drafts.get(agent.id)===text;
    ui.busyMessage=true;$('sendMessage').disabled=true;
    try {
      await api(`/api/agents/${encodeURIComponent(agent.id)}/message`,{method:'POST',body:{text}});
      if(unchanged()&&(owns()||ui.selectedAgent!==agent.id)){
        ui.drafts.delete(agent.id);
        if(owns()&&$('messageInput').value===text)$('messageInput').value='';
      }
      if(owns())inlineStatus($('messageStatus'),'送信しました。');await pollState(true);
    }
    catch(error){if(owns())inlineStatus($('messageStatus'),errorText(error)+(error.outcomeUnknown?' 送信結果は未確認です。作業ログを確認してから再送信が必要か判断してください。':''),true);}
    finally{ui.busyMessage=false;renderConversation(getAgent());}
  });
  $('setSearchSecret').addEventListener('click',()=>setCredential(credentialControls().find(control=>control.id==='search')));
  $('searchSecret').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();setCredential(credentialControls().find(control=>control.id==='search'));}});
  try {
    const fragment=new URLSearchParams(location.hash.slice(1)),token=fragment.get('token');
    if(token){history.replaceState(null,'',location.pathname+location.search);await api('/api/bootstrap',{method:'POST',headers:{'X-Workbench-Bootstrap':token},body:{}});}
    const response=await api('/api/config');ui.config=response.config;ui.configRevision=response.config_revision;ui.secretStatus=response.secret_status||{};ui.authenticated=true;renderSettings();renderProfileChoices();await pollState();
  }catch(error){notice(errorText(error),true);setConnection(false,'Workbench 接続待ち');$('startRun').disabled=true;}
  window.setInterval(()=>pollState(),1000);
}
document.addEventListener('DOMContentLoaded',initialize,{once:true});
