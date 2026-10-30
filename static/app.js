'use strict';

const DUCKDUCKGO_SEARCH_ENDPOINT='https://html.duckduckgo.com/html/';
const FIELD_GROUPS = {
  work_board: [['enabled','新しい作業で共有掲示板を使う','checkbox']],
  copilot_agent: [
    ['enabled','Copilot-agent mode を有効にする','checkbox'],
    ['bridge_directory','既存の copilot-bridge フォルダー','text','例：C:\\Tools\\copilot-bridge'],
    ['python_executable','Bridge 用 python.exe の絶対パス','text','例：C:\\Python312\\python.exe'],
    ['base_url','Bridge の API ベース URL','url','http://127.0.0.1:8800/v1'],
    ['model','Bridge のモデル名','text','copilot'],
    ['startup_timeout_seconds','Bridge 起動の待機上限（秒）','number',5,'1','Edge の準備とサインインを待つ時間です。',1200],
    ['max_concurrent_requests','Copilot の同時リクエスト上限','range',1,'1','作業者数とは別です。実際の並行処理は Bridge のウィンドウ数・サーバー容量にも制限されます。',16],
  ],
  orchestration: [
    ['delegation_level','新しい作業の PM 分担方針','range',0,'1','PM中心／委任優先／委任必須。人数・権限・呼び出し予算は別の上限です。',2],
    ['workers_per_pm','PM1人あたりの委任人数（既定値）','range',1,'1','委任優先では目標人数、委任必須では各 PM が満たす人数です。PM中心では使用しません。',16],
  ],
  paths: [
    ['read_roots','読み取りを許可する場所','paths','例：C:\\Projects\\research'],
    ['write_roots','書き込みを許可する場所','paths','例：C:\\Projects\\output'],
    ['deny_roots','アクセスを拒否する場所','paths','例：C:\\Users\\you\\.ssh'],
  ],
  python: [
    ['enabled','Python スクリプト実行を有効にする','checkbox'],
    ['network_enabled','Python のネットワーク接続を許可','checkbox'],
    ['executable','既存の python.exe の絶対パス','text','例：C:\\Python312\\python.exe'],
    ['library_paths','既存ライブラリの場所（1行1パス）','paths','例：C:\\Python312\\Lib\\site-packages'],
    ['timeout_seconds','1回の実行時間上限（秒）','number',1],
    ['max_memory_mb','実行メモリ上限（MB）','number',128],
    ['max_output_bytes','標準出力・エラーの上限（byte）','number',1024],
  ],
  selenium: [
    ['enabled','Selenium のブラウザー操作を許可','checkbox'],
    ['browser','使用するブラウザー','select',[['edge','Microsoft Edge'],['chrome','Google Chrome']]],
    ['browser_executable','既存のブラウザー実行ファイルの絶対パス','text','例：C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'],
    ['driver_executable','既存の WebDriver の絶対パス','text','例：C:\\Tools\\msedgedriver.exe'],
    ['library_paths','Selenium の既存ライブラリの場所（1行1パス）','paths','例：C:\\Python312\\Lib\\site-packages'],
    ['proxy_url','Selenium 専用プロキシ URL（空欄は直接接続）','url'],
    ['timeout_seconds','1回のブラウザー操作の時間上限（秒）','number',10],
    ['max_memory_mb','ブラウザー実行メモリ上限（MB）','number',256],
    ['max_output_chars','取得テキストの上限（文字）','number',1000],
  ],
  search: [
    ['enabled','Web 検索・ページ取得を使う','checkbox'],
    ['provider','検索エンジン','select',[['duckduckgo','DuckDuckGo（API キー不要）'],['searxng','SearXNG']]],
    ['endpoint','検索の接続先 URL（DuckDuckGo は固定）','url'],
    ['proxy_url','検索用プロキシ URL（任意）','url'],
    ['timeout_seconds','検索タイムアウト（秒）','number',1],
    ['max_response_bytes','検索応答の最大サイズ（byte）','number',1024],
  ],
  local: [
    ['max_concurrent_requests','Local の同時リクエスト上限','range',1,'1','同じモデルの作業者が複数いても、この上限に従って順番待ちします。Copilot の上限とは別です。',16],
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
    ['max_context_chars','リクエスト文脈の上限（文字）','number',1000,'1','システム方針・ツール定義・会話を含みます。実モデルの窓サイズとは別の上限です。'],
    ['auto_compact','古い会話を自動で要約する','checkbox'],
    ['context_trigger_percent','要約を始める文脈使用率（%）','number',50],
    ['context_recent_groups','そのまま残す直近のやり取り数','number',2,'1','ツール呼び出しと結果の組は分割しません。元の依頼と直近2件の人の発言も保持します。'],
    ['context_summary_chars','1つの要約の上限（文字）','number',512],
    ['context_reserve_tokens','モデル文脈予算の追加余白（推定 token）','number',256],
    ['max_history_chars','元の履歴のメモリ上限（文字／担当者）','number',4000,'1','上限超過は古い記録から削除。最大2000件。自動保存・再起動後の復元はしません。'],
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
  ['context_window_tokens','モデル文脈予算（推定 token、0 は無効）','number',0,'1','モデルに合わせて指定。UTF-8 byte 数を保守的な推定に使用し、出力上限と追加余白も確保します。正確な token 数・収容の保証ではありません。'],
];
const STATUS_LABELS = {queued:'順番待ち',working:'作業中',running:'実行中',waiting:'待機',waiting_human:'回答待ち',needs_input:'回答待ち',done:'完了',completed:'完了',error:'エラー',failed:'エラー',stopping:'停止処理中',stopped:'停止',idle:'待機',interrupted:'中断'};
const NUMBER_BOUNDS={local:{max_concurrent_requests:[1,16],queue_timeout_seconds:[1,3600],request_timeout_seconds:[5,1800],min_interval_seconds:[0,120],max_retries:[0,3],retry_backoff_seconds:[0,60],gpu_index:[0,31],max_vram_mb:[0,1048576],max_gpu_utilization_percent:[0,100],gpu_wait_timeout_seconds:[1,3600],gpu_poll_interval_seconds:[.1,60]},limits:{max_workers:[0,16],max_auto_collaborations:[0,1000],max_model_calls:[1,1000],max_tool_calls:[1,5000],max_turns_per_agent:[1,100],max_run_seconds:[10,86400],max_context_chars:[4000,2000000],context_trigger_percent:[50,90],context_recent_groups:[2,32],context_summary_chars:[512,16000],context_reserve_tokens:[256,65536],max_history_chars:[4000,4000000],max_output_tokens:[128,65536],max_file_bytes:[1024,52428800]},search:{timeout_seconds:[1,60],max_response_bytes:[1024,4194304]}};
const ACTIVE_STATUSES = new Set(['queued','working','running','waiting','waiting_human','needs_input','idle','stopping']);
const ui = {config:null,secretStatus:{},state:{runs:[],agents:[],events:[],resources:{}},selectedRun:null,selectedAgent:null,selectionGeneration:0,compactState:false,loadedDetail:null,loadedEventsRun:null,detailError:false,settingsDirty:false,settingsLocked:false,authenticated:false,polling:false,pollAgain:false,drafts:new Map(),conversationViews:new Map(),logContext:'',logSignature:'',busyMessage:false,outputSelections:new Map(),outputContext:'',outputRequest:0,outputSignature:'',settingsRevision:0,preflightRequest:0,preflightTimer:null,preflightKey:'',startPointerActive:false,startPointerWaiters:[]};
Object.assign(ui,{navigationGeneration:0,taskDialogGeneration:0,taskDraftGeneration:0,taskDraftKey:'',workspaceGeneration:0,noticeGeneration:0,startOperation:null,stoppingRuns:new Map()});
Object.assign(ui,{configRevision:null,configStale:false,settingsReloading:false,credentialGeneration:0,credentialOperations:new Map(),secretSources:{},credentialStorage:null,credentialRecoveryControls:[]});
Object.assign(ui,{settingsDraftGeneration:0,settingsSaveOperation:null});
Object.assign(ui,{skillsOperation:null,skillsCatalog:null,skillsGeneration:0});
Object.assign(ui,{settingsStorage:null,settingsTransferOperation:null,historyStorage:null,instanceId:null,retiredInstances:new Set(),messageOperation:null});
Object.assign(ui,{workBoards:new Map(),boardOwner:null,boardComposingRun:null,boardRedactionRevision:null});
const WORK_BOARD_DEFAULTS={enabled:false};
Object.assign(ui,{draftRevisions:new Map(),questionSearch:'',crewSearch:''});
Object.assign(ui,{draftQuestions:new Map(),composerQuestion:null,questionNotified:new Set(),questionNotifications:new Map(),notificationPermissionRequest:null,notificationError:''});
Object.assign(ui,{taskReuseCandidate:null,taskReuseSource:null});
Object.assign(ui,{additionalPMSequence:0,taskOrchestrationInitialized:false});
Object.assign(ui,{cockpitView:'network',networkNodes:new Map(),networkLayoutKey:'',networkMailKey:'',activityFilter:'all'});
Object.assign(ui,{networkViews:new Map(),networkGesture:null,networkSuppressClick:null,networkParentLines:[],networkMailLines:[]});
Object.assign(ui,{networkHoverAgent:null,networkFocusAgent:null,networkPreviewHovered:false,networkPreviewDismissTimer:null,networkPreviewReady:false,networkPulses:new Map(),networkPulseSequence:0,networkMotionEnabled:true,networkConnected:false,networkReducedMotion:false});
const NETWORK_NODE_SIZE=112,NETWORK_NODE_RADIUS=56,NETWORK_MAIL_SEEN_LIMIT=200,NETWORK_PULSE_LIMIT=16,NETWORK_PULSE_MS=1200,NETWORK_PREVIEW_DISMISS_MS=240;
Object.assign(ui,{effectiveProviders:null,copilotAgentStatus:null,copilotDefaultsPending:false,modelChoicesTouched:false,copilotReconnectOperation:null});
const COPILOT_AGENT_DEFAULTS={enabled:false,bridge_directory:'',python_executable:'',base_url:'http://127.0.0.1:8800/v1',model:'copilot',startup_timeout_seconds:600,max_concurrent_requests:1};
const ORCHESTRATION_DEFAULTS={delegation_level:1,workers_per_pm:2};
const DELEGATION_LABELS=['PM中心','委任優先','委任必須'];
NUMBER_BOUNDS.copilot_agent={startup_timeout_seconds:[5,1200],max_concurrent_requests:[1,16]};
NUMBER_BOUNDS.orchestration={delegation_level:[0,2],workers_per_pm:[1,16]};
NUMBER_BOUNDS.python={timeout_seconds:[1,600],max_memory_mb:[128,8192],max_output_bytes:[1024,1048576]};
NUMBER_BOUNDS.selenium={timeout_seconds:[10,300],max_memory_mb:[256,8192],max_output_chars:[1000,100000]};
const $ = id => document.getElementById(id);

function element(tag, className, text) {
  const node=document.createElement(tag);
  if(className)node.className=className;
  if(text!==undefined)node.textContent=String(text);
  return node;
}
function availableProfiles() {
  return (Array.isArray(ui.effectiveProviders)?ui.effectiveProviders:(ui.config?.providers||[])).filter(profile=>profile.enabled!==false&&profile.model&&profile.base_url);
}
function acceptConnectionSettings(response) {
  acceptServerInstance(response,true);acceptSettingsStorage(response);acceptHistoryStorage(response);acceptCredentialMetadata(response);
  invalidateSkillsCatalog('保存済み設定のスキル一覧は未確認です。ボタンで再読込してください。');
  ui.effectiveProviders=Array.isArray(response.effective_providers)?response.effective_providers:null;
  if(ui.config?.copilot_agent?.enabled===true&&availableProfiles().some(profile=>profile.id==='copilot-agent'))ui.copilotDefaultsPending=true;
  else ui.copilotDefaultsPending=false;
  ui.copilotAgentStatus=response.copilot_agent_status||null;renderCopilotStatus();
}
function renderCopilotStatus() {
  const status=ui.copilotAgentStatus,enabled=ui.config?.copilot_agent?.enabled===true;
  const labels={disabled:'オフ',stopped:'未起動',starting:'起動中',ready:'接続可能',error:'起動・接続エラー',stopping:'停止中'};
  const confirmed=status&&status.enabled===enabled;
  const state=confirmed?status.state:(enabled?'unknown':'disabled');
  let text=`Copilot Agent: ${labels[state]||'状態未確認'}`;
  if(confirmed&&typeof status.message==='string'&&status.message)text+=` — ${status.message}`;
  if(enabled&&state==='starting')text+=' Edge が開いた場合は、必要に応じてサインインしてください。準備完了を待っています。';
  if(enabled&&state==='ready'&&status.ready!==true)text='Copilot Agent: 状態未確認';
  for(const id of ['copilotAgentStatus','taskCopilotAgentStatus']){const node=$(id);if(!node)continue;node.hidden=id==='taskCopilotAgentStatus'&&!enabled;inlineStatus(node,text,state==='error');}
  const reconnect=$('reconnectCopilotAgent');if(reconnect)reconnect.disabled=!canReconnectCopilot();
}
function canReconnectCopilot() {
  return ui.authenticated&&ui.config?.copilot_agent?.enabled===true&&!ui.settingsLocked&&!ui.settingsDirty&&!ui.settingsSaving&&!ui.settingsReloading&&!ui.configStale&&!ui.copilotReconnectOperation&&!ui.credentialOperations.size&&Number.isSafeInteger(ui.configRevision)&&!['ready','starting','pending','stopping'].includes(ui.copilotAgentStatus?.state);
}
async function reconnectCopilotAgent() {
  if(!canReconnectCopilot())return;
  const action={revision:ui.configRevision,workspace:ui.workspaceGeneration};ui.copilotReconnectOperation=action;renderCopilotStatus();
  inlineStatus($('copilotReconnectStatus'),'再接続を要求しています…');
  const current=()=>ui.copilotReconnectOperation===action&&ui.configRevision===action.revision&&ui.workspaceGeneration===action.workspace;
  try{
    const response=await api('/api/copilot-agent-start',{method:'POST',body:{config_revision:action.revision}});
    if(!current())return;
    if(!validSavedSettings(response,action.revision)||JSON.stringify(response.config)!==JSON.stringify(ui.config)||!response.copilot_agent_status){const failure=new Error('再接続の応答を確認できませんでした。');failure.outcomeUnknown=true;throw failure;}
    ui.copilotAgentStatus=response.copilot_agent_status;renderCopilotStatus();
    inlineStatus($('copilotReconnectStatus'),'再接続の要求を受け付けました。接続状態は上の表示で確認できます。');
  }catch(error){
    if(!current())return;
    if(error.code==='settings_changed')ui.configStale=true;
    inlineStatus($('copilotReconnectStatus'),errorText(error)+(error.outcomeUnknown?' 自動で再送信しません。接続状態を確認してください。':''),true);
  }finally{
    if(ui.copilotReconnectOperation===action)ui.copilotReconnectOperation=null;
    renderCopilotStatus();setSettingsLock(true);ui.preflightKey='';schedulePreflight();
  }
}
function acceptServerInstance(response,configuration=false) {
  if(!Object.hasOwn(response,'instance_id')) {
    if(ui.instanceId!==null)throw new Error('サーバー起動の識別情報を確認できませんでした。画面を開き直してください。');
    return false;
  }
  const id=response.instance_id;
  if(typeof id!=='string'||!id||id.length>200||ui.retiredInstances.has(id))throw new Error('以前のサーバーの応答、または識別情報が不正な応答です。');
  if(ui.instanceId===id)return false;
  const changed=ui.instanceId!==null;if(changed)ui.retiredInstances.add(ui.instanceId);ui.instanceId=id;
  if(!changed)return false;
  ui.selectionGeneration++;ui.navigationGeneration++;ui.workspaceGeneration++;ui.credentialGeneration++;
  ui.selectedRun=null;ui.selectedAgent=null;ui.loadedDetail=null;ui.loadedEventsRun=null;ui.detailError=false;
  ui.drafts.clear();ui.draftRevisions.clear();ui.draftQuestions.clear();ui.composerQuestion=null;closeQuestionNotifications();ui.conversationViews.clear();ui.outputSelections.clear();
  invalidateWorkBoardContent();ui.workBoards.clear();ui.boardOwner=null;ui.boardComposingRun=null;ui.boardRedactionRevision=null;
  stopNetworkMotion();clearNetworkPreview();ui.networkNodes.clear();ui.networkViews.clear();ui.networkGesture=null;ui.networkSuppressClick=null;ui.networkLayoutKey='';ui.networkMailKey='';ui.activitySignature='';ui.runsSignature='';ui.rosterSignature='';
  $('teamMap').classList.remove('is-dragging');
  ui.logSignature='';ui.outputSignature='';ui.taskReuseCandidate=null;ui.startOperation=null;ui.startingRun=false;ui.stoppingRuns.clear();ui.busyMessage=false;ui.messageOperation=null;
  ui.credentialOperations.clear();ui.secretSources={};ui.credentialStorage=null;ui.credentialRecoveryControls=[];renderCredentialStorage();ui.copilotAgentStatus=null;ui.copilotReconnectOperation=null;ui.historyStorage=null;
  ui.configStale=!configuration;clearCredentialInputs();
  invalidateSkillsCatalog('サーバーが変わりました。保存済み設定を確認してから一覧を再読込してください。');
  $('messageInput').value='';$('workBoardInput').value='';$('conversationLog').replaceChildren();$('resultText').textContent='';$('resultText').hidden=true;
  $('activityFeed').replaceChildren();$('taskReuseConfirm').hidden=true;$('taskReusePreview').textContent='';
  ui.state={runs:[],agents:[],events:[],resources:{}};renderState();renderHistoryStorage();
  notice('サーバーの再起動を確認しました。前の表示と送信状態を破棄し、保存履歴を読み直します。'+(configuration?'':' 新しい作業の前に設定を読み直してください。'));
  return true;
}
function archivedRun(run) { return run?.archived===true||run?.read_only===true; }
function archivedAgent(agent) { return archivedRun(agent)||Boolean(agent&&archivedRun(ui.state.runs.find(run=>run.id===agent.run_id))); }
function displayStatus(item) { return (archivedRun(item)||archivedAgent(item))&&ACTIVE_STATUSES.has(item?.status)?'interrupted':item?.status; }
function acceptHistoryStorage(response) {
  if(Object.hasOwn(response,'history_storage'))ui.historyStorage=response.history_storage;
  renderHistoryStorage();
}
function renderHistoryStorage() {
  const storage=ui.historyStorage,known=storage?.enabled===true&&['ready','error'].includes(storage.status);
  const failed=known&&storage.status==='error';
  $('historyRetention').textContent=failed?'履歴を保存・読み込みできません。必要な報告は .txt 保存してください。':known?'表示用の会話・作業履歴を自動保存します。再起動後は閲覧専用です。':'履歴の保存状態を確認中です。必要な報告は .txt 保存できます。';
  $('historyStoragePath').textContent=known&&typeof storage.path==='string'?storage.path:'保存先は未確認です';
  const limits=[['max_runs','作業'],['max_run_bytes','バイト／作業'],['max_total_bytes','バイト合計']].filter(([key])=>Number.isSafeInteger(storage?.[key])&&storage[key]>0).map(([key,label])=>`${storage[key].toLocaleString('ja-JP')} ${label}`);
  $('historyStorageLimits').textContent=limits.length?'保存上限: '+limits.join(' · '):'';
  const message=failed?'履歴の保存・読み込みで問題があります。'+(typeof storage.error==='string'&&storage.error?` ${storage.error}`:' 保存先を確認してください。')+' 保存済みであると判断せず、必要な報告を .txt 保存してください。':'';
  $('historyStorageError').hidden=!failed;
  if($('historyStorageError').textContent!==message)$('historyStorageError').textContent=message;
}
function renderArchiveNotice(run) {
  const archived=archivedRun(run);$('archiveNotice').hidden=!archived;
  const saved=Number.isFinite(run?.history_saved_at)?localTime(run.history_saved_at):'';
  $('archiveNotice').textContent=archived?`保存した履歴を表示しています（閲覧専用）${saved?` · 保存時刻 ${saved}`:''}。${displayStatus(run)==='interrupted'?`終了時に未完了だった作業です${run.original_status?`（終了前: ${statusLabel(run.original_status)}）`:''}。`:''}自動再開はしません。続ける場合は「この依頼を新しい下書きに使う」から、新しい作業として開始してください。`:'';
  $('workspaceMode').textContent=archived?'SAVED HISTORY':'LIVE WORKSPACE';
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
function setConnection(online,text) { ui.networkConnected=online===true;if(!online){ui.networkPreviewReady=false;stopNetworkMotion();clearNetworkHover();}paintNetworkMotionState();renderNetworkPreview();$('connectionDot').classList.toggle('online',online);$('connectionDot').classList.toggle('error',!online);$('connectionStatus').textContent=text;preserveControlFocus(()=>renderCoordinationMonitor(getRun(),ui.state.agents.filter(a=>a.run_id===ui.selectedRun)));renderInspector(getAgent());renderQuestionNotice(questionEntries()); }

async function api(path,options={}) {
  const requestInstance=ui.instanceId,method=String(options.method||'GET').toUpperCase();
  const mutation=!['GET','HEAD','OPTIONS'].includes(method),bootstrap=path==='/api/bootstrap';
  const headers={'Accept':'application/json',...(options.headers||{})};
  if(mutation&&!bootstrap&&requestInstance!==null)headers['X-Workbench-Instance']=requestInstance;
  if(options.body!==undefined)headers['Content-Type']='application/json';
  let response;
  try { response=await fetch(path,{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(30000),...options,headers,body:options.body===undefined?undefined:JSON.stringify(options.body)}); }
  catch (error) { const failure=new Error(error.name==='TimeoutError'?'応答を確認できませんでした。再送信する前に、実行一覧と作業の状態を確認してください。':'接続できません。Agent Workbench のサーバーが起動しているか確認してください。');failure.outcomeUnknown=true;throw failure; }
  let data;try { data=await response.json(); } catch (_) { /* report the HTTP status below */ }
  if(!data||typeof data!=='object'||Array.isArray(data)){
    if(response.ok){const failure=new Error('応答の形式を確認できませんでした。');failure.outcomeUnknown=true;throw failure;}
    data={};
  }
  if((requestInstance!==null&&requestInstance!==ui.instanceId)||ui.retiredInstances.has(data.instance_id)){const failure=new Error('以前のサーバーの応答は適用しません。最新の状態を確認してください。');failure.outcomeUnknown=Boolean(options.method&&options.method!=='GET');throw failure;}
  if(!response.ok||data.ok===false) {
    if(response.status===409&&data.code==='instance_changed') {
      acceptServerInstance(data);ui.configStale=true;clearCredentialInputs();setSettingsLock(true);
      await pollState(true);
      const failure=new Error('サーバーが再起動したため、この処理は実行されませんでした。最新の作業と保存済み設定を確認してから、必要な操作を行ってください。自動再送信はしません。');
      failure.code='instance_changed';failure.outcomeUnknown=false;notice(failure.message,true);throw failure;
    }
    if(response.status===401) { ui.authenticated=false;setConnection(false,'認証が必要です');throw new Error('起動時に表示された専用リンクから開き直してください。'); }
    const failure=new Error(String(data.error||`リクエストに失敗しました（${response.status}）`));failure.outcomeUnknown=response.status>=500;failure.code=data.code;throw failure;
  }
  return data;
}

function delegationLabel(value) { return Number.isInteger(value)&&value>=0&&value<=2?DELEGATION_LABELS[value]:'未記録'; }
function rangeLabel(key,value) { return key==='delegation_level'?delegationLabel(Number(value)):key==='workers_per_pm'?`${value} 人`:`${value} リクエスト`; }
function makeField(spec,value,prefix) {
  const [key,label,type,extra,step,help,max]=spec,id=`${prefix}-${key}`;
  const wrap=element('div','field'+(type==='checkbox'?' checkbox-field':''));
  const name=element('label','',label);name.htmlFor=id;
  let input;
  if(type==='select') { input=element('select');for(const [v,t] of extra){const option=element('option','',t);option.value=v;input.appendChild(option);} }
  else if(type==='paths') { input=element('textarea','path-input');input.rows=4;input.placeholder=extra||''; }
  else { input=element('input');input.type=type;if(['text','url'].includes(type))input.placeholder=extra||''; }
  input.id=id;input.dataset.key=key;input.autocomplete='off';
  if(type==='number'||type==='range'){const bounds=prefix.startsWith('profile-')?(key==='context_window_tokens'?[0,2000000]:[5,1800]):NUMBER_BOUNDS[prefix]?.[key];input.min=String(bounds?.[0]??extra??0);input.step=step||'1';input.required=true;if(bounds||max!==undefined)input.max=String(bounds?.[1]??max);if(key==='max_vram_mb')input.step='1';}
  if(type==='checkbox'){input.checked=value===true;wrap.append(input,name);}
  else {input.value=type==='paths'?(Array.isArray(value)?value.join('\n'):''):String(value??'');wrap.append(name,input);}
  if(type==='range'){
    const output=element('output','range-value');output.setAttribute('for',id);output.id=`${id}-value`;wrap.append(output);
    const update=()=>{output.textContent=rangeLabel(key,input.value);input.setAttribute('aria-valuetext',output.textContent);};
    input.addEventListener('input',update);input.addEventListener('change',update);update();
  }
  if(help)wrap.appendChild(element('small','',help));
  return wrap;
}
function inputValue(input) {
  if(input.type==='checkbox')return input.checked;
  if(input.type==='number'||input.type==='range'){const n=Number(input.value);if(!Number.isFinite(n)||input.value==='')throw new Error('数値の設定を確認してください。');return n;}
  if(input.classList.contains('path-input'))return lines(input.value);
  return input.value.trim();
}
function invalidateDiagnostics() { ui.settingsRevision++;document.querySelectorAll('[data-probe-result]').forEach(node=>{node.textContent='設定または画面が変わりました。必要ならモデル一覧を再確認してください。';node.classList.remove('error');}); }
function markSettingsDirty() { ui.settingsDraftGeneration++;invalidateDiagnostics();ui.credentialGeneration++;ui.settingsDirty=true;clearCredentialInputs();setSettingsLock(true);inlineStatus($('settingsStatus'),'未保存の変更があります。キーの入力前に設定を保存するか、変更を破棄してください。'); }
function secretStatusText(configured,info) {
  const labels={session:'今回の起動中のキー',saved:'このPCのWindowsユーザーに暗号化保存したキー',environment:'環境変数のキー',none:'キー未設定'};
  if(info&&Object.hasOwn(labels,info.source)&&typeof info.saved==='boolean')return `${labels[info.source]}${info.saved?' · 暗号化保存あり':''}。値は取得・再表示しません。`;
  return configured?'キー設定あり（保存方法は未確認）。値は画面に取得しません。':'キー未設定。必要ならキーを入力するか、環境変数の参照先を確認してください。';
}
function canSaveCredential() { return ui.credentialStorage?.supported===true&&ui.credentialStorage?.available===true; }
function affectedCredentialIds() { return ui.credentialStorage?.status==='identity_mismatch'&&Array.isArray(ui.credentialStorage?.affected_ids)?[...new Set(ui.credentialStorage.affected_ids.filter(id=>typeof id==='string'&&/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(id)))]:[]; }
function acceptCredentialMetadata(response) {
  ui.secretSources=response.secret_sources&&typeof response.secret_sources==='object'&&!Array.isArray(response.secret_sources)?response.secret_sources:{};
  ui.credentialStorage=response.credential_storage&&typeof response.credential_storage==='object'&&!Array.isArray(response.credential_storage)?response.credential_storage:null;
  renderCredentialStorage();
}
function renderCredentialStorage() {
  const storage=ui.credentialStorage,known=storage&&typeof storage.supported==='boolean'&&typeof storage.available==='boolean';
  const text=!known?'暗号化保存の利用状態は未確認です。':canSaveCredential()?'このPC・このWindowsユーザーで暗号化保存できます。同じ保存先からの再起動・更新後に使えます。':storage.supported?'暗号化保存を利用できません。'+(typeof storage.error==='string'&&storage.error?` ${storage.error}`:' 保存先を確認してください。'):'この環境では暗号化保存に対応していません。この起動中のみの入力、または環境変数を使ってください。';
  inlineStatus($('credentialStorageStatus'),text,Boolean(known&&storage.supported&&!storage.available));
  $('credentialStoragePath').textContent=known&&typeof storage.path==='string'&&storage.path?`暗号化キーの保存先: ${storage.path}`:'';
  const recovery=$('credentialRecovery');recovery.replaceChildren();ui.credentialRecoveryControls=[];
  for(const id of affectedCredentialIds()){
    const row=element('div','credential-recovery-row'),label=element('p','',`保存済み接続先と一致しないキー: ${id}`),button=element('button','button secondary','この入力・保存したキーを削除'),result=element('p','inline-status');
    button.type='button';button.dataset.credential='true';button.dataset.credentialAction='clear';button.dataset.credentialProfile=id;result.setAttribute('role','status');
    const control={id,orphan:true,input:{value:''},button,clear:button,storage:{value:'session'},status:result,result,target:null};
    button.addEventListener('click',()=>setCredential(control,true));ui.credentialRecoveryControls.push(control);row.append(label,button,result);recovery.appendChild(row);
  }
  recovery.hidden=!ui.credentialRecoveryControls.length;refreshCredentialControls();
}
function refreshSecretStatus(status) {
  ui.secretStatus=status||{};
  $('profilesEditor').querySelectorAll('.profile-editor').forEach(card=>{const id=card.querySelector('[data-key="id"]').value.trim();card.querySelector('.secret-status').textContent=secretStatusText(ui.secretStatus[id],ui.secretSources[id]);});
}

function savedCredentialTarget(id) {
  if(id==='search')return null;
  const profile=ui.config?.providers?.find(item=>item.id===id);
  return profile?{id,kind:PROFILE_KINDS[profile.kind],endpoint:profile.base_url,proxy:profile.proxy_url||''}:null;
}
function credentialTargetText(id) {
  const target=savedCredentialTarget(id);
  if(target)return `保存済み接続先: ${target.id} · ${target.kind} · ${target.endpoint} · プロキシ: ${target.proxy||'なし'}`;
  return '新しいプロファイルは、接続先の設定を保存してからキーを入力してください。';
}
function credentialControls() {
  return [...$('profilesEditor').querySelectorAll('.profile-editor')].flatMap(card=>card._credential?[card._credential]:[]);
}
function clearCredentialInputs() { credentialControls().forEach(control=>{control.input.value='';}); }
function canSetCredential(id) {
  return ui.authenticated&&Number.isInteger(ui.configRevision)&&!ui.configStale&&!ui.settingsDirty&&!ui.settingsSaving&&!ui.settingsReloading&&
    !ui.credentialOperations.has(id)&&Boolean(savedCredentialTarget(id));
}
function canClearCredential(id) {
  return ui.authenticated&&Number.isInteger(ui.configRevision)&&!ui.configStale&&!ui.settingsDirty&&!ui.settingsSaving&&!ui.settingsReloading&&
    !ui.credentialOperations.has(id)&&(Boolean(savedCredentialTarget(id))||affectedCredentialIds().includes(id));
}
function refreshCredentialControls() {
  for(const control of credentialControls()){
    const allowed=canSetCredential(control.id),mode=control.storage?.value||'session';
    control.input.disabled=!allowed;control.button.disabled=!allowed||(mode==='saved'&&!canSaveCredential());
    if(control.storage){control.storage.disabled=!allowed;control.savedOption.disabled=!canSaveCredential();}
    if(control.clear)control.clear.disabled=!canClearCredential(control.id);
    if(control.modeHelp)control.modeHelp.textContent=mode==='saved'?'このPC・このWindowsユーザーに暗号化保存します。別PCや別ユーザーへのコピーでは使えません。':'新しいキーをセットすると、以前に暗号化保存したキーは削除され、この起動中だけ使います。';
    control.button.textContent=mode==='saved'?'キーを暗号化保存':'キーをセット';
    if(control.target)control.target.textContent=credentialTargetText(control.id);
  }
  for(const control of ui.credentialRecoveryControls)control.button.disabled=!canClearCredential(control.id);
}
function validCredentialReceipt(response,id,action,clearing) {
  if(!response||response.ok!==true||response.id!==id||response.config_revision!==action.revision||response.storage!==action.storage||typeof response.configured!=='boolean'||typeof response.saved!=='boolean')return false;
  const source=response.source,storage=response.credential_storage;
  if(!['session','saved','environment','none'].includes(source)||response.configured!==(source!=='none')||response.saved!==(source==='saved'))return false;
  if(!storage||typeof storage.supported!=='boolean'||typeof storage.available!=='boolean')return false;
  return clearing?['environment','none'].includes(source):source===action.storage&&(action.storage!=='saved'||storage.supported===true&&storage.available===true);
}
async function setCredential(control,clearing=false) {
  const id=control.id,storage=control.storage?.value||'session';
  if(clearing?!canClearCredential(id):!canSetCredential(id))return;
  if(!['session','saved'].includes(storage))return;
  if(!clearing&&storage==='saved'&&!canSaveCredential()){inlineStatus(control.result,'暗号化保存を利用できません。保存状態を確認してください。',true);return;}
  if(!clearing&&!control.input.value){inlineStatus(control.result,'セットする API キーを入力してください。',true);return;}
  const key=clearing?'':control.input.value;control.input.value='';
  const action={revision:ui.configRevision,generation:ui.credentialGeneration,workspace:ui.workspaceGeneration,instance:ui.instanceId,storage};
  const current=()=>ui.credentialOperations.get(id)===action&&action.revision===ui.configRevision&&action.generation===ui.credentialGeneration&&
    action.workspace===ui.workspaceGeneration&&action.instance===ui.instanceId&&$('settingsDialog').open&&control.id===id&&!ui.settingsDirty;
  ui.credentialOperations.set(id,action);invalidateWorkBoardContent();invalidateDiagnostics();setSettingsLock(true);
  inlineStatus(control.result,clearing?'入力・暗号化保存したキーを削除しています…':storage==='saved'?'保存済み接続先のキーを暗号化保存しています…':'保存済み接続先のキーをセットしています…');
  try {
    const response=await api('/api/secrets',{method:'POST',body:{id,key,storage,config_revision:action.revision}});
    if(!validCredentialReceipt(response,id,action,clearing)){
      const failure=new Error('キーの更新応答を確認できませんでした。');failure.outcomeUnknown=true;throw failure;
    }
    if(!current())return;
    ui.secretStatus[id]=response.configured;ui.secretSources[id]={source:response.source,saved:response.saved};ui.credentialStorage=response.credential_storage;
    refreshSecretStatus(ui.secretStatus);renderCredentialStorage();
    const message=clearing?'入力・保存したキーを削除しました。'+(response.source==='environment'?'環境変数のキーは引き続き使用します。':'キーは未設定です。'):storage==='saved'?'キーを暗号化保存しました。同じPC・Windowsユーザーの次回起動でも使えます。有効性は未確認です。':'キーをセットしました。以前の暗号化保存は削除し、この起動中だけ使います。有効性は未確認です。';
    inlineStatus(control.orphan?$('credentialStorageActionStatus'):control.result,message+(clearing?'':' 接続確認・自動再試行は行いません。待機中の作業には、必要なら明示的な指示を送って再試行してください。'));
  } catch(error) {
    if(!current())return;
    if(error.code==='settings_changed'){ui.configStale=true;clearCredentialInputs();}
    inlineStatus(control.result,errorText(error)+(error.outcomeUnknown?' 更新されたかどうかは未確認です。自動再送信はしません。キー設定の有無だけでは今回の更新を確認できません。':''),true);
  } finally {
    if(ui.credentialOperations.get(id)===action)ui.credentialOperations.delete(id);
    invalidateWorkBoardContent();renderWorkBoard(getRun());
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
    ui.config=response.config;ui.configRevision=response.config_revision;ui.configStale=false;ui.secretStatus=response.secret_status||{};acceptConnectionSettings(response);
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
  return Object.entries(FIELD_GROUPS).every(([group,specs])=>['copilot_agent','orchestration'].includes(group)&&config[group]===undefined||record(config[group])&&specs.every(([key,,type])=>{
    const value=config[group][key];
    if(type==='paths')return Array.isArray(value)&&value.every(path=>typeof path==='string');
    if(type==='checkbox')return typeof value==='boolean';
    return type==='number'||type==='range'?Number.isFinite(value):typeof value==='string';
  }));
}
function acceptSettingsStorage(response) {
  if(response.settings_storage&&typeof response.settings_storage.path==='string')ui.settingsStorage=response.settings_storage;
  $('settingsStorage').textContent=ui.settingsStorage?.path?'保存先: '+ui.settingsStorage.path:'保存先は通常 %LOCALAPPDATA%\\AgentWorkbench\\settings.json です。';
  const warnings=ui.settingsStorage?.warnings;
  inlineStatus($('settingsRecovery'),Array.isArray(warnings)&&warnings.length?'保存済み設定を保持しています。見つからない場所を修正して保存するまで作業を開始できません。 '+warnings.join(' '):'',Boolean(warnings?.length));
}
function settingsTransferBlocked() {
  return !ui.authenticated||ui.settingsLocked||ui.settingsSaving||ui.settingsReloading||ui.credentialOperations.size>0||ui.configStale||!Number.isSafeInteger(ui.configRevision);
}
async function exportSettings() {
  if(settingsTransferBlocked())return;
  const workspace=ui.workspaceGeneration;
  try {
    const backup=await api('/api/config/export');
    if(workspace!==ui.workspaceGeneration||!$('settingsDialog').open)return;
    if(backup.format!=='agent-workbench-settings'||backup.format_version!==1||!backup.config)throw new Error('設定のバックアップ応答を確認できませんでした。');
    // Only the server's saved public configuration is downloaded, never form/key inputs.
    downloadSettingsJson(JSON.stringify(backup,null,2)+'\n','AgentWorkbench-settings.json');
    inlineStatus($('settingsTransferStatus'),'保存済み設定のダウンロードを開始しました。未保存の編集は含みません。');
  } catch(error){if(workspace===ui.workspaceGeneration&&$('settingsDialog').open)inlineStatus($('settingsTransferStatus'),errorText(error),true);}
}
async function importSettingsFile(file) {
  if(!file||settingsTransferBlocked())return;
  if(file.size>512*1024){inlineStatus($('settingsTransferStatus'),'設定ファイルは512 KB以内にしてください。',true);return;}
  const action={workspace:ui.workspaceGeneration,revision:ui.configRevision,draft:ui.settingsDraftGeneration};
  const owns=()=>ui.settingsTransferOperation===action&&action.workspace===ui.workspaceGeneration&&action.revision===ui.configRevision&&action.draft===ui.settingsDraftGeneration&&$('settingsDialog').open&&!ui.settingsLocked&&!ui.configStale;
  ui.settingsTransferOperation=action;ui.settingsReloading=true;clearCredentialInputs();setSettingsLock(true);
  inlineStatus($('settingsTransferStatus'),'設定ファイルを確認しています…');
  try {
    const contents=await file.text();if(!owns())return;
    let backup;try{backup=JSON.parse(contents.replace(/^\uFEFF/,''));}catch(_){throw new Error('JSON形式の設定ファイルを選んでください。');}
    const response=await api('/api/config/import-preview',{method:'POST',body:{config_revision:action.revision,backup}});
    if(!owns())return;
    const status={...Object.fromEntries((response.config?.providers||[]).map(profile=>[profile.id,false])),search:false};
    if(!validSavedSettings({...response,secret_status:status},action.revision)||!Array.isArray(response.warnings)||!response.warnings.every(w=>typeof w==='string'))throw new Error('読み込んだ設定を確認できませんでした。');
    // Keep the saved baseline and task drafts intact until the normal Save succeeds.
    renderSettings(response.config);markSettingsDirty();
    inlineStatus($('settingsTransferStatus'),'設定を編集欄へ読み込みました。内容を確認して「設定を保存」を押してください。 '+response.warnings.join(' '));
  } catch(error){if(owns()){if(error.code==='settings_changed')ui.configStale=true;inlineStatus($('settingsTransferStatus'),errorText(error),true);}}
  finally{if(ui.settingsTransferOperation===action){ui.settingsTransferOperation=null;ui.settingsReloading=false;setSettingsLock(true);schedulePreflight();}}
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
    ui.config=response.config;ui.configRevision=response.config_revision;ui.configStale=false;ui.secretStatus=response.secret_status;ui.credentialGeneration++;acceptConnectionSettings(response);
    ui.settingsDirty=!sameDraft;
    if(sameDraft){
      $('profilesEditor').querySelectorAll('.profile-editor').forEach(card=>{card._credential.id=inputValue(card.querySelector('[data-key="id"]'));});
      if(JSON.stringify(action.config.search)!==JSON.stringify(response.config.search))$('searchFields')._syncSavedSearch(response.config.search);
    }
    if(owns())invalidateDiagnostics();else ui.settingsRevision++;
    preserveControlFocus(()=>renderProfileChoices(true),()=>$('pmProfile'));
    if(owns()&&sameDraft){refreshSecretStatus(response.secret_status);inlineStatus($('settingsStatus'),'設定を保存しました。');}
  } catch(error) {
    if(ui.settingsSaveOperation!==action)return;
    if(error.outcomeUnknown||error.code==='settings_changed'){ui.configStale=true;if(owns()){clearCredentialInputs();invalidateDiagnostics();}else ui.settingsRevision++;}
    if(owns())inlineStatus($('settingsStatus'),errorText(error)+(error.outcomeUnknown?' 保存されたかどうかは未確認です。自動再送信はしません。変更内容を控えてから、保存済み設定を読み直してください。':error.code==='settings_changed'?' この下書きは保存していません。変更内容を控えてから、保存済み設定を読み直してください。':error.code==='saved_credential_identity_change'?' この下書きは保存していません。変更内容を控え、保存済み設定を読み直して該当のキーを削除してから、接続先の変更をやり直してください。':''),true);
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
  const secretRow=element('div','profile-secret'),secretField=element('div','field'),secretLabel=element('label','', 'API キー（任意）');
  const storageField=element('div','field credential-storage-field'),storageLabel=element('label','','キーの保存方法'),storage=element('select'),modeHelp=element('small');
  storage.id=`profile-${index}-secret-storage`;storageLabel.htmlFor=storage.id;storage.dataset.credential='true';
  const sessionOption=element('option','','この起動中のみ'),savedOption=element('option','','このWindowsユーザーに暗号化保存');sessionOption.value='session';savedOption.value='saved';
  storage.append(sessionOption,savedOption);storage.value='session';storageField.append(storageLabel,storage,modeHelp);secretRow.appendChild(storageField);
  const secret=element('input');secret.type='password';secret.autocomplete='new-password';secret.id=`profile-${index}-secret`;secretLabel.htmlFor=secret.id;
  secret.dataset.credential='true';
  secret.placeholder='空欄では現在のキー設定を変更しません';secretField.append(secretLabel,secret);
  const saveSecret=element('button','button secondary','キーをセット');saveSecret.type='button';
  saveSecret.dataset.credential='true';saveSecret.dataset.credentialAction='set';saveSecret.dataset.credentialProfile=profile.id;
  const secretState=element('p','secret-status',secretStatusText(ui.secretStatus[profile.id],ui.secretSources[profile.id]));
  const clearSecret=element('button','button minor credential-clear','入力・保存したキーを削除');clearSecret.type='button';clearSecret.dataset.credential='true';clearSecret.dataset.credentialAction='clear';clearSecret.dataset.credentialProfile=profile.id;
  secretRow.append(secretField,saveSecret,clearSecret,secretState);content.appendChild(secretRow);
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
  card._credential={id:saved?profile.id:null,input:secret,button:saveSecret,clear:clearSecret,storage,savedOption,modeHelp,status:secretState,result:secretResult,target};
  storage.addEventListener('change',()=>refreshCredentialControls());clearSecret.addEventListener('click',()=>setCredential(card._credential,true));
  saveSecret.addEventListener('click',()=>setCredential(card._credential));
  secret.addEventListener('keydown',event=>{if(event.isComposing||event.keyCode===229)return;if(event.key==='Enter'){event.preventDefault();setCredential(card._credential);}});
  $('profilesEditor').appendChild(card);
}
function configureSearchFields(search) {
  const container=$('searchFields'),provider=container.querySelector('[data-key="provider"]'),endpoint=container.querySelector('[data-key="endpoint"]');
  let previous=provider.value,searxngEndpoint=search.provider==='searxng'?search.endpoint:'';
  const update=()=>{
    if(previous==='searxng')searxngEndpoint=endpoint.value;
    endpoint.readOnly=provider.value==='duckduckgo';
    endpoint.value=endpoint.readOnly?DUCKDUCKGO_SEARCH_ENDPOINT:searxngEndpoint;
    previous=provider.value;
  };
  container._syncSavedSearch=saved=>{
    for(const [key,,type] of FIELD_GROUPS.search){
      const input=container.querySelector(`[data-key="${key}"]`);
      if(type==='checkbox')input.checked=saved[key];
      else if(input.value!==String(saved[key]??''))input.value=String(saved[key]??'');
    }
    previous=provider.value;searxngEndpoint=saved.provider==='searxng'?saved.endpoint:'';update();
  };
  provider.addEventListener('change',update);update();
}
function renderSettings(config=ui.config) {
  ui.settingsDraftGeneration++;
  ui.credentialGeneration++;
  $('profilesEditor').replaceChildren();(config.providers||[]).forEach((profile,index)=>appendProfile(profile,index,index===0));
  const containers={work_board:'workBoardFields',copilot_agent:'copilotAgentFields',orchestration:'orchestrationFields',paths:'pathFields',python:'pythonFields',selenium:'seleniumFields',search:'searchFields',local:'localFields',limits:'budgetFields'};
  for(const [group,specs] of Object.entries(FIELD_GROUPS)){const container=$(containers[group]),defaults=group==='copilot_agent'?COPILOT_AGENT_DEFAULTS:group==='orchestration'?ORCHESTRATION_DEFAULTS:group==='work_board'?WORK_BOARD_DEFAULTS:{};container.replaceChildren();specs.forEach(spec=>container.appendChild(makeField(spec,({...defaults,...config[group]})[spec[0]],group)));}
  configureSearchFields(config.search);
  $('workBoardFields').querySelector('[data-key="enabled"]').setAttribute('aria-describedby','workBoardSettingsHelp');
  $('copilotAgentFields').querySelector('[data-key="enabled"]').setAttribute('aria-describedby','copilotAgentHelp');renderCopilotStatus();
  $('pythonFields').querySelector('[data-key="network_enabled"]').setAttribute('aria-describedby','pythonNetworkHelp');
  $('seleniumFields').querySelector('[data-key="enabled"]').setAttribute('aria-describedby','seleniumRuntimeHelp seleniumBoundaryHelp');
  $('systemPolicy').value=config.system_policy||'';ui.settingsDirty=false;inlineStatus($('settingsStatus'),'');refreshSecretStatus(ui.secretStatus);setSettingsLock(true);
}
function renderSkillControls() {
  $('reloadSkills').disabled=Boolean(ui.skillsOperation||!ui.authenticated||!ui.config||ui.configStale||ui.settingsSaving||ui.settingsReloading);
  $('skillsList').setAttribute('aria-busy',String(Boolean(ui.skillsOperation)));
}
function invalidateSkillsCatalog(message) {
  ui.skillsGeneration++;ui.skillsOperation=null;ui.skillsCatalog=null;
  $('skillsList').replaceChildren();$('skillsErrors').replaceChildren();
  inlineStatus($('skillsStatus'),message||'一覧は未確認です。ボタンで読み込みます。');
  renderSkillControls();
}
function validSkillsCatalog(value,action) {
  const record=item=>item!==null&&typeof item==='object'&&!Array.isArray(item);
  const strings=(item,keys)=>record(item)&&keys.every(key=>typeof item[key]==='string');
  return record(value)&&value.config_revision===action.revision&&value.instance_id===action.instance&&
    Array.isArray(value.skills)&&Array.isArray(value.errors)&&
    value.skills.every(item=>strings(item,['id','name','description','path','base_directory','sha256'])&&item.id&&item.name&&/^[a-f0-9]{64}$/.test(item.sha256))&&
    new Set(value.skills.map(item=>item.id)).size===value.skills.length&&
    value.errors.every(item=>strings(item,['path','error']));
}
function displaySkillsCatalog(value) {
  const list=$('skillsList'),errors=$('skillsErrors');list.replaceChildren();errors.replaceChildren();
  for(const skill of value.skills){
    const row=element('li');row.append(element('strong','',skill.name),element('p','small',skill.description));
    const details=element('details');details.append(element('summary','','場所と読み込んだ版を確認'),
      element('p','field-help',`スキル ID: ${skill.id}`),
      element('p','field-help',skill.path),element('p','field-help',`参照ファイルの基準: ${skill.base_directory}`),
      element('p','field-help',`SHA-256: ${skill.sha256}`));row.append(details);list.append(row);
  }
  for(const issue of value.errors){
    const row=element('li','error');row.append(element('strong','',issue.path||'スキルの探索'),element('p','small',issue.error));errors.append(row);
  }
  const message=value.skills.length?`${value.skills.length} 件のスキルを確認しました。`:'読み込めるスキルはありません。';
  inlineStatus($('skillsStatus'),message+(value.errors.length?` 読込エラー ${value.errors.length} 件を確認してください。`:'')+
    ' 保存済み設定での確認です。実行中の作業には反映しません。',value.errors.length>0);
}
async function reloadSkills() {
  if(ui.skillsOperation||!$('settingsDialog').open||!ui.authenticated||!ui.config||ui.configStale||ui.settingsSaving||ui.settingsReloading)return;
  if(!Number.isSafeInteger(ui.configRevision)||ui.configRevision<0||typeof ui.instanceId!=='string'||!ui.instanceId){
    inlineStatus($('skillsStatus'),'保存済み設定とサーバーの識別情報を確認してください。',true);return;
  }
  const action={generation:++ui.skillsGeneration,revision:ui.configRevision,instance:ui.instanceId,workspace:ui.workspaceGeneration};
  const owns=()=>ui.skillsOperation===action&&action.generation===ui.skillsGeneration&&action.revision===ui.configRevision&&
    action.instance===ui.instanceId&&action.workspace===ui.workspaceGeneration&&$('settingsDialog').open&&!ui.configStale;
  ui.skillsOperation=action;ui.skillsCatalog=null;$('skillsList').replaceChildren();$('skillsErrors').replaceChildren();renderSkillControls();
  inlineStatus($('skillsStatus'),'保存済みの読み取り許可フォルダーからスキルを確認しています…');
  try{
    const value=await api('/api/skills');if(!owns())return;
    if(!validSkillsCatalog(value,action))throw new Error('スキル一覧の応答を確認できませんでした。保存済み設定を読み直してください。');
    ui.skillsCatalog=value;displaySkillsCatalog(value);
  }catch(error){
    if(owns()){
      if(error.code==='settings_changed'){ui.configStale=true;setSettingsLock(true);}
      inlineStatus($('skillsStatus'),errorText(error)+' 一覧は未確認です。必要ならボタンで再読込してください。',true);
    }
  }finally{if(ui.skillsOperation===action)ui.skillsOperation=null;renderSkillControls();}
}
function collectConfig() {
  const config=structuredClone(ui.config);
  config.providers=[...$('profilesEditor').querySelectorAll('.profile-editor')].map(card=>{
    const profile={...card._original};card.querySelectorAll('[data-key]').forEach(input=>{profile[input.dataset.key]=inputValue(input);});return profile;
  });
  const ids=config.providers.map(profile=>profile.id);
  if(new Set(ids).size!==ids.length)throw new Error('プロファイル ID が重複しています。別の ID を指定してください。');
  if(!config.providers.length)throw new Error('プロファイルを1つ以上追加してください。');
  const containers={work_board:'workBoardFields',copilot_agent:'copilotAgentFields',orchestration:'orchestrationFields',paths:'pathFields',python:'pythonFields',selenium:'seleniumFields',search:'searchFields',local:'localFields',limits:'budgetFields'};
  for(const [group,id] of Object.entries(containers)){config[group]={...config[group]};$(id).querySelectorAll('[data-key]').forEach(input=>{config[group][input.dataset.key]=inputValue(input);});}
  config.search.api_key_env='';
  if(config.search.provider==='duckduckgo')config.search.endpoint=DUCKDUCKGO_SEARCH_ENDPOINT;
  if(ui.config.copilot_agent===undefined&&JSON.stringify(config.copilot_agent)===JSON.stringify(COPILOT_AGENT_DEFAULTS))delete config.copilot_agent;
  if(ui.config.orchestration===undefined&&JSON.stringify(config.orchestration)===JSON.stringify(ORCHESTRATION_DEFAULTS))delete config.orchestration;
  if(ui.config.work_board===undefined&&JSON.stringify(config.work_board)===JSON.stringify(WORK_BOARD_DEFAULTS))delete config.work_board;
  config.system_policy=$('systemPolicy').value;
  return config;
}
function setSettingsLock(force=false) {
  const locked=ui.state.runs.some(run=>!archivedRun(run)&&ACTIVE_STATUSES.has(run.status));ui.settingsLocked=locked;
  const disabled=locked||ui.settingsSaving===true||ui.settingsReloading||ui.credentialOperations.size>0;
  $('settingsForm').querySelectorAll('input,textarea,select,button').forEach(node=>{if(node.dataset.credential!=='true')node.disabled=disabled&&node.dataset.readonly!=='true'||ui.configStale&&(node.type==='submit'||node.dataset.probe==='true');});$('saveSettings').disabled=disabled||ui.configStale;
  if(!disabled)$('profilesEditor').querySelectorAll('.profile-editor').forEach(card=>{card.querySelector('[data-key="proxy_url"]').disabled=card.querySelector('[data-key="kind"]').value==='local';});
  refreshCredentialControls();$('discardSettings').disabled=Boolean(ui.settingsSaving||ui.settingsReloading||ui.credentialOperations.size);
  for(const id of ['exportSettings','importSettings','settingsImportFile'])$(id).disabled=Boolean(disabled||ui.configStale);
  const lockText=(locked?'作業の実行中は接続先・モデル・権限を変更できません。保存済み接続先のキーだけ変更できます。':'')+(ui.configStale?' 保存済み設定が変わったか、保存結果が未確認です。変更内容を控えてから「変更を破棄・保存済み設定を読み直す」で確認してください。保存・キー更新・モデル確認はそれまで行いません。':'');
  if($('settingsLockStatus').textContent!==lockText)$('settingsLockStatus').textContent=lockText;
  renderCopilotStatus();
  renderSkillControls();
}
function renderProfileChoices(preserveDraft=false,preferDefault=false) {
  if(!ui.taskOrchestrationInitialized){applyTaskOrchestrationDefaults();ui.taskOrchestrationInitialized=true;}
  let previous=$('pmProfile').value,checked=new Set([...$('workerProfiles').querySelectorAll('input:checked')].map(input=>input.value));
  const profiles=availableProfiles();
  if((!preserveDraft||preferDefault)&&ui.copilotDefaultsPending&&!ui.modelChoicesTouched&&!$('taskInput').value.trim()&&!$('additionalPMs').children.length&&profiles.some(profile=>profile.id==='copilot-agent')){
    previous='copilot-agent';checked=new Set(['copilot-agent']);ui.copilotDefaultsPending=false;
  }
  $('pmProfile').replaceChildren();$('workerProfiles').replaceChildren();
  if(!profiles.length){const empty=element('option','','設定でモデル名を指定してください');empty.value='';$('pmProfile').appendChild(empty);$('workerProfiles').appendChild(element('span','muted small','設定でプロファイルを完成させると選択できます。'));}
  profiles.forEach(profile=>{const option=element('option','',profileLabel(profile));option.value=profile.id;$('pmProfile').appendChild(option);});
  if(preserveDraft&&previous&&!profiles.some(profile=>profile.id===previous)){const option=element('option','',`${previous}（保存済み設定では利用不可）`);option.value=previous;$('pmProfile').appendChild(option);}
  if(preserveDraft||profiles.some(profile=>profile.id===previous))$('pmProfile').value=previous;
  else if(profiles.length)$('pmProfile').value=profiles[0].id;
  $('additionalPMs').querySelectorAll('select').forEach(select=>fillAdditionalPMChoice(select,select.value));
  syncAdditionalPMControls();
  const choices=[...profiles,...(preserveDraft?[...checked].filter(id=>!profiles.some(profile=>profile.id===id)).map(id=>({id,label:`${id}（保存済み設定では利用不可）` })):[])];
  choices.forEach(profile=>{const label=element('label','choice'),input=element('input');input.type='checkbox';input.value=profile.id;input.dataset.focusKey=`task-worker:${profile.id}`;input.checked=preserveDraft||checked.size?checked.has(profile.id):profile.id===$('pmProfile').value;label.append(input,element('span','',profile.label||profile.id));$('workerProfiles').appendChild(label);});
  const limit=Number(ui.config.limits?.max_workers??3);$('maxWorkers').max=String(limit);if(!preserveDraft)$('maxWorkers').value=String(Math.min(Number($('maxWorkers').value),limit));
  $('policyPreview').textContent=ui.config.system_policy||'設定された共通方針はありません。';trackTaskDraft();syncStartControl();
}
function fillAdditionalPMChoice(select,previous) {
  const profiles=availableProfiles();
  select.replaceChildren();
  profiles.forEach(profile=>{const option=element('option','',profileLabel(profile));option.value=profile.id;select.appendChild(option);});
  if(!profiles.some(profile=>profile.id===previous)){
    const option=element('option','',previous?`${previous}（保存済み設定では利用不可）`:'設定でモデル名を指定してください');
    option.value=previous;select.appendChild(option);
  }
  select.value=previous;
}
function syncAdditionalPMControls() {
  const rows=[...$('additionalPMs').children];
  rows.forEach((row,index)=>{row.querySelector('label').textContent=`PM ${index+2} のプロファイル`;row.querySelector('button').setAttribute('aria-label',`PM ${index+2} を取り除く`);});
  $('additionalPMCount').textContent=`PM ${rows.length+1} 人`;
  $('addPM').disabled=rows.length>=15||!availableProfiles().length;
}
function addPM() {
  if($('additionalPMs').children.length>=15||$('addPM').disabled)return;
  const row=element('div','additional-pm-row'),field=element('div','field');
  const label=element('label'),select=element('select'),remove=element('button','button minor','削除');
  select.id=`additional-pm-${++ui.additionalPMSequence}`;select.dataset.focusKey=select.id;select.required=true;label.htmlFor=select.id;
  fillAdditionalPMChoice(select,$('pmProfile').value);field.append(label,select);remove.type='button';row.append(field,remove);
  remove.addEventListener('click',()=>{
    const rows=[...$('additionalPMs').children],index=rows.indexOf(row);row.remove();syncAdditionalPMControls();
    trackTaskDraft({type:'change'});syncStartControl();schedulePreflight();
    ($('additionalPMs').children[index]?.querySelector('select')||$('addPM')).focus();
  });
  $('additionalPMs').appendChild(row);$('additionalPMSettings').open=true;syncAdditionalPMControls();
  trackTaskDraft({type:'change'});syncStartControl();schedulePreflight();select.focus();
}
function showView(view) {
  if(view==='settings') { if(!$('settingsDialog').open){ui.workspaceGeneration++;$('settingsDialog').showModal();} }
  else { if($('settingsDialog').open){ui.workspaceGeneration++;$('settingsDialog').close();} }
  if(view==='settings'){clearNetworkHover();stopNetworkMotion();}
  paintNetworkMotionState();reconcileTaskReuse();
}
function runPayload() {
  const payload={task:$('taskInput').value,pm_profile:$('pmProfile').value,worker_profiles:[...$('workerProfiles').querySelectorAll('input:checked')].map(input=>input.value),max_workers:Number($('maxWorkers').value),delegation_level:Number($('delegationLevel').value),workers_per_pm:Number($('workersPerPM').value)};
  const extra=[...($('additionalPMs')?.querySelectorAll('select')||[])].map(select=>select.value);
  if(extra.length)payload.pm_profiles=[payload.pm_profile,...extra];
  return payload;
}
function trackTaskDraft(event) {
  if(['input','change'].includes(event?.type)&&[ $('delegationLevel'),$('workersPerPM') ].includes(event.target))ui.taskOrchestrationInitialized=true;
  if(['input','change'].includes(event?.type)&&(event.target===$('pmProfile')||event.target?.dataset?.focusKey?.startsWith('task-worker:')||event.target?.id?.startsWith('additional-pm-')))ui.modelChoicesTouched=true;
  // An actual edit also invalidates a choice when numeric parsing would hide
  // it (0 → blank, 1 → 01), or when the user re-enters the same value.
  if(ui.taskReuseCandidate&&['input','change'].includes(event?.type))clearTaskReuse('入力を変更したため、置き換えを取り消しました。現在の入力は残しています。');
  const key=JSON.stringify(runPayload());
  if(key!==ui.taskDraftKey){ui.taskDraftKey=key;ui.taskDraftGeneration++;}
  reconcileTaskReuse();
  if(ui.taskReuseSource&&$('taskInput').value!==ui.taskReuseSource.text){ui.taskReuseSource=null;$('taskReuseProvenance').hidden=true;}
  showPendingStart();
}
function applyTaskOrchestrationDefaults() {
  const defaults=ui.config?.orchestration||ORCHESTRATION_DEFAULTS;
  $('delegationLevel').value=String(defaults.delegation_level);$('workersPerPM').value=String(defaults.workers_per_pm);
}
function taskOrchestrationIssue() {
  const level=Number($('delegationLevel').value),count=Number($('workersPerPM').value),total=Number($('maxWorkers').value);
  if($('delegationLevel').value===''||!Number.isInteger(level)||level<0||level>2||$('workersPerPM').value===''||!Number.isInteger(count)||count<1||count>16)return 'PMの分担方針と委任人数を確認してください。';
  const pms=1+($('additionalPMs')?.querySelectorAll('select')||[]).length,required=pms*count;
  return level===2&&(!Number.isInteger(total)||total<required)?`委任必須には PM ${pms} 人 × ${count} 人 = ${required} 人分の作業者上限が必要です。現在の上限は ${total} 人です。人数または方針を変更してください。`:'';
}
function renderTaskOrchestration() {
  const level=Number($('delegationLevel').value),label=delegationLabel(level),count=$('workersPerPM').value;
  $('delegationLevelValue').textContent=label;$('delegationLevel').setAttribute('aria-valuetext',label);
  $('workersPerPMValue').textContent=`${count} 人${level===0?'（PM中心では未使用）':''}`;$('workersPerPM').setAttribute('aria-valuetext',$('workersPerPMValue').textContent);
  const issue=taskOrchestrationIssue();inlineStatus($('delegationStatus'),issue|| (level===0?'PM中心では、この委任人数を使用しません。':level===1?'目標人数です。PMが必要に応じて委任し、全体の作業者上限と予算を守ります。':'各PMの委任手順が必須です。成果の品質・成功を保証する設定ではなく、全体の権限・予算も増えません。'),Boolean(issue));
  return issue;
}
function syncStartControl() { const issue=renderTaskOrchestration();$('startRun').disabled=Boolean(ui.startingRun||ui.taskReuseCandidate||issue)||!$('pmProfile').value||[...($('additionalPMs')?.querySelectorAll('select')||[])].some(select=>!select.value);syncTaskReuseControl(); }
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
  $('taskReuseConfirm').hidden=false;$('taskReusePreview').textContent=source.text;$('taskReusePreview').scrollTop=0;
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
function scrollTaskReusePreview(event) {
  const preview=$('taskReusePreview');
  if(event.target!==preview||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey||!['Home','End'].includes(event.key))return;
  // At a scroll boundary Edge otherwise passes End to the surrounding dialog,
  // moving its still-focused reading region entirely out of view. Tab and all
  // modified shortcuts keep their native behavior.
  event.preventDefault();preview.scrollTop=event.key==='Home'?0:Math.max(0,preview.scrollHeight-preview.clientHeight);
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
function canStopRun(run) { return Boolean(run)&&!archivedRun(run)&&ACTIVE_STATUSES.has(run.status)&&run.status!=='stopping'&&!ui.stoppingRuns.has(run.id); }
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
    if(response.orchestration){const policy=response.orchestration;target.append(element('p','small',`確認した分担方針: ${delegationLabel(policy.delegation_level)} · PM1人あたり ${Number.isInteger(policy.workers_per_pm)?policy.workers_per_pm:'未記録'} 人${policy.delegation_level===0?'（未使用）':''}`));}
    if(response.destinations){
      target.append(element('p','small','送信される可能性のある接続先（実際の呼び出し記録ではありません）'));
      for(const p of response.destinations)target.append(element('p','readiness-destination',`${p.pm_count?`PM ${p.pm_count} 人${p.worker_available?' / 作業者候補':''}`:p.role} · ${p.label} · ${p.model} — ${p.endpoint}${p.proxy?' · proxy: '+p.proxy:''}`));
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
  if(open) { if(!$('taskDialog').open){ui.taskDialogGeneration++;if(ui.copilotDefaultsPending)renderProfileChoices(true,true);$('taskDialog').showModal();}showPendingStart();syncStartControl();if(preview)schedulePreflight(); }
  else if($('taskDialog').open)$('taskDialog').close();
  if(open){clearNetworkHover();stopNetworkMotion();}paintNetworkMotionState();
}
function needsHuman(agent) { return !archivedAgent(agent)&&(agent.status_reason==='human_input'||(Boolean(agent.question)&&['waiting','waiting_human','needs_input'].includes(agent.status))); }
function filteredAgents(agents) {
  const query=$('agentSearch').value.trim().toLocaleLowerCase();
  return agents.filter(agent=>(!ui.needsOnly||needsHuman(agent))&&(!query||[agent.name,agent.id,agent.assignment,agent.profile_id].join(' ').toLocaleLowerCase().includes(query)));
}
function hasMessageInput(agent) {
  const run=agent&&ui.state.runs.find(run=>run.id===agent.run_id);
  if(!run||archivedRun(run)||archivedAgent(agent)||(Array.isArray(run.agent_ids)&&!run.agent_ids.includes(agent.id)))return false;
  const value=ui.selectedRun===agent.run_id&&ui.selectedAgent===agent.id?$('messageInput').value:ui.drafts.get(agent.id);
  return typeof value==='string'&&value.length>0;
}
function messageInputEntries() {
  // Presence is not a send outcome. Retained text can already have been accepted.
  const agents=new Map(ui.state.agents.map(agent=>[agent.id,agent])),seen=new Set();
  return [...ui.state.runs].reverse().flatMap(run=>{
    const members=Array.isArray(run.agent_ids)?run.agent_ids.map(id=>agents.get(id)):ui.state.agents.filter(agent=>agent.run_id===run.id);
    return members.filter(agent=>{
      if(!agent||agent.run_id!==run.id||seen.has(agent.id)||!hasMessageInput(agent))return false;
      seen.add(agent.id);return true;
    }).map(agent=>({run,agent}));
  });
}
function messageInputBadge(agent) {
  return hasMessageInput(agent)?element('span','input-presence-badge','入力あり'):null;
}
function renderMessageInputSummary() {
  const count=messageInputEntries().length,button=$('nextMessageInput'),focused=document.activeElement===button;
  if($('messageInputCount').textContent!==String(count))$('messageInputCount').textContent=String(count);
  const label=`全チームの次の入力へ。入力のある担当者 ${count}人`;
  if(button.getAttribute('aria-label')!==label)button.setAttribute('aria-label',label);
  if(button.disabled!==(count===0))button.disabled=count===0;
  const status=`全チームの入力あり ${count}人。入力の有無のみで、送信状態を示すものではありません。`;
  if($('messageInputNavigationStatus').textContent!==status)$('messageInputNavigationStatus').textContent=status;
  if(focused&&button.disabled){$('agentSearch').focus({preventScroll:true});$('agentSearch').scrollIntoView({block:'nearest',inline:'nearest'});}
}
function renderMessageInputPresence() {
  preserveControlFocus(()=>{
    renderRunList();renderMessageInputSummary();
    if(ui.needsOnly)renderQuestions(questionEntries());
    else renderAgents(ui.state.agents.filter(agent=>agent.run_id===ui.selectedRun));
  });
}
function openNextMessageInput() {
  if($('taskDialog').open||$('settingsDialog').open)return;
  saveAgentDraft();
  const entries=messageInputEntries(),index=entries.findIndex(({run,agent})=>run.id===ui.selectedRun&&agent.id===ui.selectedAgent);
  if(!entries.length){renderMessageInputPresence();return;}
  const {run,agent}=entries[(index+1)%entries.length],changed=changeSelection(run.id,agent.id);
  if(changed)ui.navigationGeneration++;
  revealInspector();
  renderState();
  // Focus belongs to this explicit action, never to a later detail response.
  ($('messageInput').disabled?$('conversationHeading'):$('messageInput')).focus();
  if(changed)void pollState();
}
function revealAgentCardAfterTab(event) {
  if(event.key!=='Tab'||event.altKey||event.ctrlKey||event.metaKey||event.defaultPrevented||$('taskDialog').open||$('settingsDialog').open)return;
  // Native Tab can reveal only a card's center in the horizontal narrow roster.
  // Reveal the actual current keyboard target; polls and delayed detail never
  // schedule this, and a newer focus/modal choice wins before the frame runs.
  window.requestAnimationFrame(()=>{
    if($('taskDialog').open||$('settingsDialog').open)return;
    const card=document.activeElement;
    if([...$('agentCards').querySelectorAll('[data-focus-key]')].includes(card))card.scrollIntoView({block:'nearest',inline:'nearest'});
  });
}
function questionEntries() {
  // Current runtime pauses, not unread messages or an inferred priority queue.
  const agents=new Map(ui.state.agents.map(agent=>[agent.id,agent]));
  return [...ui.state.runs].sort((a,b)=>(Number(a.created_at)||0)-(Number(b.created_at)||0)).flatMap(run=>{
    if(archivedRun(run)||['stopping','stopped'].includes(run.status))return [];
    const members=Array.isArray(run.agent_ids)?run.agent_ids.map(id=>agents.get(id)):ui.state.agents.filter(agent=>agent.run_id===run.id);
    return members.filter(agent=>agent&&agent.run_id===run.id&&agent.status==='waiting'&&
      typeof agent.question==='string'&&agent.question.trim()&&agent.status_reason==='human_input')
      .map(agent=>({run,agent}));
  });
}
function questionState(agent) {
  const value=agent?.question_state;
  if(!value||typeof value!=='object'||Array.isArray(value)||typeof value.question_id!=='string'||!/^q-[a-f0-9]{32}$/.test(value.question_id)||
    !['consultation','permission'].includes(value.kind)||typeof value.recommendation!=='string'||
    !Number.isFinite(value.asked_at)||value.asked_at<=0||
    !(value.deadline_at===null||(Number.isFinite(value.deadline_at)&&value.deadline_at>=value.asked_at))||
    !['pending','answered','fallback','blocked','cancelled'].includes(value.resolution)||
    !(value.resolved_at===null||Number.isFinite(value.resolved_at))||typeof value.reason!=='string')return null;
  return value;
}
function questionReplyTarget(agent) {
  if(!agent||!needsHuman(agent))return null;
  // Old archived/fixture schemas retain ordinary message semantics. A present,
  // invalid identity must never be silently treated as a fresh ordinary message.
  if(!Object.hasOwn(agent,'question_state'))return null;
  const state=questionState(agent);
  return state&&['pending','blocked'].includes(state.resolution)?state.question_id:undefined;
}
function questionTimingLabel(agent) {
  const state=questionState(agent);
  if(!state)return agent&&Object.hasOwn(agent,'question_state')?'質問の期限・推奨回答を確認できません。':'自動回答の期限は設定されていません。';
  if(state.resolution==='fallback')return `サーバーが推奨回答を適用しました: ${state.recommendation}`;
  if(state.resolution==='answered')return '回答を受け付けました。';
  if(state.resolution==='cancelled')return '質問は取り消されました。';
  if(state.resolution==='blocked')return '推奨回答の自動適用は停止しました。同じ質問への人の回答を待ちます。送信可否は作業の現在状態を確認してください。';
  if(state.kind==='permission')return '権限・承認の確認です。自動回答せず、人の回答を待ちます。';
  if(state.deadline_at===null||!state.recommendation.trim())return '自動回答は設定されていません。人の回答を待ちます。';
  const deadline=new Date(state.deadline_at*1000).toLocaleTimeString(),elapsed=Date.now()>=state.deadline_at*1000;
  return `推奨回答: ${state.recommendation}\n回答期限 ${deadline}（質問から約90秒）。未回答ならサーバーが推奨回答を使います。${elapsed?' 期限を過ぎました。サーバーの確定を確認中です。':''}ブラウザーを閉じてもサーバー側の期限は進みます。`;
}
function questionNotificationKey(run,agent,state) { return JSON.stringify([ui.instanceId,run.id,agent.id,state.question_id]); }
function closeQuestionNotifications() {
  for(const notification of ui.questionNotifications.values()){try{notification.close();}catch(_){}}
  ui.questionNotifications.clear();
}
function notificationCapability() {
  if(typeof globalThis.Notification!=='function'||window.isSecureContext===false)return 'unavailable';
  return ['default','granted','denied'].includes(Notification.permission)?Notification.permission:'unavailable';
}
async function requestQuestionNotificationPermission() {
  if(ui.notificationPermissionRequest||notificationCapability()!=='default')return;
  const action={};ui.notificationPermissionRequest=action;ui.notificationError='';renderQuestionNotice(questionEntries());
  try{await Notification.requestPermission();}
  catch(_){ui.notificationError='ブラウザー通知の許可を取得できませんでした。画面内の質問通知を確認してください。';}
  finally{if(ui.notificationPermissionRequest===action)ui.notificationPermissionRequest=null;renderQuestionNotice(questionEntries());}
}
async function openNotifiedQuestion(owner) {
  if(ui.instanceId!==owner.instance||!ui.authenticated||$('taskDialog').open||$('settingsDialog').open)return;
  const navigation=ui.navigationGeneration,workspace=ui.workspaceGeneration;
  await pollState(true);
  if(ui.instanceId!==owner.instance||ui.navigationGeneration!==navigation||ui.workspaceGeneration!==workspace||
    !ui.networkConnected||ui.detailError||$('taskDialog').open||$('settingsDialog').open)return;
  const entry=questionEntries().find(({run,agent})=>run.id===owner.run&&agent.id===owner.agent&&questionState(agent)?.question_id===owner.question&&questionState(agent)?.resolution==='pending');
  if(entry){window.focus?.();openQuestion(entry.agent.id);}
}
function syncQuestionNotifications(entries) {
  const pending=new Map();
  for(const {run,agent} of entries){const state=questionState(agent);if(state?.resolution==='pending')pending.set(questionNotificationKey(run,agent,state),{run,agent,state});}
  for(const [key,notification] of ui.questionNotifications){if(!pending.has(key)||!ui.networkConnected){try{notification.close();}catch(_){}ui.questionNotifications.delete(key);}}
  if(!ui.authenticated||!ui.networkConnected||ui.detailError||!ui.instanceId||notificationCapability()!=='granted')return;
  for(const [key,{run,agent,state}] of pending){
    if(ui.questionNotified.has(key))continue;
    // One attempt per question in this page session; never replay after failure.
    ui.questionNotified.add(key);
    try{
      const notification=new Notification('Workbench: 回答待ちの質問があります',{body:'アプリを開いて質問と回答期限を確認してください。',tag:key});
      ui.questionNotifications.set(key,notification);
      const owner={instance:ui.instanceId,run:run.id,agent:agent.id,question:state.question_id};
      notification.onclick=()=>{try{notification.close();}catch(_){}void openNotifiedQuestion(owner);};
      notification.onerror=()=>{ui.notificationError='ブラウザー通知を表示できませんでした。画面内の質問通知を確認してください。';renderQuestionNotice(questionEntries());};
    }catch(_){ui.notificationError='ブラウザー通知を表示できませんでした。画面内の質問通知を確認してください。';}
  }
}
function renderQuestionNotice(entries) {
  syncQuestionNotifications(entries);
  const capability=notificationCapability(),button=$('enableQuestionNotifications');
  button.disabled=capability!=='default'||Boolean(ui.notificationPermissionRequest);
  button.textContent=ui.notificationPermissionRequest?'通知の許可を確認中…':'ブラウザー通知を有効にする';
  const status=ui.notificationError||({unavailable:'この環境ではブラウザー通知を利用できません。画面内で確認してください。',denied:'ブラウザー通知は拒否されています。変更する場合はブラウザーの設定を確認してください。',granted:'ブラウザー通知は許可済みです。この画面を開いている間に通知します。OS側の表示は保証されません。',default:'ブラウザー通知は未許可です。ボタンを押したときだけ許可を確認します。'})[capability];
  if($('questionNotificationStatus').textContent!==status)$('questionNotificationStatus').textContent=status;
  const lostNoticeFocus=!entries.length&&document.activeElement===$('openQuestionNotice');
  $('questionNotice').hidden=!entries.length;
  if(lostNoticeFocus)$('needsYou').focus({preventScroll:true});
  const title=ui.networkConnected?`全チームで ${entries.length} 件の質問が回答待ちです`:`最後に取得した回答待ちの質問 ${entries.length} 件（接続未確認）`;
  if($('questionNoticeTitle').textContent!==title)$('questionNoticeTitle').textContent=title;
  const entry=entries[0],body=entry?`チーム ${shortRunId(entry.run)} · ${entry.agent.name||entry.agent.id}\n${questionTimingLabel(entry.agent)}`:'';
  if($('questionNoticeBody').textContent!==body)$('questionNoticeBody').textContent=body;
}
function staleQuestionDraft(agent) {
  return Boolean(agent&&hasMessageInput(agent)&&ui.draftQuestions.has(agent.id)&&ui.draftQuestions.get(agent.id)!==questionReplyTarget(agent));
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
  renderQuestionNotice(entries);
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
  revealInspector();
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
    filtered.map(({run,agent})=>[run.id,run.task,run.created_at,agent.id,agent.name,agent.parent_id,agent.profile_id,agent.configured_profile,agent.question,agent.question_state,agent.message_eligibility,hasMessageInput(agent)])]);
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
      const source=element('span','question-run'),sourceLine=element('span','question-run-line'),inputBadge=messageInputBadge(agent);
      sourceLine.append(element('span','question-run-id',`チーム ${shortRunId(run)}`));if(inputBadge)sourceLine.append(inputBadge);
      source.append(sourceLine,element('span','question-run-title',String(run.task||'作業').split('\n')[0]));
      card.append(source,
        element('span','agent-name',`${!agent.parent_id?'PM':'作業者'} · ${agent.name||agent.id}`),
        element('span','question-preview',agent.question.length>180?agent.question.slice(0,180)+'…':agent.question),
        element('span','question-timing',questionTimingLabel(agent)),
        element('span','question-availability',availability.label+(availability.message?' · '+availability.message:'')));
      const model=element('span','agent-model',profile?profileLabel(profile):'開始時の設定情報なし');
      model.title=configuredProfileLabel(agent)+'（応答モデル未確認）';card.append(model,element('span','question-open','質問と作業ログを開く'));
      card.addEventListener('click',()=>openQuestion(agent.id));$('agentCards').appendChild(card);
    }
  },fallback);
  if(focusedKey?.startsWith('question:')&&document.activeElement?.dataset.focusKey===focusedKey)
    document.activeElement.scrollIntoView({block:'nearest',inline:'nearest'});
}
function workBoardState(runId) {
  if(!ui.workBoards.has(runId))ui.workBoards.set(runId,{posts:new Map(),nodes:new Map(),cursor:0,lastSeq:0,loaded:false,loading:null,error:'',status:'',canPost:false,remaining:200,epoch:0,seenSeq:0,draft:{body:'',reply_to:null,revision:0},operation:null,view:{scroll:0,atBottom:true}});
  return ui.workBoards.get(runId);
}
function workBoardEnabled(run) { return run?.work_board?.enabled===true; }
function workBoardActive(run) { return Boolean(run&&!archivedRun(run)&&ACTIVE_STATUSES.has(run.status)&&run.status!=='stopping'); }
function saveWorkBoardDraft(event) {
  if(!ui.boardOwner)return;
  const draft=workBoardState(ui.boardOwner).draft,value=$('workBoardInput').value;
  if(draft.body!==value||event?.type==='input'){draft.body=value;draft.revision++;}
}
function rememberWorkBoardView() {
  if(ui.cockpitView!=='board'||!ui.boardOwner)return;
  const board=workBoardState(ui.boardOwner),feed=$('workBoardFeed');
  board.view.scroll=feed.scrollTop;board.view.atBottom=feed.scrollHeight-feed.clientHeight-feed.scrollTop<=40;
  if(board.view.atBottom&&board.loaded)board.seenSeq=Math.max(board.seenSeq,board.cursor);
}
function invalidateWorkBoardContent() {
  ui.networkPreviewReady=false;
  clearNetworkPreview();stopNetworkMotion();
  // Public history is re-read after a redaction change; old quotes must disappear too.
  for(const board of ui.workBoards.values()){
    board.epoch++;board.loading=null;board.posts.clear();board.nodes.clear();board.cursor=0;board.loaded=false;board.error='';board.canPost=false;
    if(board.operation)board.operation.hidePreview=true;
  }
  $('workBoardFeed').replaceChildren();$('workBoardReplyBody').textContent='';$('workBoardUncertainBody').textContent='';
  $('workBoardStatus').textContent='公開内容を更新しています。再取得できるまで以前の投稿・引用は表示しません。';
}
function hideWorkBoardAfterRedactionFailure() {
  invalidateWorkBoardContent();
  for(const board of ui.workBoards.values())board.error='秘密情報を安全に伏せた表示を取得できませんでした。以前の投稿・引用は表示しません。再取得してください。';
  if(currentRunBoard(ui.selectedRun))renderWorkBoard(getRun());
}
function workBoardPostValid(post,runId) {
  return post&&post.run_id===runId&&Number.isSafeInteger(post.seq)&&post.seq>=1&&post.seq<=200&&
    ['human','agent'].includes(post.author_kind)&&typeof post.author_name==='string'&&typeof post.body==='string'&&
    (post.author_kind==='human'?post.author_id===null:typeof post.author_id==='string')&&
    (post.reply_to===null||Number.isSafeInteger(post.reply_to)&&post.reply_to>0&&post.reply_to<post.seq)&&
    typeof post.created_at==='number'&&Number.isFinite(post.created_at);
}
function workBoardQuote(board,seq) {
  const parent=board.posts.get(seq);
  return parent?`${parent.author_name}: ${parent.body}`:`参照 #${seq}（本文はまだ取得できていません）`;
}
function createWorkBoardPost(post,runId) {
  const row=element('article',`board-post ${post.author_kind==='human'?'human':'agent'}`);
  row.tabIndex=-1;row.dataset.focusKey=`board:${runId}:${post.seq}`;
  const avatar=element('div','board-avatar',post.author_kind==='human'?'YOU':'A');avatar.setAttribute('aria-hidden','true');
  const content=element('div','board-post-content'),bubble=element('div','board-bubble'),header=element('div','board-author');
  const author=element('strong','',post.author_name),role=element('span',''),time=element('time','',localTime(post.created_at));
  header.append(author,role,time);
  const quote=element('button','board-quote');quote.type='button';quote.hidden=post.reply_to===null;
  quote.addEventListener('click',()=>{
    if(ui.boardOwner!==runId||ui.selectedRun!==runId)return;
    const target=workBoardState(runId).nodes.get(post.reply_to)?.row;
    if(target){target.scrollIntoView({block:'center',behavior:'auto'});target.focus({preventScroll:true});}
  });
  const body=element('p','board-body',post.body),footer=element('div','board-post-footer'),reply=element('button','button minor','返信');
  reply.type='button';reply.dataset.focusKey=`board-reply:${runId}:${post.seq}`;
  reply.addEventListener('click',()=>{
    const run=getRun(),board=workBoardState(runId);
    if(ui.boardOwner!==runId||run?.id!==runId||!workBoardActive(run)||!board.canPost)return;
    board.draft.reply_to=post.seq;board.draft.revision++;renderWorkBoardControls(run);$('workBoardInput').focus();
  });
  footer.append(element('span','',`#${post.seq}`),reply);bubble.append(quote,body);content.append(header,bubble,footer);row.append(avatar,content);
  return {row,quote,reply,role,avatar};
}
function renderWorkBoardUnread(run) {
  const board=run?workBoardState(run.id):null,last=Math.max(run?.work_board?.last_seq||0,board?.lastSeq||0);
  const count=workBoardEnabled(run)?Math.max(0,last-(board?.seenSeq||0)):0;
  $('workBoardBadge').hidden=count===0;$('workBoardBadge').textContent=count?`未表示 ${count}`:'';
  $('workBoardNew').hidden=!count||!board||board.view.atBottom||ui.cockpitView!=='board';
  $('workBoardNew').textContent=`新しい投稿 ${count}件 · 下へ`;
}
function renderWorkBoardControls(run) {
  if(!run||ui.boardOwner!==run.id)return;
  const board=workBoardState(run.id),enabled=workBoardEnabled(run),active=workBoardActive(run),draft=board.draft,operation=board.operation;
  const canPost=enabled&&active&&board.loaded&&board.canPost&&board.remaining>0;
  $('workBoardForm').hidden=!enabled||!active;
  $('workBoardInput').disabled=!enabled||!active;
  $('workBoardSend').disabled=!canPost||Boolean(operation)||ui.boardComposingRun===run.id||!draft.body.trim()||[...draft.body].length>2000;
  $('workBoardCharacters').textContent=`${[...draft.body].length} / 2000 文字`;
  $('workBoardReply').hidden=draft.reply_to===null||!enabled;
  $('workBoardReplyTitle').textContent=draft.reply_to===null?'':`投稿 #${draft.reply_to} への返信`;
  $('workBoardReplyBody').textContent=draft.reply_to===null?'':workBoardQuote(board,draft.reply_to);
  $('workBoardUncertain').hidden=archivedRun(run)||!enabled||!operation||operation.status!=='unknown';
  $('workBoardUncertainBody').textContent=operation?.status==='unknown'?(operation.hidePreview?'秘密情報の更新後のため、以前の送信本文は表示しません。確認時は元の投稿IDと本文をそのまま使用します。':operation.body):'';
  $('workBoardRetry').disabled=archivedRun(run)||!enabled||operation?.status!=='unknown';
  $('workBoardMode').textContent=archivedRun(run)?(enabled?'保存した掲示板を表示しています。閲覧専用のため投稿・返信・再送はできません。':'この保存履歴では掲示板がオフです。'):!enabled?'この作業では掲示板がオフです。設定で有効にして、新しい作業を開始してください。':!active?'この作業は終了しています。投稿は閲覧のみです。':board.loaded&&!board.canPost?'投稿上限に達しました。過去の投稿は閲覧できます。':'この作業の全員へ共有 · 投稿受付は、閲覧・理解・正式報告の証明ではありません。';
  $('workBoardReload').hidden=!enabled;$('workBoardReload').disabled=Boolean(board.loading);
  $('workBoardCount').textContent=enabled?`${board.posts.size} / ${Math.max(run.work_board.post_count||0,board.lastSeq)} 件取得 · 最大200件`:'';
  inlineStatus($('workBoardStatus'),board.error||board.status,Boolean(board.error));
  for(const node of board.nodes.values())node.reply.disabled=!canPost;
}
function renderWorkBoard(run) {
  const visible=Boolean(run&&ui.cockpitView==='board');$('workBoardPanel').hidden=!visible;
  if(!run){renderWorkBoardUnread(null);return;}
  const board=workBoardState(run.id),enabled=workBoardEnabled(run),feed=$('workBoardFeed');
  if(visible&&ui.boardOwner!==run.id){
    ui.boardOwner=run.id;ui.boardComposingRun=null;feed.replaceChildren();board.nodes.clear();$('workBoardInput').value=board.draft.body;
  }
  renderWorkBoardUnread(run);
  if(!visible)return;
  feed.hidden=!enabled;$('workBoardEmpty').hidden=!enabled||!board.loaded||board.posts.size>0;
  if(!enabled){feed.replaceChildren();board.nodes.clear();renderWorkBoardControls(run);return;}
  for(const post of [...board.posts.values()].sort((a,b)=>a.seq-b.seq)){
    let node=board.nodes.get(post.seq);
    if(!node){node=createWorkBoardPost(post,run.id);board.nodes.set(post.seq,node);feed.appendChild(node.row);}
    node.quote.textContent=post.reply_to===null?'':workBoardQuote(board,post.reply_to);
    node.quote.disabled=!board.posts.has(post.reply_to);
    const agent=ui.state.agents.find(agent=>agent.run_id===run.id&&agent.id===post.author_id);
    node.role.textContent=post.author_kind==='human'?'あなた':agent?`${agent.parent_id?'作業者':'PM'} · ${stateLabel(agent)}`:'担当者';
    node.avatar.textContent=post.author_kind==='human'?'YOU':agent&&!agent.parent_id?'PM':'W';
  }
  if(board.view.atBottom){feed.scrollTop=feed.scrollHeight;if(board.loaded)board.seenSeq=Math.max(board.seenSeq,board.cursor);}
  else feed.scrollTop=board.view.scroll;
  renderWorkBoardControls(run);renderWorkBoardUnread(run);
  if(!board.loading&&!board.error&&(!board.loaded||board.cursor<Math.max(run.work_board.last_seq||0,board.lastSeq)))void loadWorkBoard(run);
}
async function loadWorkBoard(run,force=false) {
  if(!workBoardEnabled(run)||run.id!==ui.selectedRun||ui.cockpitView!=='board'||ui.credentialOperations.size)return;
  const board=workBoardState(run.id);
  if(board.loading)return board.loading.promise;
  if(board.error&&!force)return;
  board.error='';
  const action={generation:ui.selectionGeneration,epoch:board.epoch,promise:null};board.loading=action;
  const current=()=>board.loading===action&&board.epoch===action.epoch&&ui.selectedRun===run.id&&ui.selectionGeneration===action.generation;
  action.promise=(async()=>{
    try{
      for(let page=0;page<201;page++){
        const cursor=board.cursor,response=await api(`/api/runs/${encodeURIComponent(run.id)}/work-board?after_seq=${cursor}&limit=50`);
        if(!current())return;
        if(acceptServerInstance(response))throw new Error('サーバーが再起動したため、保存履歴を読み直します。');
        if(!Number.isSafeInteger(response?.redaction_revision)||response.redaction_revision<0||ui.boardRedactionRevision!==null&&response.redaction_revision<ui.boardRedactionRevision)throw new Error('掲示板の秘密情報更新を確認できませんでした。');
        if(response.redaction_revision!==ui.boardRedactionRevision){
          invalidateWorkBoardContent();ui.boardRedactionRevision=response.redaction_revision;action.epoch=board.epoch;board.loading=action;
          if(cursor>0)continue; // Re-fetch the entire public feed, never mix masking revisions.
        }
        if(response?.enabled!==true||response.run_id!==run.id||!Array.isArray(response.posts)||response.posts.length>50||
          typeof response.has_more!=='boolean'||typeof response.can_post!=='boolean'||!Number.isSafeInteger(response.last_seq)||response.last_seq<cursor||response.last_seq>200||
          !Number.isSafeInteger(response.next_after_seq)||!Number.isSafeInteger(response.remaining_posts)||response.remaining_posts<0||response.remaining_posts>200)throw new Error('掲示板の取得応答を確認できませんでした。');
        let next=cursor;
        for(const post of response.posts){if(!workBoardPostValid(post,run.id)||post.seq!==next+1)throw new Error('投稿の順番を確認できませんでした。');next=post.seq;}
        if(response.next_after_seq!==next||next>response.last_seq||response.has_more!==(next<response.last_seq)||response.has_more&&next===cursor)throw new Error('掲示板の続きの位置を確認できませんでした。');
        for(const post of response.posts)board.posts.set(post.seq,post);
        board.cursor=next;board.lastSeq=Math.max(board.lastSeq,response.last_seq);board.canPost=response.can_post;board.remaining=response.remaining_posts;board.loaded=true;
        renderWorkBoard(run);
        if(!response.has_more)return;
      }
      throw new Error('掲示板の取得上限に達しました。');
    }catch(error){if(current()){if(error.code==='redaction_capacity')hideWorkBoardAfterRedactionFailure();else board.error=errorText(error);}}
    finally{if(board.loading===action){board.loading=null;if(currentRunBoard(run.id))renderWorkBoard(getRun());}}
  })();
  renderWorkBoardControls(run);return action.promise;
}
function currentRunBoard(runId) { return ui.selectedRun===runId&&ui.boardOwner===runId&&ui.cockpitView==='board'; }
async function submitWorkBoardPost(retry=false) {
  const run=getRun();if(!run||archivedRun(run)||ui.boardOwner!==run.id||!workBoardEnabled(run))return;
  const board=workBoardState(run.id);saveWorkBoardDraft();
  let action=board.operation;
  if(retry){if(action?.status!=='unknown')return;}
  else{
    if(action||!workBoardActive(run)||!board.loaded||!board.canPost||board.remaining<=0||ui.boardComposingRun===run.id||!board.draft.body.trim()||[...board.draft.body].length>2000)return;
    action={id:crypto.randomUUID(),body:board.draft.body,reply_to:board.draft.reply_to,revision:board.draft.revision,status:'pending',hidePreview:false};board.operation=action;
  }
  action.status='pending';board.error='';board.status=retry?'前回の投稿の受付結果を確認しています…':'投稿を送信しています…';renderWorkBoardControls(run);
  const epoch=board.epoch,instance=ui.instanceId,body={body:action.body,client_post_id:action.id};if(action.reply_to!==null)body.reply_to=action.reply_to;
  try{
    const response=await api(`/api/runs/${encodeURIComponent(run.id)}/work-board`,{method:'POST',body});
    if(response?.ok!==true||typeof response.duplicate!=='boolean'||!workBoardPostValid(response.post,run.id)||response.post.author_kind!=='human'){
      const error=new Error('投稿の受付応答を確認できませんでした。');error.outcomeUnknown=true;throw error;
    }
    if(instance!==ui.instanceId||ui.workBoards.get(run.id)!==board||board.operation!==action)return;
    board.lastSeq=Math.max(board.lastSeq,response.post.seq);
    // A concurrent redaction change invalidates this body; the next GET supplies freshly masked text.
    board.status=`投稿 #${response.post.seq} ${response.duplicate?'の受付を確認しました':'を受け付けました'}。閲覧・理解は未確認です。`;
    if(board.epoch!==epoch)board.status+=' 公開本文を再取得します。';
    if(board.draft.revision===action.revision&&board.draft.body===action.body&&board.draft.reply_to===action.reply_to&&ui.boardComposingRun!==run.id){
      board.draft={body:'',reply_to:null,revision:board.draft.revision+1};if(ui.boardOwner===run.id)$('workBoardInput').value='';
    }
    board.operation=null;
  }catch(error){
    if(instance!==ui.instanceId||ui.workBoards.get(run.id)!==board||board.operation!==action)return;
    if(error.outcomeUnknown||error.code==='redaction_capacity'){action.status='unknown';board.status='送信結果は未確認です。自動再送信はしません。';}
    else{board.operation=null;board.status='投稿は確認できませんでした。下書きは保持しています。';}
    board.error=board.epoch===epoch?errorText(error):'公開内容の更新中に投稿結果を取得できませんでした。';
    if(error.code==='redaction_capacity')hideWorkBoardAfterRedactionFailure();
  }finally{if(instance===ui.instanceId&&ui.workBoards.get(run.id)===board&&currentRunBoard(run.id)){renderWorkBoard(getRun());if(!board.operation)void loadWorkBoard(getRun(),true);}}
}
function setCockpitView(view) {
  if(!['network','board','inspector'].includes(view))return;
  rememberWorkBoardView();
  ui.cockpitView=view;document.querySelector('.app-shell').dataset.cockpitView=view;
  for(const [id,mode] of [['networkView','network'],['boardView','board'],['inspectorView','inspector']])$(id).setAttribute('aria-pressed',String(view===mode));
  if(view!=='network'){clearNetworkHover();stopNetworkMotion();}
  renderWorkBoard(getRun());renderNetworkPreview();paintNetworkMotionState();
}
function revealInspector() { if(window.matchMedia?.('(max-width: 1100px)').matches)setCockpitView('inspector'); }
function svgElement(tag,attributes={}) {
  const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [key,value] of Object.entries(attributes))node.setAttribute(key,String(value));
  return node;
}
function retainedTeamEvents(run) {
  if(!run||(ui.compactState&&ui.loadedEventsRun!==run.id))return [];
  return ui.state.events.filter(event=>event.run_id===run.id).slice(-100);
}
function networkLayout(agents) {
  const ids=new Set(agents.map(agent=>agent.id)),placed=new Map();let top=32;
  const roots=agents.filter(agent=>!agent.parent_id||!ids.has(agent.parent_id));
  for(const root of [...roots,...agents]) {
    if(placed.has(root.id))continue;
    placed.set(root.id,{x:304,y:top});let row=0;const descendants=[];
    // Parent identity, not a model-written role label, defines the hierarchy.
    const pending=agents.filter(agent=>agent.parent_id===root.id);
    while(pending.length) {
      const agent=pending.shift();if(placed.has(agent.id))continue;
      placed.set(agent.id,{x:92+(row%3)*212,y:top+176+Math.floor(row/3)*164});row++;descendants.push(agent.id);
      pending.push(...agents.filter(child=>child.parent_id===agent.id&&!placed.has(child.id)));
    }
    // Deterministic balanced rows; no physics or model-written hierarchy.
    const lastRowCount=row%3,offset=(3-lastRowCount)*212/2;
    if(lastRowCount)for(const id of descendants.slice(-lastRowCount))placed.get(id).x+=offset;
    top+=176+Math.ceil(row/3)*164+40;
  }
  return {positions:placed,width:720,height:Math.max(360,top)};
}
function currentMailLinks(agents,events) {
  const ids=new Set(agents.map(agent=>agent.id)),pairs=new Map();
  for(const event of events) {
    if(!['mail','mail_consumed'].includes(event.kind)||!ids.has(event.from_agent_id)||!ids.has(event.to_agent_id)||event.from_agent_id===event.to_agent_id)continue;
    const key=JSON.stringify([event.from_agent_id,event.to_agent_id]);
    const stage=networkMailStage(event),previous=pairs.get(key);
    pairs.delete(key);pairs.set(key,{from:event.from_agent_id,to:event.to_agent_id,stage,
      queued:(previous?.queued||0)+(stage==='queued'?1:0),consumed:(previous?.consumed||0)+(stage==='consumed'?1:0)});
  }
  return [...pairs.values()].slice(-12);
}
function selectMailPair(from,to) {
  ui.activityPair={from,to};ui.activityFilter='pair';setCockpitView('network');renderActivity(getRun());$('activityTitle').focus({preventScroll:true});
}
function networkMailPath(from,to,index) {
  return networkLinkGeometry(from,to,index).path;
}
function networkNodeCenter(point) { return {x:point.x+NETWORK_NODE_RADIUS,y:point.y+NETWORK_NODE_RADIUS}; }
function networkLinkGeometry(from,to,index=0,parent=false) {
  const a=networkNodeCenter(from),b=networkNodeCenter(to),dx=b.x-a.x,dy=b.y-a.y,length=Math.hypot(dx,dy)||1;
  // Reciprocal directions bend to opposite sides; endpoints follow circle tangents.
  const bend=parent?0:Math.min(120,48+length*.14+(index%3)*8),nx=-dy/length,ny=dx/length;
  const control1={x:a.x+dx/3+nx*bend,y:a.y+dy/3+ny*bend},control2={x:a.x+dx*2/3+nx*bend,y:a.y+dy*2/3+ny*bend};
  const clip=(center,toward)=>{const vx=toward.x-center.x,vy=toward.y-center.y,scale=NETWORK_NODE_RADIUS/(Math.hypot(vx,vy)||1);return {x:center.x+vx*scale,y:center.y+vy*scale};};
  const start=clip(a,control1),end=clip(b,control2);
  return {start,end,control1,control2,path:`M ${start.x} ${start.y} C ${control1.x} ${control1.y}, ${control2.x} ${control2.y}, ${end.x} ${end.y}`};
}
function networkViewState(runId=ui.selectedRun) {
  const view=ui.networkViews.get(runId)||{positions:new Map(),camera:null,selectedAgent:null,pinnedAgent:null,mailSeen:new Set(),mailCursor:-1,mailReady:false};
  ui.networkViews.delete(runId);ui.networkViews.set(runId,view);
  // Only IDs, geometry and bounded event identities; never cache public text.
  while(ui.networkViews.size>64)ui.networkViews.delete(ui.networkViews.keys().next().value);
  return view;
}
function networkPreviewAgent() {
  if(!ui.networkPreviewReady||!ui.selectedRun||ui.cockpitView!=='network'||document.hidden||$('settingsDialog')?.open||$('taskDialog')?.open)return null;
  const id=networkViewState().pinnedAgent||ui.networkFocusAgent||ui.networkHoverAgent;
  return ui.state.agents.find(agent=>agent.id===id&&agent.run_id===ui.selectedRun)||null;
}
function cancelNetworkPreviewDismiss() { clearTimeout(ui.networkPreviewDismissTimer);ui.networkPreviewDismissTimer=null; }
function scheduleNetworkPreviewDismiss(relatedTarget=null) {
  cancelNetworkPreviewDismiss();
  if($('networkPreview')?.contains(relatedTarget)||relatedTarget?.closest?.('.network-node'))return;
  const runId=ui.selectedRun;
  ui.networkPreviewDismissTimer=setTimeout(()=>{
    ui.networkPreviewDismissTimer=null;
    if(runId!==ui.selectedRun||ui.networkPreviewHovered||$('networkPreview')?.contains(document.activeElement)||document.activeElement?.closest?.('.network-node'))return;
    ui.networkHoverAgent=null;ui.networkFocusAgent=null;renderNetworkPreview();
  },NETWORK_PREVIEW_DISMISS_MS);
}
function clearNetworkHover() { cancelNetworkPreviewDismiss();ui.networkPreviewHovered=false;ui.networkHoverAgent=null;ui.networkFocusAgent=null;renderNetworkPreview(); }
function clearNetworkPreview() {
  cancelNetworkPreviewDismiss();ui.networkPreviewHovered=false;ui.networkHoverAgent=null;ui.networkFocusAgent=null;
  for(const view of ui.networkViews.values())view.pinnedAgent=null;
  renderNetworkPreview();
}
function toggleNetworkPin(id) {
  cancelNetworkPreviewDismiss();
  if(!ui.state.agents.some(agent=>agent.id===id&&agent.run_id===ui.selectedRun))return;
  const view=networkViewState();view.pinnedAgent=view.pinnedAgent===id?null:id;
  if(!view.pinnedAgent){ui.networkHoverAgent=null;ui.networkFocusAgent=null;}
  renderNetworkPreview();
}
function closeNetworkPreview() {
  const id=networkPreviewAgent()?.id||(ui.selectedRun?networkViewState().pinnedAgent:null);
  if(ui.selectedRun)networkViewState().pinnedAgent=null;
  clearNetworkHover();
  if(id)ui.networkNodes.get(id)?.button.focus({preventScroll:true});
  // Restoring keyboard focus must not reopen the dismissed preview.
  ui.networkFocusAgent=null;renderNetworkPreview();
}
function renderNetworkPreview() {
  const panel=$('networkPreview');if(!panel)return;
  const agent=networkPreviewAgent(),pinned=ui.selectedRun?networkViewState().pinnedAgent:null;
  for(const [id,node] of ui.networkNodes){node.button.classList.toggle('pinned',id===pinned);node.button.setAttribute('aria-pressed',String(id===pinned));node.button.setAttribute('aria-expanded',String(id===agent?.id));}
  panel.hidden=!agent;
  if($('networkPreviewMonitor'))$('networkPreviewMonitor').textContent=agentMonitorText(agent);
  if(!agent){for(const id of ['networkPreviewTitle','networkPreviewState','networkPreviewRole','networkPreviewAssignment','networkPreviewLatest','networkPreviewCounts','networkPreviewError','networkPreviewMode'])$(id).textContent='';$('networkPreviewError').hidden=true;return;}
  const activity=agent.activity||{},latest=activity.latest_log,count=value=>Number.isSafeInteger(value)&&value>=0?String(value):'未取得';
  $('networkPreviewTitle').textContent=agent.name||agent.id;
  $('networkPreviewState').textContent=stateLabel(agent);
  $('networkPreviewRole').textContent=`${agent.parent_id?'WORKER':'PM'}${agent.role?` · ${agent.role}`:''}${archivedAgent(agent)?' · 保存履歴':''}`;
  $('networkPreviewAssignment').textContent=agent.assignment||'担当内容は未記録';
  $('networkPreviewLatest').textContent=latest?`${localTime(latest.at)} · ${String(latest.text||'')}`:'最新ログは未取得';
  $('networkPreviewCounts').textContent=`待機入力 ${count(activity.pending_count)} · 結果 ${count(activity.result_count)} · 保存記録 ${count(activity.output_receipt_count)}`;
  $('networkPreviewError').textContent=agent.last_error||'';$('networkPreviewError').hidden=!agent.last_error;
  $('networkPreviewMode').textContent=pinned===agent.id?'詳細を固定中 · 解除は閉じる / Escape':'一時表示 · ノードをクリック / Enter で固定';
}
function networkMailStage(event) {
  if(event.kind==='mail'&&event.delivery_state==='queued')return 'queued';
  if(event.kind==='mail_consumed'&&event.delivery_state==='context_consumed')return 'consumed';
  return 'unknown';
}
function networkDeliveryLabel(stage) { return stage==='queued'?'送信キューに受理':stage==='consumed'?'会話へ取り込み済み':'配送状態は未記録'; }
function networkMotionAllowed(run=getRun()) {
  return Boolean(run&&run.id===ui.selectedRun&&!archivedRun(run)&&['running','working','queued','waiting'].includes(run.status)
    &&ui.networkMotionEnabled&&ui.networkConnected&&ui.networkPreviewReady&&!ui.networkReducedMotion&&!document.hidden&&ui.cockpitView==='network'&&ui.networkCanvas
    &&!$('settingsDialog')?.open&&!$('taskDialog')?.open);
}
function finishNetworkPulse(id) {
  const pulse=ui.networkPulses.get(id);if(!pulse)return;
  clearTimeout(pulse.timer);pulse.node.remove();ui.networkPulses.delete(id);
}
function stopNetworkMotion({rebase=true}={}) {
  for(const id of [...ui.networkPulses.keys()])finishNetworkPulse(id);
  for(const node of ui.networkNodes.values())node.button.classList.remove('is-live');
  if(rebase&&ui.selectedRun&&ui.networkViews.has(ui.selectedRun))ui.networkViews.get(ui.selectedRun).mailReady=false;
}
function paintNetworkMotionState() {
  const allowed=networkMotionAllowed();
  if(!allowed)stopNetworkMotion();
  for(const [id,node] of ui.networkNodes){const agent=ui.state.agents.find(item=>item.id===id&&item.run_id===ui.selectedRun);node.button.classList.toggle('is-live',allowed&&!archivedAgent(agent)&&['working','running'].includes(agent?.status));}
  const button=$('networkMotion');if(button){button.setAttribute('aria-pressed',String(ui.networkMotionEnabled));button.textContent=ui.networkMotionEnabled?'動きを停止':'動きを表示';button.title=ui.networkReducedMotion?'端末の「動きを減らす」設定により静止表示です':'新しく確認できた通信記録だけを短く表示します';}
}
function paintNetworkPulse(pulse) {
  const positions=ui.networkLayout?.positions,from=positions?.get(pulse.from),to=positions?.get(pulse.to);if(!from||!to)return;
  if(pulse.stage==='queued')pulse.motion.setAttribute('path',networkMailPath(from,to,pulse.index));
  else {const center=networkNodeCenter(to);pulse.node.setAttribute('cx',center.x);pulse.node.setAttribute('cy',center.y);}
}
function startNetworkMailPulse(event) {
  if(!networkMotionAllowed()||!ui.networkPulseLayer)return;
  const index=ui.networkMailLines.findIndex(link=>link.from===event.from_agent_id&&link.to===event.to_agent_id);if(index<0)return;
  while(ui.networkPulses.size>=NETWORK_PULSE_LIMIT)finishNetworkPulse(ui.networkPulses.keys().next().value);
  const stage=networkMailStage(event),id=++ui.networkPulseSequence;
  const node=svgElement('circle',{r:stage==='queued'?4:NETWORK_NODE_RADIUS+5,class:`network-mail-pulse ${stage}`,'aria-hidden':'true'});
  node.dataset.stage=stage;node.dataset.eventId=String(event.id);
  // New nodes join an already-running SVG timeline: start once explicitly,
  // never at implicit document time zero (whose end event can remove them).
  const motion=stage==='queued'?svgElement('animateMotion',{begin:'indefinite',dur:`${NETWORK_PULSE_MS}ms`,repeatCount:1,fill:'remove'}):svgElement('animate',{begin:'indefinite',attributeName:'r',values:`${NETWORK_NODE_RADIUS+3};${NETWORK_NODE_RADIUS+17}`,dur:`${NETWORK_PULSE_MS}ms`,repeatCount:1,fill:'remove'});
  const pulse={node,motion,stage,from:event.from_agent_id,to:event.to_agent_id,index,runId:ui.selectedRun,timer:null};
  paintNetworkPulse(pulse);node.appendChild(motion);ui.networkPulseLayer.appendChild(node);ui.networkPulses.set(id,pulse);
  motion.addEventListener('endEvent',()=>finishNetworkPulse(id),{once:true});
  pulse.timer=setTimeout(()=>finishNetworkPulse(id),NETWORK_PULSE_MS+100);
  motion.beginElement?.();
}
function observeNetworkMail(agents,events) {
  const run=getRun();if(!run||!ui.selectedRun)return;
  const view=networkViewState(),loaded=!ui.compactState||ui.loadedEventsRun===run.id;
  if(!loaded){view.mailReady=false;stopNetworkMotion();return;}
  const allowed=networkMotionAllowed(),previous=view.mailCursor,animate=allowed&&view.mailReady,ids=new Set(agents.map(agent=>agent.id)),fresh=[];
  for(const event of events){
    if(event.run_id!==run.id||!Number.isSafeInteger(event.id)||event.id<0)continue;
    view.mailCursor=Math.max(view.mailCursor,event.id);
    const stage=networkMailStage(event);
    if(event.run_id!==run.id||stage==='unknown'||typeof event.mail_id!=='string'||!event.mail_id||event.mail_id.length>256
      ||!ids.has(event.from_agent_id)||!ids.has(event.to_agent_id)||event.from_agent_id===event.to_agent_id)continue;
    const key=JSON.stringify([event.id,event.mail_id,stage]);
    if(animate&&event.id>previous&&!view.mailSeen.has(key))fresh.push(event);
    view.mailSeen.delete(key);view.mailSeen.add(key);
    while(view.mailSeen.size>NETWORK_MAIL_SEEN_LIMIT)view.mailSeen.delete(view.mailSeen.values().next().value);
  }
  view.mailReady=allowed;
  if(!allowed)stopNetworkMotion();
  else for(const event of fresh.slice(-NETWORK_PULSE_LIMIT))startNetworkMailPulse(event);
  paintNetworkMotionState();
}
function networkViewport() {
  const map=$('teamMap');return {width:map.clientWidth||840,height:map.clientHeight||390};
}
function pruneNetworkViews() {
  for(const [id,view] of ui.networkViews){
    if(!ui.state.runs.some(run=>run.id===id)){ui.networkViews.delete(id);continue;}
    const ids=new Set(ui.state.agents.filter(agent=>agent.run_id===id).map(agent=>agent.id));
    for(const agentId of view.positions.keys())if(!ids.has(agentId))view.positions.delete(agentId);
    if(view.selectedAgent&&!ids.has(view.selectedAgent))view.selectedAgent=null;
    if(view.pinnedAgent&&!ids.has(view.pinnedAgent))view.pinnedAgent=null;
  }
  const ids=new Set(ui.state.agents.filter(agent=>agent.run_id===ui.selectedRun).map(agent=>agent.id));
  if((ui.networkHoverAgent&&!ids.has(ui.networkHoverAgent))||(ui.networkFocusAgent&&!ids.has(ui.networkFocusAgent)))cancelNetworkPreviewDismiss();
  if(!ids.has(ui.networkHoverAgent))ui.networkHoverAgent=null;
  if(!ids.has(ui.networkFocusAgent))ui.networkFocusAgent=null;
  for(const [id,pulse] of ui.networkPulses)if(!ids.has(pulse.from)||!ids.has(pulse.to))finishNetworkPulse(id);
}
function networkBounds() {
  const points=[...(ui.networkLayout?.positions.values()||[])];
  if(!points.length)return {x:0,y:0,width:840,height:390};
  const x=Math.min(...points.map(p=>p.x))-24,y=Math.min(...points.map(p=>p.y))-32;
  return {x,y,width:Math.max(...points.map(p=>p.x+NETWORK_NODE_SIZE+32))-x,height:Math.max(...points.map(p=>p.y+NETWORK_NODE_SIZE+32))-y};
}
function paintNetworkCamera() {
  if(!ui.networkCanvas||!ui.selectedRun)return;
  const camera=networkViewState().camera;if(!camera)return;
  ui.networkCanvas.style.transform=`translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`;
  $('networkZoomValue').textContent=`${Math.round(camera.scale*100)}%`;
  $('networkZoomOut').disabled=camera.scale<=.01;$('networkZoomIn').disabled=camera.scale>=2;
}
function fitNetwork() {
  if(!ui.networkLayout||!ui.selectedRun)return;
  const bounds=networkBounds(),viewport=networkViewport(),scale=Math.min(1,Math.max(.01,Math.min(viewport.width/bounds.width,viewport.height/bounds.height)));
  networkViewState().camera={scale,x:(viewport.width-bounds.width*scale)/2-bounds.x*scale,y:(viewport.height-bounds.height*scale)/2-bounds.y*scale};
  paintNetworkCamera();
}
function zoomNetwork(factor,anchor) {
  if(!Number.isFinite(factor)||factor<=0||!ui.networkCanvas)return;
  const view=networkViewState();if(!view.camera)fitNetwork();
  const camera=view.camera,viewport=networkViewport(),point=anchor||{x:viewport.width/2,y:viewport.height/2};
  const scale=Math.min(2,Math.max(.01,camera.scale*factor)),ratio=scale/camera.scale;
  view.camera={scale,x:point.x-(point.x-camera.x)*ratio,y:point.y-(point.y-camera.y)*ratio};paintNetworkCamera();
}
function panNetwork(dx,dy) {
  if(!ui.networkCanvas||!Number.isFinite(dx)||!Number.isFinite(dy))return;
  const view=networkViewState();if(!view.camera)fitNetwork();
  view.camera.x+=dx;view.camera.y+=dy;paintNetworkCamera();
}
function repaintNetworkGeometry() {
  const positions=ui.networkLayout?.positions;if(!positions)return;
  for(const [id,node] of ui.networkNodes){const point=positions.get(id);node.button.style.left=`${point.x}px`;node.button.style.top=`${point.y}px`;}
  for(const {line,id,parentId} of ui.networkParentLines)line.setAttribute('d',networkLinkGeometry(positions.get(parentId),positions.get(id),0,true).path);
  for(const {line,track,from,to,index} of ui.networkMailLines){const path=networkMailPath(positions.get(from),positions.get(to),index);line.setAttribute('d',path);track.setAttribute('d',path);}
  for(const pulse of ui.networkPulses.values())paintNetworkPulse(pulse);
}
function moveNetworkNode(id,x,y) {
  const point=ui.networkLayout?.positions.get(id);if(!point||!Number.isFinite(x)||!Number.isFinite(y))return;
  // Local view coordinates only; no task, assignment, status or server mutation.
  point.x=Math.max(0,Math.min(10000,x));point.y=Math.max(32,Math.min(10000,y));
  networkViewState().positions.set(id,{...point});repaintNetworkGeometry();
}
function resetNetworkLayout() {
  if(!ui.networkCanvas)return;
  const agents=ui.state.agents.filter(agent=>agent.run_id===ui.selectedRun),layout=networkLayout(agents),view=networkViewState();
  view.positions=new Map([...layout.positions].map(([id,point])=>[id,{...point}]));ui.networkLayout.positions=view.positions;
  repaintNetworkGeometry();fitNetwork();
}
function startNetworkGesture(event,nodeId=null) {
  if(!ui.networkCanvas||event.isPrimary===false||(event.button!=null&&event.button!==0)||ui.networkGesture)return;
  if(!nodeId&&event.target?.closest?.('.network-node,.network-mail-line'))return;
  const camera=networkViewState().camera,point=nodeId?ui.networkLayout.positions.get(nodeId):camera;if(!point)return;
  ui.networkSuppressClick=null;
  clearNetworkHover();
  const capture=nodeId?ui.networkNodes.get(nodeId).button:$('teamMap');
  ui.networkGesture={runId:ui.selectedRun,pointerId:event.pointerId,nodeId,startX:event.clientX,startY:event.clientY,origin:{x:point.x,y:point.y},scale:camera.scale,moved:false,capture};
  capture.setPointerCapture?.(event.pointerId);event.stopPropagation?.();
}
function updateNetworkGesture(event) {
  const gesture=ui.networkGesture;if(!gesture||gesture.runId!==ui.selectedRun||gesture.pointerId!==event.pointerId)return;
  const dx=event.clientX-gesture.startX,dy=event.clientY-gesture.startY;
  if(!gesture.moved&&Math.hypot(dx,dy)<5)return;
  gesture.moved=true;event.preventDefault?.();
  if(gesture.nodeId)moveNetworkNode(gesture.nodeId,gesture.origin.x+dx/gesture.scale,gesture.origin.y+dy/gesture.scale);
  else {const camera=networkViewState().camera;camera.x=gesture.origin.x+dx;camera.y=gesture.origin.y+dy;paintNetworkCamera();}
  $('teamMap').classList.add('is-dragging');
}
function endNetworkGesture(event,cancel=false) {
  const gesture=ui.networkGesture;if(!gesture||gesture.pointerId!==event.pointerId)return;
  ui.networkGesture=null;$('teamMap').classList.remove('is-dragging');
  if(gesture.runId===ui.selectedRun&&gesture.moved){
    if(cancel){if(gesture.nodeId)moveNetworkNode(gesture.nodeId,gesture.origin.x,gesture.origin.y);else Object.assign(networkViewState().camera,gesture.origin);paintNetworkCamera();}
    ui.networkSuppressClick=gesture.nodeId;
  }
  if(gesture.capture.hasPointerCapture?.(event.pointerId))gesture.capture.releasePointerCapture(event.pointerId);
}
function networkNodeClick(event={},id) {
  if(event.detail!==0&&ui.networkSuppressClick===id){ui.networkSuppressClick=null;event.preventDefault?.();return;}
  ui.networkSuppressClick=null;toggleNetworkPin(id);
}
function networkNodeKey(event,id) {
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation?.();closeNetworkPreview();return;}
  if(event.key==='F2'&&networkPreviewAgent()?.id===id){event.preventDefault();event.stopPropagation?.();cancelNetworkPreviewDismiss();$('networkPreviewOpen').focus({preventScroll:true});return;}
  if(!event.altKey||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
  event.preventDefault();event.stopPropagation?.();const point=ui.networkLayout.positions.get(id),step=event.shiftKey?40:10;
  moveNetworkNode(id,point.x+(event.key==='ArrowRight'?step:event.key==='ArrowLeft'?-step:0),point.y+(event.key==='ArrowDown'?step:event.key==='ArrowUp'?-step:0));
}
function networkKey(event) {
  if(event.key==='Escape'){event.preventDefault();closeNetworkPreview();return;}
  if(event.target!==$('teamMap'))return;
  if(['+','=','-','Home','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))event.preventDefault();
  if(['+','='].includes(event.key))zoomNetwork(1.2);else if(event.key==='-')zoomNetwork(1/1.2);else if(event.key==='Home')fitNetwork();
  else if(event.key.startsWith('Arrow'))panNetwork(event.key==='ArrowRight'?-40:event.key==='ArrowLeft'?40:0,event.key==='ArrowDown'?-40:event.key==='ArrowUp'?40:0);
}
function initializeNetworkControls() {
  const map=$('teamMap');
  map.addEventListener('pointerdown',event=>startNetworkGesture(event));map.addEventListener('pointermove',updateNetworkGesture);
  map.addEventListener('pointerup',event=>endNetworkGesture(event));map.addEventListener('pointercancel',event=>endNetworkGesture(event,true));
  map.addEventListener('lostpointercapture',event=>endNetworkGesture(event,true));map.addEventListener('keydown',networkKey);
  map.addEventListener('wheel',event=>{if(!ui.networkCanvas)return;event.preventDefault();if(event.ctrlKey||event.metaKey){const rect=map.getBoundingClientRect();zoomNetwork(Math.exp(-Math.max(-100,Math.min(100,event.deltaY))*.005),{x:event.clientX-rect.left,y:event.clientY-rect.top});}else panNetwork(-event.deltaX,-event.deltaY);},{passive:false});
  $('networkZoomIn').addEventListener('click',()=>zoomNetwork(1.2));$('networkZoomOut').addEventListener('click',()=>zoomNetwork(1/1.2));
  $('networkFit').addEventListener('click',fitNetwork);$('networkReset').addEventListener('click',resetNetworkLayout);
  $('networkPreviewClose').addEventListener('click',closeNetworkPreview);
  $('networkPreviewOpen').addEventListener('click',()=>{const agent=networkPreviewAgent();if(agent)selectAgent(agent.id);});
  $('networkPreview').addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();closeNetworkPreview();}});
  $('networkPreview').addEventListener('pointerenter',()=>{ui.networkPreviewHovered=true;cancelNetworkPreviewDismiss();});
  $('networkPreview').addEventListener('pointerleave',event=>{ui.networkPreviewHovered=false;scheduleNetworkPreviewDismiss(event.relatedTarget);});
  $('networkPreview').addEventListener('focusin',cancelNetworkPreviewDismiss);
  $('networkPreview').addEventListener('focusout',event=>scheduleNetworkPreviewDismiss(event.relatedTarget));
  $('networkMotion').addEventListener('click',()=>{ui.networkMotionEnabled=!ui.networkMotionEnabled;stopNetworkMotion();paintNetworkMotionState();});
  const preference=window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const updateMotionPreference=()=>{ui.networkReducedMotion=preference?.matches===true;stopNetworkMotion();paintNetworkMotionState();};
  updateMotionPreference();preference?.addEventListener?.('change',updateMotionPreference);
  document.addEventListener('visibilitychange',()=>{clearNetworkHover();stopNetworkMotion();paintNetworkMotionState();});
}
function renderTeamMap(agents) {
  pruneNetworkViews();
  const map=$('teamMap'),layoutKey=JSON.stringify([ui.selectedRun,agents.map(agent=>[agent.id,agent.parent_id])]);
  $('teamMapMeta').textContent=`${agents.length} AGENTS`;
  const counts=[['作業中',agents.filter(a=>!archivedAgent(a)&&['working','running'].includes(a.status)).length],['待機',agents.filter(a=>!archivedAgent(a)&&['queued','waiting','idle'].includes(a.status)&&!needsHuman(a)).length],['要回答',agents.filter(needsHuman).length]];
  $('networkCounts').textContent=archivedRun(getRun())?'保存時点の担当と通信 · 現在は実行していません':counts.map(([label,count])=>`${label} ${count}`).join('  /  ');
  if(layoutKey!==ui.networkLayoutKey) {
    stopNetworkMotion();ui.networkLayoutKey=layoutKey;ui.networkMailKey='';ui.networkNodes=new Map();ui.networkGesture=null;ui.networkParentLines=[];ui.networkMailLines=[];map.classList.remove('is-dragging');map.replaceChildren();
    if(!agents.length){map.appendChild(element('p','network-empty','チームを開始すると、担当と連絡がここに並びます。'));ui.networkSvg=null;ui.networkCanvas=null;ui.networkPulseLayer=null;renderNetworkPreview();return;}
    const layout=networkLayout(agents),canvas=element('div','network-canvas');ui.networkLayout=layout;
    const view=networkViewState();for(const id of view.positions.keys())if(!layout.positions.has(id))view.positions.delete(id);
    for(const [id,point] of layout.positions)if(view.positions.has(id))layout.positions.set(id,{...view.positions.get(id)});else view.positions.set(id,{...point});
    if(view.selectedAgent&&!layout.positions.has(view.selectedAgent))view.selectedAgent=null;
    ui.networkCanvas=canvas;
    canvas.style.width=`${layout.width}px`;canvas.style.height=`${layout.height}px`;
    const svg=svgElement('svg',{viewBox:`0 0 ${layout.width} ${layout.height}`,width:layout.width,height:layout.height,role:'group','aria-label':'親子関係とメールの方向',class:'network-lines'});
    const defs=svgElement('defs'),marker=svgElement('marker',{id:'mailArrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'});
    marker.appendChild(svgElement('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'currentColor'}));defs.appendChild(marker);svg.appendChild(defs);
    for(const agent of agents) {
      const here=layout.positions.get(agent.id),parent=layout.positions.get(agent.parent_id);
      if(parent){const line=svgElement('path',{d:networkLinkGeometry(parent,here,0,true).path,class:'network-parent-line','aria-hidden':'true'});svg.appendChild(line);ui.networkParentLines.push({line,id:agent.id,parentId:agent.parent_id});}
    }
    ui.networkSvg=svgElement('g',{class:'network-mail-lines'});svg.appendChild(ui.networkSvg);ui.networkPulseLayer=svgElement('g',{class:'network-mail-pulses','aria-hidden':'true'});svg.appendChild(ui.networkPulseLayer);canvas.appendChild(svg);
    for(const agent of agents) {
      const place=layout.positions.get(agent.id),button=element('button','network-node');button.type='button';button.dataset.agentId=agent.id;button.dataset.networkRole=agent.parent_id?'worker':'pm';button.dataset.focusKey=`map:${agent.id}`;
      button.style.left=`${place.x}px`;button.style.top=`${place.y}px`;
      const inner=element('span','network-orb-inner'),monogram=element('span','network-monogram'),role=element('span','network-role',agent.parent_id?'WORKER':'PM'),name=element('strong','network-name'),state=element('span','network-state');
      inner.append(monogram,role);button.append(inner,name,state);button.addEventListener('click',event=>networkNodeClick(event,agent.id));button.addEventListener('pointerdown',event=>startNetworkGesture(event,agent.id));button.addEventListener('keydown',event=>networkNodeKey(event,agent.id));
      button.addEventListener('pointerenter',()=>{cancelNetworkPreviewDismiss();if(!ui.networkGesture){ui.networkHoverAgent=agent.id;renderNetworkPreview();}});
      button.addEventListener('pointerleave',event=>scheduleNetworkPreviewDismiss(event.relatedTarget));
      button.addEventListener('focus',()=>{cancelNetworkPreviewDismiss();ui.networkFocusAgent=agent.id;renderNetworkPreview();});
      button.addEventListener('blur',event=>scheduleNetworkPreviewDismiss(event.relatedTarget));
      button.setAttribute('aria-controls','networkPreview');button.setAttribute('aria-describedby','networkInteractionHelp');canvas.appendChild(button);
      ui.networkNodes.set(agent.id,{button,name,state,monogram});
    }
    map.appendChild(canvas);
    if(!view.camera)fitNetwork();else paintNetworkCamera();
  }
  let workerOrdinal=0;
  for(const agent of agents) {
    const monogram=agent.parent_id?`W${++workerOrdinal}`:'PM';
    const node=ui.networkNodes.get(agent.id);if(!node)continue;
    const displayed=displayStatus(agent),status=Object.hasOwn(STATUS_LABELS,displayed)?displayed:'unknown';
    node.button.className=`network-node ${status}${needsHuman(agent)?' human-input':''}${agent.id===ui.selectedAgent?' selected':''}`;
    node.button.setAttribute('aria-label',`${agent.name||agent.id} · ${stateLabel(agent)} · クリックまたは Enter で詳細を固定`);
    node.name.textContent=agent.name||agent.id;node.state.textContent=stateLabel(agent);
    node.monogram.textContent=monogram;
  }
  const links=currentMailLinks(agents,retainedTeamEvents(getRun())),mailKey=JSON.stringify(links);
  if(ui.networkSvg&&mailKey!==ui.networkMailKey) {
    ui.networkMailKey=mailKey;ui.networkMailLines=[];ui.networkSvg.replaceChildren();
    links.forEach((link,index)=>{const from=ui.networkLayout.positions.get(link.from),to=ui.networkLayout.positions.get(link.to);
      const path=networkMailPath(from,to,index);
      // One continuous screen-space hit target; visual dashes are decorative.
      const line=svgElement('path',{d:path,class:`network-mail-line ${link.stage}`,role:'button',tabindex:0,'aria-label':`${agents.find(a=>a.id===link.from)?.name||link.from} → ${agents.find(a=>a.id===link.to)?.name||link.to} · ${networkDeliveryLabel(link.stage)} · 理解や完了の確認ではありません · 通信を見る`});
      const track=svgElement('path',{d:path,class:`network-mail-track ${link.stage}`,'marker-end':'url(#mailArrow)','aria-hidden':'true'});
      line.dataset.deliveryStage=link.stage;
      line.dataset.focusKey=`mail-line:${JSON.stringify([link.from,link.to])}`;line.addEventListener('click',()=>selectMailPair(link.from,link.to));
      line.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();selectMailPair(link.from,link.to);}});ui.networkSvg.appendChild(line);ui.networkSvg.appendChild(track);ui.networkMailLines.push({line,track,from:link.from,to:link.to,index});
    });
  }
  $('networkMailMeta').textContent=`最新100イベント内 · 通信 ${links.length} 方向（最大12） · キュー受理と会話取込を区別（理解・完了ではありません）`;
  renderNetworkPreview();observeNetworkMail(agents,retainedTeamEvents(getRun()));
}
function renderAgentTabs(agents) {
  const signature=JSON.stringify([ui.selectedAgent,agents.map(agent=>[agent.id,agent.name,agent.role,agent.parent_id])]);if(signature===ui.tabsSignature)return;ui.tabsSignature=signature;
  const tabs=$('agentTabs');tabs.replaceChildren();
  agents.forEach(agent=>{const button=element('button','agent-tab'+(agent.id===ui.selectedAgent?' active':''),`${!agent.parent_id?'◉':'○'} ${agent.name||agent.id}`);button.type='button';button.dataset.focusKey=`tab:${agent.id}`;button.setAttribute('aria-pressed',String(agent.id===ui.selectedAgent));button.addEventListener('click',()=>selectAgent(agent.id));tabs.appendChild(button);});
}
function saveAgentDraft(event) {
  if(!ui.selectedAgent)return;
  const value=$('messageInput').value,previous=ui.drafts.get(ui.selectedAgent),hadInput=typeof previous==='string'&&previous.length>0;
  if(!value.length)ui.draftQuestions.delete(ui.selectedAgent);
  else if(!ui.draftQuestions.has(ui.selectedAgent))ui.draftQuestions.set(ui.selectedAgent,ui.composerQuestion);
  if(event?.type==='input'||ui.drafts.get(ui.selectedAgent)!==value)ui.draftRevisions.set(ui.selectedAgent,(ui.draftRevisions.get(ui.selectedAgent)||0)+1);
  ui.drafts.set(ui.selectedAgent,value);
  if(event?.type==='input'&&hadInput!==(value.length>0))renderMessageInputPresence();
  if(event?.type==='input')renderConversation(getAgent());
}
function rememberConversationView() {
  if(!ui.logContext)return;
  const container=$('conversationLog');
  ui.conversationViews.set(ui.logContext,{scroll:container.scrollTop,atBottom:container.scrollHeight-container.scrollTop-container.clientHeight<70,expanded:new Set([...container.querySelectorAll('details[open]')].map(node=>node.dataset.logId))});
}
function changeSelection(runId,id) {
  if(ui.selectedRun===runId&&ui.selectedAgent===id)return false;
  if(ui.selectedRun)networkViewState().selectedAgent=ui.selectedAgent;
  if(ui.selectedRun!==runId&&ui.activityFilter==='pair'){ui.activityFilter='all';ui.activityPair=null;}
  if(ui.selectedRun!==runId){clearNetworkHover();stopNetworkMotion();saveWorkBoardDraft();rememberWorkBoardView();}
  saveAgentDraft();rememberConversationView();ui.selectedRun=runId;ui.selectedAgent=id;
  ui.composerQuestion=questionReplyTarget(getAgent());
  if(runId)networkViewState(runId).selectedAgent=id;
  // An epoch, rather than an ID comparison, also rejects an old A response after A → B → A.
  ui.selectionGeneration++;ui.loadedDetail=null;ui.detailError=false;ui.logContext='';ui.logSignature='';ui.outputRequest++;
  if(ui.polling)ui.pollAgain=true;
  $('messageInput').value=ui.drafts.get(id)||'';inlineStatus($('messageStatus'),'');inlineStatus($('resultActionStatus'),'');
  return true;
}
function selectAgent(id) { if(!ui.state.agents.some(agent=>agent.id===id&&agent.run_id===ui.selectedRun))return;ui.navigationGeneration++;const changed=changeSelection(ui.selectedRun,id);revealInspector();renderRun();if(changed)void pollState(); }
function selectRun(id) { if(!ui.state.runs.some(run=>run.id===id))return;ui.navigationGeneration++;const agents=ui.state.agents.filter(agent=>agent.run_id===id),saved=networkViewState(id).selectedAgent,changed=changeSelection(id,agents.find(agent=>agent.id===saved)?.id||agents.find(agent=>!agent.parent_id)?.id||agents[0]?.id||null);inlineStatus($('messageStatus'),'');showView('work');setBriefOpen(false);renderState();if(changed)void pollState(); }

