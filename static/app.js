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
function invalidateDiagnostics() { ui.settingsRevision++;document.querySelectorAll('[data-probe-result]').forEach(node=>{node.textContent='設定または画面が変わりました。必要ならモデル一覧を再確認してください。';node.classList.remove('error');}); }
function markSettingsDirty() { invalidateDiagnostics();ui.settingsDirty=true;inlineStatus($('settingsStatus'),'未保存の変更があります。'); }
function secretStatusText(configured) { return configured?'キー設定あり。値は画面に取得しません。':'キー未設定。必要ならキーを入力するか、環境変数の参照先を確認してください。'; }
function refreshSecretStatus(status) {
  ui.secretStatus=status||{};
  $('profilesEditor').querySelectorAll('.profile-editor').forEach(card=>{const id=card.querySelector('[data-key="id"]').value.trim();card.querySelector('.secret-status').textContent=secretStatusText(ui.secretStatus[id]);});
  inlineStatus($('searchSecretStatus'),secretStatusText(ui.secretStatus.search));
}

function appendProfile(profile,index,expanded=true) {
  const card=element('section','profile-editor');card.dataset.index=String(index);card._original={...profile};
  const toolbar=element('div','profile-toolbar'),heading=element('div','profile-heading-group');
  const title=element('h3','profile-title',profile.label||profile.id||'新しいプロファイル');
  const enabled=makeField(['enabled','使用する','checkbox'],profile.enabled!==false,`profile-${index}`);enabled.classList.add('choice');
  heading.append(title,enabled);toolbar.appendChild(heading);
  const actions=element('div','profile-actions'),toggle=element('button','button minor',expanded?'閉じる':'編集'),probe=element('button','button minor','モデル一覧を確認'),remove=element('button','button minor remove','削除');
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
  const secretState=element('p','secret-status',secretStatusText(ui.secretStatus[profile.id]));
  secretRow.append(secretField,saveSecret,secretState);content.appendChild(secretRow);
  const result=element('p','inline-status');result.dataset.probeResult='true';result.setAttribute('role','status');card.appendChild(result);
  const kind=card.querySelector('[data-key="kind"]'),proxy=card.querySelector('[data-key="proxy_url"]');
  const updateKind=()=>{proxy.disabled=ui.settingsLocked||kind.value==='local';proxy.title=kind.value==='local'?'Local はプロキシを使わず直接接続します':'';};
  kind.addEventListener('change',()=>{if(kind.value==='local')proxy.value='';updateKind();});updateKind();
  remove.addEventListener('click',()=>{card.remove();markSettingsDirty();});
  probe.addEventListener('click',async()=>{
    if(ui.settingsDirty){inlineStatus(result,'モデル一覧の確認前に、設定を保存してください。',true);return;}
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
    finally{probe.disabled=ui.settingsLocked;}
  });
  saveSecret.addEventListener('click',async()=>{
    if(ui.settingsDirty){inlineStatus(result,'先にプロファイルの設定を保存してください。',true);return;}
    if(!secret.value){inlineStatus(result,'セットする API キーを入力してください。',true);return;}
    const key=secret.value,id=card.querySelector('[data-key="id"]').value;invalidateDiagnostics();secret.value='';saveSecret.disabled=true;
    try { await api('/api/secrets',{method:'POST',body:{id,key}});ui.secretStatus[id]=true;invalidateDiagnostics();secretState.textContent='今回の起動中に使うキーをセットしました。値は保存・再表示しません。';inlineStatus(result,'キーをセットしました。'); }
    catch(error){inlineStatus(result,errorText(error),true);}finally{saveSecret.disabled=ui.settingsLocked;}
  });
  $('profilesEditor').appendChild(card);
}
function renderSettings() {
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
  if(view==='settings') { if(!$('settingsDialog').open)$('settingsDialog').showModal(); }
  else { if($('settingsDialog').open)$('settingsDialog').close(); }
}
function runPayload() {
  return {task:$('taskInput').value,pm_profile:$('pmProfile').value,worker_profiles:[...$('workerProfiles').querySelectorAll('input:checked')].map(input=>input.value),max_workers:Number($('maxWorkers').value)};
}
function schedulePreflight() {
  if(!$('taskDialog').open)return;
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
  const current=()=>request===ui.preflightRequest&&revision===ui.settingsRevision&&$('taskDialog').open;
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
    }
  }catch(error){await settleStartPointer();if(current())inlineStatus($('preflightStatus'),errorText(error)+' 開始時にも設定を再確認します。',true);}
  finally{if(current()){$('preflightStatus').setAttribute('aria-busy','false');$('preflightPending').textContent='';}}
}
function setBriefOpen(open) {
  if(open) { if(!$('taskDialog').open)$('taskDialog').showModal();schedulePreflight(); }
  else if($('taskDialog').open)$('taskDialog').close();
}
function needsHuman(agent) { return agent.status_reason==='human_input'||(Boolean(agent.question)&&['waiting','waiting_human','needs_input'].includes(agent.status)); }
function filteredAgents(agents) {
  const query=$('agentSearch').value.trim().toLocaleLowerCase();
  return agents.filter(agent=>(!ui.needsOnly||needsHuman(agent))&&(!query||[agent.name,agent.id,agent.assignment,agent.profile_id].join(' ').toLocaleLowerCase().includes(query)));
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
function saveAgentDraft() { if(ui.selectedAgent)ui.drafts.set(ui.selectedAgent,$('messageInput').value); }
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
function selectAgent(id) { if(!ui.state.agents.some(agent=>agent.id===id&&agent.run_id===ui.selectedRun))return;const changed=changeSelection(ui.selectedRun,id);renderRun();if(changed)void pollState(); }
function selectRun(id) { if(!ui.state.runs.some(run=>run.id===id))return;const agents=ui.state.agents.filter(agent=>agent.run_id===id),changed=changeSelection(id,agents.find(agent=>!agent.parent_id)?.id||agents[0]?.id||null);inlineStatus($('messageStatus'),'');showView('work');setBriefOpen(false);renderState();if(changed)void pollState(); }

function renderRunList() {
  const signature=JSON.stringify([ui.selectedRun,ui.state.runs.map(run=>[run.id,run.task,run.status,run.status_reason,run.created_at])]);if(signature===ui.runsSignature)return;ui.runsSignature=signature;
  $('runCount').textContent=String(ui.state.runs.length);$('runList').replaceChildren();
  if(!ui.state.runs.length){$('runList').appendChild(element('p','sidebar-empty','ここにチームの作業が並びます'));return;}
  [...ui.state.runs].reverse().forEach(run=>{const button=element('button','run-link'+(run.id===ui.selectedRun?' selected':''));button.type='button';button.dataset.focusKey=`run:${run.id}`;button.append(element('span','run-link-title',String(run.task||'作業').split('\n')[0]),element('span','run-link-meta',`${stateLabel(run)} · ${localTime(run.created_at)}`));button.addEventListener('click',()=>selectRun(run.id));$('runList').appendChild(button);});
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
  const question=agent&&needsHuman(agent)?agent.question||'':'';$('humanQuestion').hidden=!question;$('humanQuestion').textContent=question?`判断が必要です\n${question}`:'';
  $('messageLabel').textContent=question?'質問への回答':'追加の指示';$('messageInput').placeholder=question?'選択肢や条件を確認し、回答を入力してください':'このエージェントへ追加の指示を送る';
  const stopping=['stopping','stopped'].includes(run?.status),eligibility=agent?.message_eligibility;
  const blocked=stopping||eligibility?.allowed===false;
  $('sendMessage').disabled=!agent||ui.busyMessage||blocked;$('messageInput').disabled=!agent||blocked;
  $('messageEligibility').textContent=eligibility?.message||(stopping?'停止したチームは再開できません。新しい仕事を開始してください':'');
  $('messageEligibility').hidden=!$('messageEligibility').textContent;
  const logs=loaded&&Array.isArray(agent?.logs)?agent.logs:[],signature=JSON.stringify([ui.selectedRun,agent?.id,loading,logs]);
  if(signature===ui.logSignature)return;ui.logSignature=signature;
  rememberConversationView();
  const container=$('conversationLog'),context=outputOwner(),view=ui.conversationViews.get(context),atBottom=view?.atBottom??true,expanded=view?.expanded||new Set();container.replaceChildren();
  ui.logContext=loaded?context:'';
  if(loading){container.appendChild(element('div','detail-loading','作業ログを読み込み中…'));return;}
  if(!logs.length){container.appendChild(element('div','empty-small',agent?'まだログはありません。作業が進むとここに表示されます。':'エージェントを選ぶと、作業の経過が表示されます。'));return;}
  logs.forEach((log,index)=>{
    const id=String(log.id??index),kind=String(log.kind||'assistant');
    if(log.thinking||kind==='thinking') {const detail=element('details','thinking');detail.dataset.logId=id;detail.open=expanded.has(id);detail.append(element('summary','',`モデルが返した思考の詳細${localTime(log.at)?' · '+localTime(log.at):''}`),element('pre','log-text',log.thinking||log.text||''));container.appendChild(detail);}
    if(kind==='thinking'||!log.text)return;
    const entry=element('article','log-entry '+(['user','tool'].includes(kind)?kind:'')),meta=element('div','log-meta');
    meta.append(element('span','log-role',({user:'あなた',assistant:agent.name||'エージェント',tool:'ツール',system:'システム',error:'エラー'})[kind]||kind),element('span','',localTime(log.at)));
    entry.append(meta,element('pre','log-text',log.text));container.appendChild(entry);
  });
  container.scrollTop=atBottom?container.scrollHeight:(view?.scroll||0);
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
function preserveControlFocus(render) {
  const key=document.activeElement?.dataset.focusKey;
  render();
  if(key&&document.activeElement===document.body) [...document.querySelectorAll('[data-focus-key]')].find(node=>node.dataset.focusKey===key)?.focus({preventScroll:true});
}
function renderRun() { preserveControlFocus(renderRunContent); }
function renderRunContent() {
  const run=getRun();$('workEmpty').hidden=Boolean(run);$('runOverview').hidden=!run;document.querySelector('.conversation-panel').hidden=!run;const agents=ui.state.agents.filter(agent=>agent.run_id===run?.id);const waiting=agents.filter(agent=>needsHuman(agent)).length;$('needsYou').textContent=`回答待ち ${waiting}`;if(!run){renderAgents(agents);renderTeamMap(agents);renderAgentTabs(agents);renderConversation(null);renderActivity(null);return;}
  $('activeRunTitle').textContent='チームの作業';$('activeRunStatus').className='status-badge '+(Object.hasOwn(STATUS_LABELS,run.status)?run.status:'');$('activeRunStatus').textContent=stateLabel(run);$('activeRunTask').textContent=run.task||'';
  const collaborationBlocked=run.collaboration_limit_reached===true;
  $('collaborationLimitNotice').hidden=!collaborationBlocked;
  $('collaborationLimitNotice').textContent=collaborationBlocked?'自動連携が上限に達したため、新しい委任・メール・完了通知を停止しました。この連携上限だけでは、開始済み・待機中の作業は停止しません。停止したチームは再開できません。上限を変更して続ける場合は、作業の停止後に設定を保存し、新しい作業を開始してください。追加の指示や回答では回数はリセットされません。':'';
  $('stopRun').disabled=!ACTIVE_STATUSES.has(run.status)||run.status==='stopping';
  const metricValues=[['自動連携',`${run.auto_collaborations??0} / ${run.max_auto_collaborations??24}`],['モデル呼び出し',run.model_calls||0],['ツール実行',run.tool_calls||0],['作業者の上限',run.max_workers||0]],metricSignature=JSON.stringify([run.id,metricValues]);
  if(metricSignature!==ui.metricSignature){ui.metricSignature=metricSignature;const metrics=$('runMetrics');metrics.replaceChildren();for(const [label,value] of metricValues){const metric=element('span','metric',label);metric.appendChild(element('b','',value));metrics.appendChild(metric);}}
  renderAgents(agents);renderTeamMap(agents);renderAgentTabs(agents);renderConversation(getAgent());renderActivity(run);
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
  $('runForm').addEventListener('input',schedulePreflight);
  $('runForm').addEventListener('change',schedulePreflight);
  $('taskDialog').addEventListener('close',()=>{releaseStartPointer();ui.preflightKey='';ui.preflightRequest++;clearTimeout(ui.preflightTimer);});
  $('settingsDialog').addEventListener('close',()=>{invalidateDiagnostics();schedulePreflight();});
  $('preflightSettings').addEventListener('click',()=>{setBriefOpen(false);showView('settings');});
  $('toggleBrief').addEventListener('click',()=>setBriefOpen(false));
  for(const id of ['newRun','launchTask','emptyNewRun'])$(id).addEventListener('click',()=>setBriefOpen(true));
  $('emptySettings').addEventListener('click',()=>showView('settings'));
  $('closeSettings').addEventListener('click',()=>showView('work'));
  $('agentSearch').addEventListener('input',()=>renderRun());
  $('needsYou').addEventListener('click',()=>{ui.needsOnly=!ui.needsOnly;$('needsYou').setAttribute('aria-pressed',String(ui.needsOnly));renderRun();});
  for(const id of ['taskDialog','settingsDialog']) { const dialog=$(id);dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();}); }
  window.addEventListener('popstate',()=>{setBriefOpen(false);showView('work');});
  $('settingsForm').addEventListener('input',event=>{if(event.target.type!=='password')markSettingsDirty();});
  $('settingsForm').addEventListener('change',event=>{if(event.target.type!=='password')markSettingsDirty();});
  $('settingsForm').addEventListener('invalid',event=>{const card=event.target.closest('.profile-editor');if(card&&card.querySelector('.profile-content').hidden)card.querySelector('[data-readonly]').click();},true);
  $('addProfile').addEventListener('click',()=>{const indexes=[...$('profilesEditor').children].map(node=>Number(node.dataset.index));const index=Math.max(-1,...indexes)+1;appendProfile({id:`profile-${index+1}`,label:'新しいプロファイル',kind:'local',base_url:'http://127.0.0.1:11434/v1',model:'',api_key_env:'',proxy_url:'',enabled:true,request_timeout_seconds:180},index);markSettingsDirty();});
  $('settingsForm').addEventListener('submit',async event=>{
    event.preventDefault();if(ui.settingsLocked||ui.settingsSaving)return;
    ui.settingsSaving=true;setSettingsLock(true);inlineStatus($('settingsStatus'),'保存しています…');
    try {const config=collectConfig();const response=await api('/api/config',{method:'PUT',body:config});ui.config=response.config||config;refreshSecretStatus(response.secret_status);invalidateDiagnostics();ui.settingsDirty=false;renderProfileChoices();inlineStatus($('settingsStatus'),'設定を保存しました。');notice('');}
    catch(error){inlineStatus($('settingsStatus'),errorText(error),true);}finally{ui.settingsSaving=false;setSettingsLock(true);}
  });
  $('runForm').addEventListener('submit',async event=>{
    event.preventDefault();const task=$('taskInput').value;if(!task.trim()||ui.startingRun)return;
    const workerProfiles=[...$('workerProfiles').querySelectorAll('input:checked')].map(input=>input.value);
    if(!workerProfiles.length&&Number($('maxWorkers').value)>0){inlineStatus($('runFormStatus'),'作業者に使ってよいプロファイルを1つ以上選んでください。',true);return;}
    ui.startingRun=true;$('startRun').disabled=true;inlineStatus($('runFormStatus'),'チームを準備しています…');
    try {const response=await api('/api/runs',{method:'POST',body:{task,pm_profile:$('pmProfile').value,worker_profiles:workerProfiles,max_workers:Number($('maxWorkers').value)}});const id=response.run?.id||response.id||response.run_id;await pollState(true);if(id)selectRun(id);inlineStatus($('runFormStatus'),'チームを開始しました。');notice('');}
    catch(error){inlineStatus($('runFormStatus'),errorText(error),true);}finally{ui.startingRun=false;$('startRun').disabled=!$('pmProfile').value;}
  });
  $('stopRun').addEventListener('click',async()=>{const run=getRun();if(!run)return;$('stopRun').disabled=true;try{await api(`/api/runs/${encodeURIComponent(run.id)}/stop`,{method:'POST',body:{}});await pollState(true);notice('チームに停止を要求しました。');}catch(error){notice(errorText(error),true);$('stopRun').disabled=false;}});
  $('messageInput').addEventListener('input',saveAgentDraft);
  $('messageForm').addEventListener('submit',async event=>{
    event.preventDefault();const agent=getAgent(),text=$('messageInput').value;if(!agent||!text.trim()||ui.busyMessage)return;ui.busyMessage=true;$('sendMessage').disabled=true;
    try {await api(`/api/agents/${encodeURIComponent(agent.id)}/message`,{method:'POST',body:{text}});if(ui.drafts.get(agent.id)===text)ui.drafts.delete(agent.id);if(ui.selectedAgent===agent.id&&$('messageInput').value===text)$('messageInput').value='';if(ui.selectedAgent===agent.id)inlineStatus($('messageStatus'),'送信しました。');await pollState(true);}
    catch(error){if(ui.selectedAgent===agent.id)inlineStatus($('messageStatus'),errorText(error),true);}finally{ui.busyMessage=false;renderConversation(getAgent());}
  });
  $('setSearchSecret').addEventListener('click',async()=>{const key=$('searchSecret').value;if(!key)return;$('searchSecret').value='';$('setSearchSecret').disabled=true;try{await api('/api/secrets',{method:'POST',body:{id:'search',key}});ui.secretStatus.search=true;invalidateDiagnostics();inlineStatus($('searchSecretStatus'),'今回の起動中に使うキーをセットしました。');}catch(error){inlineStatus($('searchSecretStatus'),errorText(error),true);}finally{$('setSearchSecret').disabled=ui.settingsLocked;}});
  try {
    const fragment=new URLSearchParams(location.hash.slice(1)),token=fragment.get('token');
    if(token){history.replaceState(null,'',location.pathname+location.search);await api('/api/bootstrap',{method:'POST',headers:{'X-Workbench-Bootstrap':token},body:{}});}
    const response=await api('/api/config');ui.config=response.config;ui.secretStatus=response.secret_status||{};ui.authenticated=true;renderSettings();renderProfileChoices();await pollState();
  }catch(error){notice(errorText(error),true);setConnection(false,'Workbench 接続待ち');$('startRun').disabled=true;}
  window.setInterval(()=>pollState(),1000);
}
document.addEventListener('DOMContentLoaded',initialize,{once:true});