function renderRunList() {
  const counts=new Map();for(const {run} of questionEntries())counts.set(run.id,(counts.get(run.id)||0)+1);
  const inputs=new Map();for(const {run} of messageInputEntries())inputs.set(run.id,(inputs.get(run.id)||0)+1);
  const signature=JSON.stringify([ui.selectedRun,ui.state.runs.map(run=>[run.id,run.task,run.status,run.status_reason,run.archived,run.read_only,run.created_at,counts.get(run.id)||0,inputs.get(run.id)||0])]);if(signature===ui.runsSignature)return;ui.runsSignature=signature;
  const live=ui.state.runs.filter(run=>!archivedRun(run)).length,archived=ui.state.runs.length-live;
  $('runCount').textContent=`${live} / 20${archived?` · 保存 ${archived}`:''}`;$('runCount').setAttribute('aria-label',`この起動中の作業 ${live}件・上限20件、保存履歴 ${archived}件`);$('runList').replaceChildren();
  if(!ui.state.runs.length){$('runList').appendChild(element('p','sidebar-empty','ここにチームの作業が並びます'));return;}
  [...ui.state.runs].reverse().forEach(run=>{const button=element('button','run-link'+(run.id===ui.selectedRun?' selected':'')+(archivedRun(run)?' archived':''));button.type='button';button.dataset.focusKey=`run:${run.id}`;button.append(element('span','run-link-title',String(run.task||'作業').split('\n')[0]),element('span','run-link-meta',`${stateLabel(run)} · ${localTime(run.created_at)} · ${shortRunId(run)}${counts.get(run.id)?` · 質問 ${counts.get(run.id)}件`:''}${inputs.get(run.id)?` · 入力 ${inputs.get(run.id)}人`:''}`));button.addEventListener('click',()=>selectRun(run.id));$('runList').appendChild(button);});
}
const REASON_LABELS = {peer_message:'チーム連絡待ち',human_input:'回答待ち',teammates:'作業者待ち',teammate_error:'作業者エラー',delegation_incomplete:'委任手順が未完了',dependency_wait:'前工程の承認待ち',dependency_stale:'前工程変更・PM再依頼待ち',collaboration_limit:'連携上限',needs_attention:'要確認',error:'エラー'};
function stateLabel(item) { return archivedRun(item)||archivedAgent(item)?`保存履歴 · ${statusLabel(displayStatus(item))}`:REASON_LABELS[item?.status_reason]||statusLabel(item?.status); }
function badge(status,reason) { return element('span','status-badge '+(Object.hasOwn(STATUS_LABELS,status)?status:''),REASON_LABELS[reason]||statusLabel(status)); }
function renderAgents(agents) {
  const signature=JSON.stringify([ui.selectedAgent,ui.needsOnly,$('agentSearch').value,agents.map(agent=>[agent.id,agent.parent_id,agent.name,agent.profile_id,agent.configured_profile,agent.status,agent.status_reason,agent.archived,agent.read_only,agent.assignment,agent.question,agent.last_error,workerDependencyLabel(agent),hasMessageInput(agent)])]);if(signature===ui.rosterSignature)return;ui.rosterSignature=signature;
  $('agentCount').textContent=String(agents.length);$('agentCards').replaceChildren();$('rosterEmpty').hidden=filteredAgents(agents).length>0;$('rosterEmpty').textContent=agents.length?'条件に一致するエージェントはいません。':'チームを開始すると、ここに担当者が並びます。';
  filteredAgents(agents).forEach((agent,index)=>{
    const card=element('button','agent-card'+(agent.id===ui.selectedAgent?' selected':''));card.type='button';card.dataset.agentId=agent.id;card.dataset.focusKey=`agent:${agent.id}`;card.setAttribute('aria-pressed',String(agent.id===ui.selectedAgent));
    const top=element('div','agent-card-top'),stateLine=element('span','agent-state-line'),inputBadge=messageInputBadge(agent);
    stateLine.append(archivedAgent(agent)?element('span','status-badge archived',stateLabel(agent)):badge(agent.status,agent.status_reason));if(inputBadge)stateLine.append(inputBadge);
    top.append(element('span','agent-avatar',!agent.parent_id?'PM':`W${agents.filter(item=>item.parent_id).findIndex(item=>item.id===agent.id)+1}`),stateLine);
    const profile=configuredProfile(agent),model=element('span','agent-model',profile?profileLabel(profile):'開始時の設定情報なし');
    model.title=configuredProfileLabel(agent)+'（応答モデル未確認）';
    card.append(top,element('span','agent-name',agent.name||agent.id),model,element('span','agent-task',agent.assignment||agent.question||agent.last_error||(!agent.parent_id?'チームの作業を管理':'割り当てられた作業を担当')));
    const dependency=workerDependencyLabel(agent);if(dependency)card.appendChild(element('span','agent-dependencies',dependency));
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
function downloadSettingsJson(text,filename) {
  const blob=new Blob([text],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob);let link;
  try {link=element('a');link.href=url;link.download=filename;link.hidden=true;document.body.appendChild(link);link.click();}
  finally {link?.remove();window.setTimeout(()=>URL.revokeObjectURL(url),1000);}
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
function setVisibleText(node,text) { const value=String(text??'');if(node.textContent!==value)node.textContent=value; }
function renderInspector(agent) {
  if($('inspectorMonitor'))$('inspectorMonitor').textContent=agentMonitorText(agent);
  const activity=agent?.activity,latest=activity?.latest_log;
  setVisibleText($('inspectorAssignment'),agent?.assignment||'担当内容は未記録です。');
  setVisibleText($('inspectorLatest'),latest?`${localTime(latest.at)} · ${latest.kind||'ログ'}\n${latest.text||''}`:'公開された最新ログはまだありません。');
  const count=value=>Number.isInteger(value)&&value>=0?value:'未取得';
  setVisibleText($('inspectorCounts'),`待機入力 ${count(activity?.pending_count)} · 報告 ${count(activity?.result_count)} · 保存 ${count(activity?.output_receipt_count)}`);
  $('inspectorError').hidden=!agent?.last_error;setVisibleText($('inspectorError'),agent?.last_error||'');
  $('inspectAgentMail').disabled=!agent;
}
function renderConversation(agent) {
  renderInspector(agent);
  renderResults(agent);
  const available=Boolean(agent),run=getRun();$('messageForm').hidden=!available;
  const loaded=agentDetailLoaded(agent),loading=available&&!loaded,detailStatus=$('detailStatus');
  detailStatus.hidden=!loading;
  const detailMessage=loading?(ui.detailError?'詳細を取得できませんでした。接続を確認しながら再試行しています。':'選択したエージェントのログと成果を読み込み中…'):'';
  if(detailStatus.textContent!==detailMessage)detailStatus.textContent=detailMessage;
  $('conversationLog').setAttribute('aria-busy',String(loading));$('resultsPanel').setAttribute('aria-busy',String(loading));
  $('conversationTitle').textContent=agent?(agent.name||agent.id):'作業ログ';
  $('conversationMeta').textContent=agent?`${!agent.parent_id?'PM':'作業者'} · ${agent.profile_id} · ${agent.turns||0} turns`:'';
  const memory=agent?.context_memory;
  $('contextMemoryStatus').hidden=!memory;
  $('contextMemoryStatus').textContent=memory?`${memory.compacting&&!archivedAgent(agent)?'会話を要約中 · ':''}文脈圧縮 ${memory.compactions} 回${memory.fallback_compactions>0?`（うち自動抜粋 ${memory.fallback_compactions} 回・AIによる要約ではありません。内容の一部を省略）`:''} · 元の履歴 ${memory.history_records} 件（上限で除外 ${memory.history_omitted} 件）· モデル用の会話文脈は今回の起動中のみ。要約には情報が抜けることがあります。`:'';
  const projection=memory?.ordered_projection;
  if(projection?.mode==='ordered_bounded_projection')$('contextMemoryStatus').textContent+=` 手順用表示 ${projection.raw_message_count} → ${projection.projected_message_count} 件（省略 ${projection.omitted_message_count}、結果の短縮 ${projection.trimmed_message_count}）。AI要約ではなく送信時の抜粋です。原履歴にも保持上限があります。`;
  $('conversationProfile').textContent=agent?configuredProfileLabel(agent)+'（応答モデル未確認）':'';
  $('conversationStatus').hidden=!agent;
  if(agent){$('conversationStatus').className='status-badge '+(archivedAgent(agent)?'archived':Object.hasOwn(STATUS_LABELS,agent.status)?agent.status:'');$('conversationStatus').textContent=stateLabel(agent);}
  const archived=archivedRun(run)||archivedAgent(agent),question=agent&&(archived||needsHuman(agent))?agent.question||'':'';
  const questionLostFocus=!question&&document.activeElement===$('humanQuestion');
  const questionContext=JSON.stringify([ui.selectedRun,agent?.id,question,questionState(agent)?.question_id]);
  $('humanQuestion').hidden=!question;
  if(ui.questionContext!==questionContext){ui.questionContext=questionContext;$('humanQuestion').textContent=question?`${archived?'保存時点の質問（回答不可）':'判断が必要です'}\n${question}`:'';$('humanQuestion').scrollTop=0;}
  if(questionLostFocus)$('conversationHeading').focus({preventScroll:true});
  // Preserve the identity of existing nonempty text before showing a new question.
  if(agent&&$('messageInput').value&&!ui.draftQuestions.has(agent.id))ui.draftQuestions.set(agent.id,ui.composerQuestion);
  ui.composerQuestion=questionReplyTarget(agent);
  const timing=question||agent?.question_state?questionTimingLabel(agent):'';
  $('questionTiming').hidden=!timing;$('questionTiming').textContent=(archived&&timing?'保存時点: ':'')+timing;
  $('messageLabel').textContent=question?'質問への回答':'追加の指示';$('messageInput').placeholder=question?'選択肢や条件を確認し、回答を入力してください':'このエージェントへ追加の指示を送る';
  const stopping=['stopping','stopped'].includes(run?.status),eligibility=agent?.message_eligibility;
  const blocked=archived||stopping||eligibility?.allowed!==true;
  const staleDraft=staleQuestionDraft(agent),unknownQuestion=ui.composerQuestion===undefined;
  $('sendMessage').disabled=!agent||ui.busyMessage||blocked||staleDraft||unknownQuestion;$('messageInput').disabled=!agent||blocked;
  $('messageEligibility').textContent=staleDraft?'入力を始めた質問は終了または変更されました。下書きは保持しています。現在の質問や追加指示へ送る場合は、内容を確認して入力欄を空にしてから入力し直してください。':unknownQuestion?'質問の識別情報を確認できないため回答できません。最新の状態を取得してください。':archived?'保存履歴は閲覧専用です。追加指示・回答・メール送信はできません。新しい作業の下書きに依頼文を使えます。':eligibility?.message||(stopping?'停止したチームは再開できません。新しい仕事を開始してください':agent&&eligibility?.allowed!==true?'送信できる状態か確認できません。最新の状態を取得してから確認してください。':'');
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
function focusHumanRecipient(id) {
  if(archivedRun(getRun())||!ui.state.agents.some(agent=>agent.id===id&&agent.run_id===ui.selectedRun&&!archivedAgent(agent)))return;
  selectAgent(id);setCockpitView('inspector');($('messageInput').disabled?$('conversationHeading'):$('messageInput')).focus({preventScroll:true});
}
// Only the reserved application event is evidence. Model prose, mail and old
// review events never gain authority by containing a similar JSON object.
function referenceAuditPayload(event,run) {
  const identity=value=>typeof value==='string'&&value.trim().length>0&&value.length<=80&&!value.includes('\0')&&!value.includes('[redacted]');
  if(!run||!identity(run.id)||!identity(event.run_id)||!identity(event.agent_id)||event.kind!=='reference_audit'||event.run_id!==run.id||!Number.isSafeInteger(event.id)||event.id<1||
    !Array.isArray(run.pm_agent_ids)||run.pm_agent_ids.length!==1||!identity(run.pm_agent_ids[0])||event.agent_id!==run.pm_agent_ids[0]||
    typeof event.text!=='string'||event.text.length>32000)return null;
  const exact=(value,keys)=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));
  const integer=(value,min,max)=>Number.isSafeInteger(value)&&value>=min&&value<=max;
  const text=(value,max)=>typeof value==='string'&&value.trim().length>0&&[...value].length<=max&&!value.includes('\0')&&!value.includes('[redacted]');
  const hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
  let audit;try{audit=JSON.parse(event.text);}catch{return null;}
  const report=audit?.scope==='worker_report',keys=['schema_version','source','scope','workflow_id','generation','decision','facts','comment','semantic_scope'];
  if(report)keys.push('worker_id','result_revision');
  if(!exact(audit,keys)||audit.schema_version!==1||audit.source!=='application'||!['step','worker_report'].includes(audit.scope)||
    audit.decision!=='accept'||audit.semantic_scope!=='reference_match_only'||!text(audit.workflow_id,80)||!integer(audit.generation,1,257)||
    !exact(audit.comment,['text','verified'])||audit.comment.verified!==false||typeof audit.comment.text!=='string'||
    [...audit.comment.text].length>(report?4000:512)||!Array.isArray(audit.facts)||audit.facts.length<1||audit.facts.length>(report?64:1))return null;
  if(report&&(!text(audit.worker_id,80)||audit.worker_id===event.agent_id||!Array.isArray(run.agent_ids)||!run.agent_ids.includes(audit.worker_id)||!integer(audit.result_revision,1,Number.MAX_SAFE_INTEGER)))return null;
  let previous=0,participant=null;
  for(const fact of audit.facts) {
    if(!exact(fact,['step','participant_key','submission_generation','predecessor','expected_head','value','meaning','reference'])||
      !integer(fact.step,1,64)||fact.step<=previous||!text(fact.participant_key,24)||!integer(fact.submission_generation,1,audit.generation)||
      !text(fact.expected_head,1)||!text(fact.value,128)||!text(fact.meaning,512)||
      !exact(fact.predecessor,['kind','step','value'])||!text(fact.predecessor.value,128)||
      fact.predecessor.kind!==(fact.step===1?'seed':'accepted_step')||fact.predecessor.step!==fact.step-1||
      !exact(fact.reference,['entry_id','entry_sha256','catalog_sha256','semantic_scope'])||
      typeof fact.reference.entry_id!=='string'||!/^[A-Za-z0-9_-]{1,40}$/.test(fact.reference.entry_id)||
      !hash(fact.reference.entry_sha256)||!hash(fact.reference.catalog_sha256)||fact.reference.semantic_scope!=='reference_match_only')return null;
    if(report&&participant!==null&&fact.participant_key!==participant)return null;
    previous=fact.step;participant=fact.participant_key;
  }
  return audit;
}
function appendReferenceAudit(content,event,run) {
  const legacy=['ordered_reviewed','worker_report_review'].includes(event.kind);
  if(event.kind!=='reference_audit'&&!legacy)return false;
  const audit=legacy?null:referenceAuditPayload(event,run);
  if(!audit) {
    content.append(element('p','audit-unverified',legacy?'過去のPMコメント／構造化照合記録なし':'構造化照合を確認できない記録（未検証）'),element('div','activity-body',event.text||''));
    return true;
  }
  const section=element('section','reference-audit');
  section.append(element('p','reference-audit-label','固定参照との構造化照合'),
    element('p','reference-audit-scope',`${archivedRun(run)?'保存時点':'記録時点'}の参照資料との一致です。一般辞書の正しさ・PMの意味理解・現在の承認や完了は確認しません。`),
    element('p','reference-audit-meta',`${audit.scope==='step'?'候補の監査':`正式報告の監査 · 担当ID ${audit.worker_id} · 報告版 ${audit.result_revision}`} · 世代 ${audit.generation} · 手順ID ${audit.workflow_id}`));
  const facts=element('ol','reference-audit-facts');facts.tabIndex=0;facts.dataset.focusKey=`reference-audit:${JSON.stringify([run.id,event.id])}`;
  facts.dataset.auditScrollKey=facts.dataset.focusKey;facts.setAttribute('aria-label','固定参照との照合記録。手番ごとの事実。');
  for(const fact of audit.facts) {
    const row=element('li','reference-audit-fact');
    row.append(element('p','reference-audit-step',`第${fact.step}手 · 担当 ${fact.participant_key} · 提出世代 ${fact.submission_generation}`),
      element('p','',`前の語（${fact.predecessor.kind==='seed'?'開始語':`第${fact.predecessor.step}手`}）：${fact.predecessor.value}`),
      element('p','',`必要な先頭文字：${fact.expected_head} → 実値：${fact.value}`),element('p','',`意味：${fact.meaning}`),
      element('p','reference-audit-source',`参照ID：${fact.reference.entry_id}\n項目 SHA-256：${fact.reference.entry_sha256}\n資料 SHA-256：${fact.reference.catalog_sha256}`));
    facts.appendChild(row);
  }
  section.appendChild(facts);
  const comment=element('section','reference-audit-comment');
  comment.append(element('p','audit-unverified','PMの判断・コメント（文章の正しさは未検証）'),element('div','activity-body',audit.comment.text||'コメントなし'));
  content.append(section,comment);return true;
}
function renderActivity(run) {
  const feed=$('activityFeed'),loading=Boolean(run)&&ui.compactState&&ui.loadedEventsRun!==run.id,retained=retainedTeamEvents(run),mail=event=>['mail','mail_consumed'].includes(event.kind);
  const events=retained.filter(event=>ui.activityFilter==='mail'?mail(event):ui.activityFilter==='selected'?mail(event)&&[event.from_agent_id,event.to_agent_id].includes(ui.selectedAgent):ui.activityFilter==='pair'?mail(event)&&((event.from_agent_id===ui.activityPair?.from&&event.to_agent_id===ui.activityPair?.to)||(event.from_agent_id===ui.activityPair?.to&&event.to_agent_id===ui.activityPair?.from)):true).reverse();
  const signature=JSON.stringify([run?.id,run?.archived,run?.read_only,run?.pm_agent_ids,run?.agent_ids,loading,ui.activityFilter,ui.activityPair,ui.selectedAgent,events]);if(signature===ui.activitySignature)return;ui.activitySignature=signature;
  for(const [id,filter] of [['activityAll','all'],['activityMail','mail'],['activitySelected','selected']])$(id).setAttribute('aria-pressed',String(ui.activityFilter===filter));
  setVisibleText($('activityScope'),`${ui.activityFilter==='pair'?'選択した二者の通信 · ':ui.activityFilter==='selected'?'選択担当の通信 · ':''}最新100イベント内 ${events.length} 件。保持範囲外の履歴は含みません。`);
  const scroll=ui.activityRun===run?.id?feed.scrollTop:0,auditScroll=new Map([...feed.querySelectorAll('[data-focus-key]')].filter(node=>node.dataset.auditScrollKey).map(node=>[node.dataset.auditScrollKey,node.scrollTop]));ui.activityRun=run?.id;feed.replaceChildren();feed.setAttribute('aria-busy',String(loading));
  if(loading){feed.appendChild(element('p','detail-loading','チームのメールと進捗を読み込み中…'));return;}
  if(!events.length){feed.appendChild(element('p','empty-small','この表示範囲に記録はありません。宛先IDのない過去のメールは「すべて」で確認できます。'));return;}
  events.forEach(event=>{const row=element('article','activity-item'),content=element('div');let title;
    if(mail(event))title=`${event.from||'エージェント'} → ${Array.isArray(event.to)?event.to.join(', '):event.to||'チーム'}`;
    else title=({spawn:'作業者が参加',question:'人への質問',error:'エラー',done:'作業完了',stopped:'作業を停止',tool:'ツール実行',collaboration_limit:'自動連携が上限に到達',reference_audit:'参照資料の監査記録',ordered_reviewed:'PMの監査記録',worker_report_review:'PMの監査記録'})[event.kind]||event.kind||'進捗';
    content.appendChild(element('div','activity-title',title));
    if(mail(event)) {
      const kind=({peer_message:'相互メール',worker_report:'作業者の報告',worker_notice:'作業者の通知',worker_error:'作業者のエラー通知'})[event.message_type]||'メール';
      const delivery=event.delivery_state==='context_consumed'?'会話へ取り込み済み':event.delivery_state==='queued'?'送信キューに受理（記録時点）':'配送状態は未記録';
      content.appendChild(element('p','mail-delivery',`${kind} · ${delivery}（理解・完了の確認ではありません）`));
      if(event.subject)content.appendChild(element('p','mail-subject',event.subject));
      const participants=element('div','mail-participants');
      for(const [label,id] of [['差出人',event.from_agent_id],['宛先',event.to_agent_id]]) {
        const agent=ui.state.agents.find(item=>item.id===id&&item.run_id===run?.id);if(!agent)continue;
        const button=element('button','button minor',`${label}: ${agent.name||agent.id}`);button.type='button';button.dataset.focusKey=`mail:${event.id}:${label}`;button.addEventListener('click',()=>selectAgent(id));participants.appendChild(button);
      }
      const sender=ui.state.agents.find(item=>item.id===event.from_agent_id&&item.run_id===run?.id);
      if(sender){const reply=element('button','button minor','差出人へ人の指示を入力');reply.type='button';reply.disabled=archivedRun(run)||archivedAgent(sender);reply.dataset.focusKey=`mail-reply:${event.id}`;reply.addEventListener('click',()=>focusHumanRecipient(sender.id));participants.appendChild(reply);}
      content.appendChild(participants);
    }
    if(!appendReferenceAudit(content,event,run))content.appendChild(element('div','activity-body',event.text||''));row.append(element('time','activity-time',localTime(event.at)),content);feed.appendChild(row);
  });
  for(const node of feed.querySelectorAll('[data-focus-key]'))if(node.dataset.auditScrollKey)node.scrollTop=auditScroll.get(node.dataset.auditScrollKey)||0;
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
function sharedBudgetCount(run,key,fallback) {
  const value=run.budget?.[key];
  if(run.budget?.shared!==true||!value||![value.used,value.limit,value.remaining].every(Number.isSafeInteger)||value.used!==fallback||value.used<0||value.limit<1||value.remaining!==Math.max(0,value.limit-value.used))return fallback;
  return `${value.used} / ${value.limit}（残り ${value.remaining}）`;
}
function sharedBudgetMetrics(run) {
  const budget=run.budget,rows=[];
  if(budget?.shared!==true)return rows;
  const duration=value=>{const seconds=Math.floor(value);return `${Math.floor(seconds/60)}分${seconds%60}秒`;};
  const time=budget.time;
  if(time&&[time.used_seconds,time.limit_seconds,time.remaining_seconds].every(value=>typeof value==='number'&&Number.isFinite(value)&&value>=0)&&time.limit_seconds>0&&Math.abs(time.remaining_seconds-Math.max(0,time.limit_seconds-time.used_seconds))<0.01){
    rows.push(['実行時間（チーム共有）',`${duration(time.used_seconds)} / ${duration(time.limit_seconds)}（残り ${duration(time.remaining_seconds)}）`]);
  }
  if(typeof budget.observed_at==='number'&&Number.isFinite(budget.observed_at)&&budget.observed_at>0){
    const observed=new Date(budget.observed_at*1000);
    if(Number.isFinite(observed.getTime()))rows.push([archivedRun(run)?'予算の保存時点':'予算の観測時点',observed.toLocaleTimeString('ja-JP',{hour12:false})]);
  }
  return rows;
}
function runtimeStopMetrics(run) {
  const labels={time_limit:'実行時間の上限',model_limit:'モデル呼び出し回数の上限',tool_limit:'ツール実行回数の上限',turn_limit:'担当のターン数上限',provider_timeout:'モデルAPIの応答待ちタイムアウト（自動再試行なし）'};
  const reasons=Array.isArray(run.stop_reasons)?run.stop_reasons:[run.stop_reason];
  const values=[...new Set(reasons.filter(reason=>typeof reason==='string'&&Object.hasOwn(labels,reason)))].map(reason=>labels[reason]);
  return values.length?[['担当の停止理由',values.join(' / ')]]:[];
}
// Monitoring reads application observations only. It never dispatches work or
// treats an animated line, elapsed time, or a model's prose as completion.
function observedSeconds(value) { return typeof value==='number'&&Number.isFinite(value)&&value>=0?`${Math.floor(value)}秒`:'未記録'; }
function providerObservationLabel(agent) {
  const p=agent?.provider_observation;if(!p||p.schema_version!==1)return '';
  const labels={started:'呼び出し開始（通信段階は未観測）',queue_wait:'Local 受付待ち（キュー・GPU確認を含む）',admitted:'受付完了',response_wait:'API応答待ち',received:'応答受信',parse:'応答を検査中',completed:'応答処理完了',error:'呼び出しエラー',cancelled:'呼び出し取消',retry_wait:'設定済み再試行の待機'};
  if(!Object.hasOwn(labels,p.phase))return '';
  const archived=archivedAgent(agent)||p.history_only===true,parts=[archived?'保存時点':ui.networkConnected?'観測時点':'接続未確認・最後の観測',p.purpose==='compaction'?'文脈要約':'作業',labels[p.phase]];
  if(p.phase==='queue_wait'&&p.admission_kind==='copilot')parts[parts.length-1]='Copilot 受付待ち';
  parts.push(`この段階 ${observedSeconds(p.phase_elapsed_seconds)}`);
  const limit=p.phase==='queue_wait'?p.queue_timeout_seconds:p.phase==='response_wait'?p.request_timeout_seconds:null;
  if(typeof limit==='number'&&Number.isFinite(limit)&&limit>0)parts.push(`上限 ${observedSeconds(limit)}`);
  if(Number.isSafeInteger(p.attempt)&&p.attempt>1)parts.push(`試行 ${p.attempt}`);
  if(['error','cancelled'].includes(p.phase)&&['queue_wait','response_wait'].includes(p.previous_phase))parts.push(`${p.previous_phase==='queue_wait'?'直前の受付待ち':'直前の応答待ち'} ${observedSeconds(p.previous_phase_elapsed_seconds)}`);
  if(typeof p.observed_at==='number'&&Number.isFinite(p.observed_at))parts.push(localTime(p.observed_at));
  return parts.join(' · ');
}
function coordinationAgentLabel(agent) {
  const c=agent?.coordination;if(!c||c.schema_version!==1)return '';
  const labels={human_input:'人の回答待ち',error:'エラーを確認',inbox_pending:'新着入力の取込待ち',pm_review:'PMの候補監査待ち',turn:'他の担当の手番',submit:'本人の候補提出待ち',report_review:'PMの正式報告監査待ち',completed:'手順完了'};
  const reason=c.dependency?.reason,parts=[];
  if(c.participant_key)parts.push(`担当 ${c.participant_key}`);
  if(Number.isSafeInteger(c.step))parts.push(`第${c.step}手`);
  if(reason&&Object.hasOwn(labels,reason))parts.push(labels[reason]);
  if(c.history_only===true)parts.unshift('保存時点');
  return parts.join(' · ');
}
function workerDependencyLabel(agent) {
  const value=agent?.worker_dependencies;if(value===undefined)return '';
  const record=item=>item!==null&&typeof item==='object'&&!Array.isArray(item);
  const id=item=>typeof item==='string'&&item.trim().length>0&&item.length<=80&&!item.includes('\u0000');
  const ids=items=>Array.isArray(items)&&items.length<=16&&items.every(id)&&new Set(items).size===items.length;
  const prefix=archivedAgent(agent)?'保存時点の依存関係':ui.networkConnected?'取得した依存関係':'最後に取得した依存関係';
  if(!record(value)||!ids(value.depends_on)||!value.depends_on.length||!ids(value.blocked_by)||
     value.blocked_by.some(ident=>!value.depends_on.includes(ident))||typeof value.stale!=='boolean'||
     !record(value.accepted_revisions)||Object.entries(value.accepted_revisions).some(([ident,revision])=>
       !value.depends_on.includes(ident)||!Number.isSafeInteger(revision)||revision<1))return `${prefix}: 詳細を確認できません。`;
  const name=ident=>{const peer=ui.state.agents.find(item=>item.run_id===agent.run_id&&item.id===ident);return `${peer?.name||'担当未取得'} [${ident}]`;};
  const parts=[`${prefix}: ${value.depends_on.map(name).join('、')}`];
  if(value.blocked_by.length)parts.push(`前工程の承認待ち: ${value.blocked_by.map(name).join('、')}`);
  if(value.stale)parts.push('前工程が変更されました。以前の成果は失効し、PMの明示的な再依頼が必要です。');
  const accepted=Object.entries(value.accepted_revisions);
  if(accepted.length)parts.push('使用した承認版: '+accepted.map(([ident,revision])=>`${name(ident)} / ${revision}`).join('、'));
  return parts.join('\n');
}
function agentMonitorText(agent) { return [coordinationAgentLabel(agent),workerDependencyLabel(agent),providerObservationLabel(agent)].filter(Boolean).join('\n'); }
function mailLifecycles(events,runId) {
  const rows=new Map();
  for(const event of events) {
    if(event.run_id!==runId||!['mail','mail_consumed'].includes(event.kind)||typeof event.mail_id!=='string'||!event.mail_id||typeof event.from_agent_id!=='string'||typeof event.to_agent_id!=='string')continue;
    const key=JSON.stringify([runId,event.mail_id,event.from_agent_id,event.to_agent_id]);
    const row=rows.get(key)||{key,from:event.from_agent_id,to:event.to_agent_id,queued:null,consumed:null,latest:0};
    const at=typeof event.at==='number'&&Number.isFinite(event.at)&&event.at>0?event.at:null;
    if(event.kind==='mail'&&event.delivery_state==='queued')row.queued=at;
    if(event.kind==='mail_consumed'&&event.delivery_state==='context_consumed')row.consumed=at;
    row.latest=Math.max(row.latest,at||0);rows.set(key,row);
  }
  return [...rows.values()].sort((a,b)=>b.latest-a.latest).slice(0,20);
}
function mailLifecycleLabel(row) {
  const from=row.queued===null?'送信記録は保持範囲外':`送信 ${localTime(row.queued)}`;
  const to=row.consumed===null?'取込はこの範囲で未確認':`取込 ${localTime(row.consumed)}`;
  const delay=row.queued!==null&&row.consumed!==null&&row.consumed>=row.queued?`（間隔 ${observedSeconds(row.consumed-row.queued)}）`:'';
  return `${from} → ${to}${delay}`;
}
function renderCoordinationMonitor(run,agents) {
  const panel=$('coordinationMonitor');if(!panel)return;panel.hidden=!run;if(!run)return;
  const c=run.coordination,rows=mailLifecycles(retainedTeamEvents(run),run.id);
  const signature=JSON.stringify([run.id,run.archived,ui.networkConnected,c,agents.map(a=>[a.id,a.name,a.coordination,a.worker_dependencies,a.provider_observation]),rows]);
  if(signature===ui.monitorSignature)return;ui.monitorSignature=signature;
  const content=$('coordinationContent');content.replaceChildren();
  const name=id=>agents.find(a=>a.id===id)?.name||id||'未記録';
  const source=archivedRun(run)||c?.history_only?'保存時点の記録':ui.networkConnected?'取得した状態':'接続未確認・最後に取得した状態';
  $('coordinationFreshness').textContent=source;
  if(c?.schema_version===1&&c.kind==='ordered_work') {
    const phase={ready:'候補提出待ち',pending_review:'PM監査待ち',complete:'全手を採用済み'}[c.phase]||'状態を確認';
    content.appendChild(element('p','coordination-phase',`${phase} · 採用 ${c.accepted_steps} / ${c.total_steps} 手${c.step!==null?` · 第${c.step}手`:''}`));
    if(c.current_actor_id)content.appendChild(element('p','small',`現在の担当: ${name(c.current_actor_id)}`));
    if(c.pending)content.appendChild(element('p','coordination-candidate',`監査対象: ${c.pending.value}\n${c.pending.summary}${c.pending.summary_truncated?'…（抜粋）':''}\n${c.pending.semantic_status==='reference_matched'?'固定参照に一致（一般的な意味の正しさを保証しません）':'意味はPMによる確認が必要です'}`));
    content.appendChild(element('p','small muted',`訂正 ${c.corrections?.revisions??0} · 巻き戻し ${c.corrections?.rollbacks??0} · PM完了 ${c.pm_completion?.completed===true?'受理済み':'未確認'}`));
    const reports=Array.isArray(c.reports)?c.reports:[];
    for(const report of reports.slice(0,16))content.appendChild(element('p','report-monitor',`${name(report.agent_id)} · 現在版 ${report.current_revision} · 正式報告 ${report.formal_revision??'なし'} · 配送 ${report.delivered_revision??'未確認'} · 取込 ${report.consumed_revision??'未確認'} · PM承認 ${report.accepted_current?'現在版を承認':'未完了'}`));
  } else content.appendChild(element('p','small muted','手順の順序は未設定です。担当の状態と通信の観測を表示します。'));
  const crew=element('div','monitor-crew');
  for(const agent of agents) {
    const text=agentMonitorText(agent);if(!text)continue;
    const card=element('button','monitor-agent');card.type='button';card.dataset.focusKey=`monitor-agent:${run.id}:${agent.id}`;
    card.append(element('strong','',agent.name||agent.id),element('span','',text));card.addEventListener('click',()=>selectAgent(agent.id));crew.appendChild(card);
  }
  content.appendChild(crew);
  const mail=$('mailLifecycleList');mail.replaceChildren();
  for(const row of rows) {
    const button=element('button','mail-lifecycle');button.type='button';button.dataset.focusKey=`lifecycle:${row.key}`;
    button.append(element('strong','',`${name(row.from)} → ${name(row.to)}`),element('span','',mailLifecycleLabel(row)));
    button.addEventListener('click',()=>selectMailPair(row.from,row.to));mail.appendChild(button);
  }
  if(!rows.length)mail.appendChild(element('p','small muted','この表示範囲に配送記録はありません。'));
}
function renderRunContent() {
  reconcileTaskReuse();syncTaskReuseControl();
  const run=getRun();renderArchiveNotice(run);$('workEmpty').hidden=Boolean(run);$('runOverview').hidden=!run;document.querySelector('.conversation-panel').hidden=!run;$('networkWorkspace').hidden=!run;renderWorkBoard(run);
  const agents=ui.state.agents.filter(agent=>agent.run_id===run?.id),questions=questionEntries();renderQuestionSummary(questions);renderMessageInputSummary();renderCoordinationMonitor(run,agents);
  $('rosterHeading').textContent=ui.needsOnly?'質問':'CREW';
  $('rosterScope').textContent=ui.needsOnly?'全チーム · チームの開始順。開くだけでは回答・再開しません。':run?`表示中のチーム · ${shortRunId(run)}`:'選択したチームの担当者';
  $('agentSearchLabel').textContent=ui.needsOnly?'全チームの質問・依頼・担当者を検索':'エージェントを検索';
  $('agentSearch').placeholder=ui.needsOnly?'質問・チームの依頼・担当者で検索':'エージェント・担当で検索';
  $('agentCards').classList.toggle('question-list',Boolean(ui.needsOnly));
  if(ui.needsOnly)renderQuestions(questions);else renderAgents(agents);
  if(!run){renderTeamMap(agents);renderAgentTabs(agents);renderConversation(null);renderActivity(null);return;}
  $('activeRunTitle').textContent=`表示中のチーム · ${shortRunId(run)}`;$('activeRunStatus').className='status-badge '+(archivedRun(run)?'archived':Object.hasOwn(STATUS_LABELS,run.status)?run.status:'');$('activeRunStatus').textContent=stateLabel(run);$('activeRunTask').textContent=run.task||'';
  const collaborationBlocked=!archivedRun(run)&&run.collaboration_limit_reached===true;
  $('collaborationLimitNotice').hidden=!collaborationBlocked;
  $('collaborationLimitNotice').textContent=collaborationBlocked?'自動連携が上限に達したため、新しい委任・メール・完了通知を停止しました。この連携上限だけでは、開始済み・待機中の作業は停止しません。停止したチームは再開できません。上限を変更して続ける場合は、作業の停止後に設定を保存し、新しい作業を開始してください。追加の指示や回答では回数はリセットされません。':'';
  $('stopRun').disabled=!canStopRun(run);
  const metricValues=[['自動連携',`${run.auto_collaborations??0} / ${run.max_auto_collaborations??24}`],[run.budget?.shared===true?'モデル呼び出し（チーム共有）':'モデル呼び出し',sharedBudgetCount(run,'model_calls',run.model_calls||0)],[run.budget?.shared===true?'ツール実行（チーム共有）':'ツール実行',sharedBudgetCount(run,'tool_calls',run.tool_calls||0)],...sharedBudgetMetrics(run),...runtimeStopMetrics(run),['作業者の上限',run.max_workers||0],['PMの分担方針',delegationLabel(run.delegation_level)],['PMごとの委任人数',Number.isInteger(run.workers_per_pm)?`${run.workers_per_pm} 人${run.delegation_level===0?'（未使用）':''}`:'未記録']],metricSignature=JSON.stringify([run.id,metricValues]);
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
  acceptServerInstance(state);
  const compact=Object.hasOwn(state,'selection'),selection=state.selection;
  // Legacy full-state fixtures remain supported; compact detail must name its exact request owner.
  if(compact&&(!selection||selection.run_id!==request.run||selection.agent_id!==request.agent||selection.detail_loaded!==Boolean(request.agent)))throw new Error('選択した詳細の応答を確認できませんでした。');
  const next={...state,runs:Array.isArray(state.runs)?state.runs:[],agents:Array.isArray(state.agents)?state.agents:[],events:Array.isArray(state.events)?state.events:[],resources:state.resources||{}};
  if(compact&&request.agent&&!next.agents.some(agent=>agent.run_id===request.run&&agent.id===request.agent&&['logs','results','output_receipts'].every(key=>Array.isArray(agent[key]))))throw new Error('選択した詳細の応答を確認できませんでした。');
  if(Number.isSafeInteger(state.redaction_revision)&&state.redaction_revision>=0){
    if(ui.boardRedactionRevision!==null&&state.redaction_revision<ui.boardRedactionRevision)throw new Error('公開内容の更新前の応答を受信しました。再取得します。');
    if(ui.boardRedactionRevision!==state.redaction_revision)invalidateWorkBoardContent();
    ui.boardRedactionRevision=state.redaction_revision;
  }
  ui.state=next;ui.compactState=compact;ui.detailError=false;ui.networkPreviewReady=true;acceptHistoryStorage(state);
  if(Object.hasOwn(state,'copilot_agent_status')){
    const changed=JSON.stringify(ui.copilotAgentStatus)!==JSON.stringify(state.copilot_agent_status);
    ui.copilotAgentStatus=state.copilot_agent_status;renderCopilotStatus();
    if(changed){ui.preflightKey='';schedulePreflight();}
  }
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
          if(error.code==='redaction_capacity')hideWorkBoardAfterRedactionFailure();
          setConnection(false,'接続を確認してください');ui.detailError=true;renderConversation(getAgent());if(!ui.authenticated)notice(errorText(error),true);
        }
        // Initial summary or a removed selection can choose the latest run/root during renderState.
        if(request.generation!==ui.selectionGeneration)ui.pollAgain=true;
      } while(ui.pollAgain&&ui.authenticated);
    } finally {ui.polling=false;}
  })();return ui.pollPromise;
}
async function initialize() {
  applyTaskOrchestrationDefaults();
  $('enableQuestionNotifications').addEventListener('click',requestQuestionNotificationPermission);
  $('openQuestionNotice').addEventListener('click',()=>{if($('taskDialog').open||$('settingsDialog').open)return;const entry=questionEntries()[0];if(entry)openQuestion(entry.agent.id);});
  renderQuestionNotice(questionEntries());
  initializeNetworkControls();
  $('networkView').addEventListener('click',()=>setCockpitView('network'));
  $('boardView').addEventListener('click',()=>setCockpitView('board'));
  $('workBoardForm').addEventListener('submit',event=>{event.preventDefault();void submitWorkBoardPost();});
  $('workBoardInput').addEventListener('input',event=>{saveWorkBoardDraft(event);renderWorkBoardControls(getRun());});
  $('workBoardInput').addEventListener('compositionstart',()=>{ui.boardComposingRun=ui.boardOwner;saveWorkBoardDraft({type:'input'});});
  $('workBoardInput').addEventListener('compositionend',()=>{saveWorkBoardDraft({type:'input'});ui.boardComposingRun=null;renderWorkBoardControls(getRun());});
  $('workBoardFeed').addEventListener('scroll',()=>{rememberWorkBoardView();renderWorkBoardUnread(getRun());});
  $('workBoardNew').addEventListener('click',()=>{const run=getRun();if(!run)return;const board=workBoardState(run.id);board.view.atBottom=true;$('workBoardFeed').scrollTop=$('workBoardFeed').scrollHeight;rememberWorkBoardView();renderWorkBoardUnread(run);});
  $('workBoardReload').addEventListener('click',()=>{const run=getRun();if(run)void loadWorkBoard(run,true);});
  $('workBoardCancelReply').addEventListener('click',()=>{const run=getRun();if(!run||ui.boardOwner!==run.id)return;const board=workBoardState(run.id);board.draft.reply_to=null;board.draft.revision++;renderWorkBoardControls(run);$('workBoardInput').focus();});
  $('workBoardRetry').addEventListener('click',()=>{const run=getRun();if(run)void submitWorkBoardPost(true);});
  $('inspectorView').addEventListener('click',()=>setCockpitView('inspector'));
  for(const [id,filter] of [['activityAll','all'],['activityMail','mail'],['activitySelected','selected']])$(id).addEventListener('click',()=>{ui.activityFilter=filter;renderActivity(getRun());});
  $('inspectAgentMail').addEventListener('click',()=>{ui.activityFilter='selected';setCockpitView('network');renderActivity(getRun());$('activityTitle').focus({preventScroll:true});});
  $('resultSelection').addEventListener('change',()=>{ui.outputSelections.set(outputOwner(),$('resultSelection').value);renderResults(getAgent());$('resultText').scrollTop=0;});
  $('copyResult').addEventListener('click',copySelectedOutput);$('exportResult').addEventListener('click',exportSelectedOutput);
  $('navWork').addEventListener('click',()=>showView('work'));$('navSettings').addEventListener('click',()=>showView('settings'));
  $('startRun').addEventListener('pointerdown',event=>{if(event.isPrimary)ui.startPointerActive=true;});
  window.addEventListener('pointerup',releaseStartPointer);
  window.addEventListener('pointercancel',releaseStartPointer);
  window.addEventListener('blur',releaseStartPointer);
  $('runForm').addEventListener('input',event=>{trackTaskDraft(event);syncStartControl();schedulePreflight();});
  $('runForm').addEventListener('change',event=>{trackTaskDraft(event);syncStartControl();schedulePreflight();});
  $('addPM').addEventListener('click',addPM);
  $('useOrchestrationDefaults').addEventListener('click',()=>{applyTaskOrchestrationDefaults();ui.taskOrchestrationInitialized=true;trackTaskDraft({type:'change'});syncStartControl();schedulePreflight();});
  $('taskDialog').addEventListener('close',()=>{ui.taskDialogGeneration++;clearTaskReuse();releaseStartPointer();ui.preflightKey='';ui.preflightRequest++;clearTimeout(ui.preflightTimer);});
  $('settingsDialog').addEventListener('close',()=>{ui.workspaceGeneration++;clearCredentialInputs();invalidateSkillsCatalog();if(ui.settingsSaving)inlineStatus($('settingsStatus'),'設定を送信しました。閉じても保存要求は取り消されません。必要なら応答後に保存済み設定を読み直してください。');for(const control of credentialControls())if(ui.credentialOperations.has(control.id)){control.status.textContent='キーの更新結果は未確認です。保存済み設定を読み直しても、キー設定の有無だけでは今回の更新を確認できません。';if(control.result!==control.status)inlineStatus(control.result,'');}invalidateDiagnostics();schedulePreflight();});
  $('reloadSkills').addEventListener('click',reloadSkills);
  $('discardSettings').addEventListener('click',discardSettings);
  $('reconnectCopilotAgent').addEventListener('click',reconnectCopilotAgent);
  $('preflightSettings').addEventListener('click',()=>{setBriefOpen(false);showView('settings');});
  $('toggleBrief').addEventListener('click',()=>setBriefOpen(false));
  $('reuseTask').addEventListener('click',beginTaskReuse);
  $('replaceTaskDraft').addEventListener('click',replaceTaskDraft);
  $('keepTaskDraft').addEventListener('click',keepTaskDraft);
  $('taskReusePreview').addEventListener('keydown',scrollTaskReusePreview);
  for(const id of ['newRun','launchTask','emptyNewRun'])$(id).addEventListener('click',()=>setBriefOpen(true));
  $('emptySettings').addEventListener('click',()=>showView('settings'));
  $('closeSettings').addEventListener('click',()=>showView('work'));
  $('agentSearch').addEventListener('input',()=>renderRun());
  $('needsYou').addEventListener('click',toggleQuestionView);
  $('nextMessageInput').addEventListener('click',openNextMessageInput);
  document.addEventListener('keydown',revealAgentCardAfterTab);
  for(const id of ['taskDialog','settingsDialog']) { const dialog=$(id);dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();}); }
  window.addEventListener('popstate',()=>{setBriefOpen(false);showView('work');});
  $('exportSettings').addEventListener('click',exportSettings);
  $('importSettings').addEventListener('click',()=>{if(!settingsTransferBlocked())$('settingsImportFile').click();});
  $('settingsImportFile').addEventListener('change',event=>{const file=event.target.files?.[0];event.target.value='';return importSettingsFile(file);});
  $('settingsForm').addEventListener('input',event=>{if(event.target.type!=='password'&&event.target.dataset.credential!=='true'&&event.target.id!=='settingsImportFile')markSettingsDirty();});
  $('settingsForm').addEventListener('change',event=>{if(event.target.type!=='password'&&event.target.dataset.credential!=='true'&&event.target.id!=='settingsImportFile')markSettingsDirty();});
  $('settingsForm').addEventListener('invalid',event=>{const card=event.target.closest('.profile-editor');if(card&&card.querySelector('.profile-content').hidden)card.querySelector('[data-readonly]').click();},true);
  $('addProfile').addEventListener('click',()=>{const indexes=[...$('profilesEditor').children].map(node=>Number(node.dataset.index));const index=Math.max(-1,...indexes)+1;appendProfile({id:`profile-${index+1}`,label:'新しいプロファイル',kind:'local',base_url:'http://127.0.0.1:11434/v1',model:'',api_key_env:'',proxy_url:'',enabled:true,request_timeout_seconds:180,context_window_tokens:0},index,true,false);markSettingsDirty();});
  $('settingsForm').addEventListener('submit',saveSettings);
  $('runForm').addEventListener('submit',async event=>{
    event.preventDefault();const task=$('taskInput').value;if(!task.trim()||ui.startingRun||ui.taskReuseCandidate)return;
    const delegationIssue=taskOrchestrationIssue();if(delegationIssue){inlineStatus($('runFormStatus'),delegationIssue,true);return;}
    const workerProfiles=[...$('workerProfiles').querySelectorAll('input:checked')].map(input=>input.value);
    if(!workerProfiles.length&&Number($('maxWorkers').value)>0){inlineStatus($('runFormStatus'),'作業者に使ってよいプロファイルを1つ以上選んでください。',true);return;}
    trackTaskDraft();notice('');
    const action={navigationGeneration:ui.navigationGeneration,dialogGeneration:ui.taskDialogGeneration,draftGeneration:ui.taskDraftGeneration,workspaceGeneration:ui.workspaceGeneration,noticeGeneration:ui.noticeGeneration,runId:null};
    ui.startOperation=action;ui.startingRun=true;syncStartControl();inlineStatus($('runFormStatus'),'チームを準備しています…');
    try {
      const response=await api('/api/runs',{method:'POST',body:runPayload()});
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
    if(!agent||archivedRun(getRun())||archivedAgent(agent)||!text.trim()||ui.busyMessage||agent.message_eligibility?.allowed!==true||['stopping','stopped'].includes(getRun()?.status))return;
    saveAgentDraft();const questionId=ui.draftQuestions.get(agent.id);
    if(questionId===undefined||staleQuestionDraft(agent)){renderConversation(agent);inlineStatus($('messageStatus'),'質問が終了・変更されたか、識別情報を確認できません。下書きを保持しました。',true);return;}
    const action={agent:agent.id,run:agent.run_id,selection:ui.selectionGeneration,draft:ui.draftRevisions.get(agent.id),instance:ui.instanceId,question:questionId};
    const currentTarget=()=>questionReplyTarget(ui.state.agents.find(item=>item.id===action.agent&&item.run_id===action.run))===action.question;
    const owns=()=>ui.messageOperation===action&&ui.instanceId===action.instance&&ui.selectedAgent===action.agent&&ui.selectedRun===action.run&&ui.selectionGeneration===action.selection&&ui.draftRevisions.get(action.agent)===action.draft&&currentTarget();
    const unchanged=()=>ui.messageOperation===action&&ui.instanceId===action.instance&&ui.draftRevisions.get(action.agent)===action.draft&&ui.drafts.get(agent.id)===text&&ui.draftQuestions.get(agent.id)===action.question&&currentTarget();
    ui.messageOperation=action;ui.busyMessage=true;$('sendMessage').disabled=true;
    try {
      const request={method:'POST',body:{text}};
      if(questionId!==null)request.body.question_id=questionId;
      const receipt=await api(`/api/agents/${encodeURIComponent(agent.id)}/message`,request);
      if(ui.messageOperation!==action||ui.instanceId!==action.instance)return;
      if(receipt?.ok!==true){const failure=new Error('応答の形式を確認できませんでした。');failure.outcomeUnknown=true;throw failure;}
      if(unchanged()&&(owns()||ui.selectedAgent!==agent.id)){
        ui.drafts.delete(agent.id);
        ui.draftQuestions.delete(agent.id);
        if(owns()&&$('messageInput').value===text)$('messageInput').value='';
        renderMessageInputPresence();
      }
      if(owns())inlineStatus($('messageStatus'),'送信しました。');await pollState(true);
    }
    catch(error){if(owns())inlineStatus($('messageStatus'),errorText(error)+(error.outcomeUnknown?' 送信結果は未確認です。作業ログを確認してから再送信が必要か判断してください。':''),true);}
    finally{if(ui.messageOperation===action&&ui.instanceId===action.instance){ui.messageOperation=null;ui.busyMessage=false;renderConversation(getAgent());renderMessageInputPresence();}}
  });
  try {
    const fragment=new URLSearchParams(location.hash.slice(1)),token=fragment.get('token');
    if(token){history.replaceState(null,'',location.pathname+location.search);acceptServerInstance(await api('/api/bootstrap',{method:'POST',headers:{'X-Workbench-Bootstrap':token},body:{}}));}
    const response=await api('/api/config');ui.config=response.config;ui.configRevision=response.config_revision;ui.secretStatus=response.secret_status||{};acceptConnectionSettings(response);ui.authenticated=true;renderSettings();renderProfileChoices();await pollState();
  }catch(error){notice(errorText(error),true);setConnection(false,'Workbench 接続待ち');$('startRun').disabled=true;}
  window.setInterval(()=>pollState(),1000);
}
document.addEventListener('DOMContentLoaded',initialize,{once:true});
