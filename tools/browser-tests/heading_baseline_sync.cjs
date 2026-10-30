'use strict';

// Static candidate only. No browser/server is created and no work runs on import.
// This exact self-contained factory is used by both the browser and the trace probe.
function createHeadingSync(options = {}) {
  const budget = options.budgetMs === undefined ? 10000 : options.budgetMs;
  if (!Number.isFinite(budget) || budget <= 0 || budget > 10000) throw new Error('invalid_budget');
  const vectorKeys = ['top', 'height', 'client', 'width', 'clientWidth'];
  let phase = 'new', initial, last, started, latestAt = -Infinity;
  let movement = 0, completion = null, candidate = null, stable = 0;
  let prepMoved = false, endMoved = false, endScrollSeen = false, endStartMovement = null;
  let resetCount = 0, focusCount = 0, keydownCount = 0, keyupCount = 0;
  let downStamp = null, upStamp = null, baselineCount = 0, baselineValue;
  let completionCount = 0, prepCompletion = null, baselineGeneration = null;
  let hasFailure = false, failure;

  const same = (a, b) => {
    if (a === b) return true;
    if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every(k => Object.hasOwn(b, k) && same(a[k], b[k]));
  };
  const copy = value => Array.isArray(value) ? value.map(copy) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([k, v]) => [k, copy(v)])) : value;
  const reject = code => { throw new Error(code); };
  const transact = fn => {
    if (hasFailure) throw failure;
    try { return fn(); }
    catch (error) { hasFailure = true; failure = error; phase = 'failed'; throw error; }
  };
  const time = at => {
    if (!Number.isFinite(at) || at < latestAt) reject('invalid_or_regressing_time');
    latestAt = at;
    if (started !== undefined && phase !== 'baseline' && phase !== 'compared' && at - started >= budget) reject('readiness_deadline');
  };
  const vectorEqual = (a, b) => vectorKeys.every(k => a[k] === b[k]);
  const nearEnd = vector => vector.top > 0 && vector.height - vector.client - vector.top <= 1;
  const ownerValid = owner => owner && typeof owner.run === 'string' && owner.run.trim() !== ''
    && typeof owner.agent === 'string' && owner.agent.trim() !== ''
    && Number.isSafeInteger(owner.generation) && owner.generation >= 0
    && owner.authenticated === true && owner.detailError === false
    && owner.loadedDetail && owner.loadedDetail.run === owner.run
    && owner.loadedDetail.agent === owner.agent && owner.loadedDetail.generation === owner.generation;
  const guards = snapshot => {
    if (!snapshot || !snapshot.connected || snapshot.node !== initial.node) reject('node_changed');
    if (!ownerValid(snapshot.owner)) reject('owner_admission_invalid');
    if (!same(snapshot.owner, initial.owner)) reject('owner_changed');
    if (!Array.isArray(snapshot.chain) || !same(snapshot.chain,initial.chain)) reject('ancestor_chain_changed');
    if (!same(snapshot.ancestors, initial.ancestors) || !same(snapshot.window, initial.window)) reject('ancestor_or_window_changed');
    if (!same(snapshot.rect, initial.rect)) reject('heading_rectangle_changed');
    for (const key of vectorKeys) if (!Number.isFinite(snapshot.vector[key])) reject('invalid_vector');
    for (const key of vectorKeys.slice(1)) if (snapshot.vector[key] !== initial.vector[key]) reject('dimension_changed');
    if (focusCount === 1 && snapshot.focus !== initial.node) reject('focus_changed');
  };
  const observe = (snapshot, at) => {
    time(at); guards(snapshot);
    if (!vectorEqual(snapshot.vector, last.vector)) {
      if (phase === 'armed') reject('preparation_changed_after_arming');
      if (phase === 'ready') reject('frozen_candidate_changed');
      movement++;
      if (phase === 'preparing') prepMoved = true;
      if (phase === 'end') endMoved = true;
      if (phase !== 'baseline' && phase !== 'compared') { completion = null; stable = 0; candidate = null; }
    }
    last = copy(snapshot);
  };
  const eventShape = event => {
    if (!event || event.trusted !== true || event.target !== initial.node || !Number.isFinite(event.stamp)) reject('invalid_event_identity');
  };
  const plainEnd = event => event.key === 'End' && event.repeat === false
    && event.ctrlKey === false && event.altKey === false && event.metaKey === false && event.shiftKey === false;
  const summary = () => ({phase, movement, completion: copy(completion), candidate: copy(candidate), stable,
    prepMoved, endMoved, endScrollSeen, resetCount, focusCount, keydownCount, keyupCount,
    baselineCount, baselineValue, baselineGeneration, completionCount, prepCompletion: copy(prepCompletion),
    latestAt, budgetMs: budget, hasFailure});

  return {
    initialize(snapshot, at) { return transact(() => {
      if (phase !== 'new' || !snapshot || !snapshot.connected || !snapshot.node) reject('invalid_initialization');
      initial = copy(snapshot); last = copy(snapshot); started = at; phase = 'preparing';
      time(at); guards(snapshot); return summary();
    }); },
    reset(snapshot, at) { return transact(() => {
      if (phase !== 'preparing' || resetCount !== 0) reject('reset_count');
      resetCount++; observe(snapshot, at); if (snapshot.vector.top !== 0) reject('reset_not_zero'); return summary();
    }); },
    focused(snapshot, at) { return transact(() => {
      if (phase !== 'preparing' || resetCount !== 1 || focusCount !== 0) reject('focus_order');
      focusCount++; observe(snapshot, at); return summary();
    }); },
    sample(snapshot, at) { return transact(() => { observe(snapshot, at); return summary(); }); },
    frame(snapshot, at) { return transact(() => {
      observe(snapshot, at);
      if (phase === 'preparing') {
        if (resetCount !== 1 || focusCount !== 1 || snapshot.vector.top !== 0) { stable = 0; return summary(); }
        if (prepMoved && (!completion || completion.generation !== movement)) { stable = 0; return summary(); }
        stable++;
        if (stable === 4) {
          prepCompletion = completion ? copy(completion) : {noObservedMovement: true, generation: movement};
          phase = 'armed'; completion = null; stable = 0;
        }
      } else if (phase === 'end') {
        if (!completion || completion.generation !== movement || keyupCount !== 1 || !endMoved || !endScrollSeen || !nearEnd(snapshot.vector)) { stable = 0; return summary(); }
        if (!vectorEqual(snapshot.vector, completion.vector)) reject('completion_vector_mismatch');
        stable++;
        if (stable === 4) { candidate = {generation: movement, vector: copy(snapshot.vector), completion: copy(completion)}; phase = 'ready'; }
      }
      return summary();
    }); },
    event(type, event, snapshot, at) { return transact(() => {
      time(at); eventShape(event);
      if (type === 'keydown') {
        if (phase !== 'armed' || keydownCount !== 0 || !plainEnd(event) || snapshot.focus !== initial.node) reject('invalid_keydown');
        observe(snapshot, at); keydownCount++; downStamp = event.stamp; endStartMovement = movement; phase = 'end'; return summary();
      }
      if (type === 'keyup') {
        if (phase !== 'end' || keydownCount !== 1 || keyupCount !== 0 || !plainEnd(event) || event.stamp < downStamp) reject('invalid_keyup');
        observe(snapshot, at); keyupCount++; upStamp = event.stamp; return summary();
      }
      if (type !== 'scroll' && type !== 'scrollend') reject('unknown_event');
      if (phase === 'armed') reject('prior_epoch_event_after_arming');
      if (phase === 'end' || phase === 'ready') {
        if (event.stamp < downStamp) reject('known_prior_epoch_event');
        if (type === 'scrollend' && (keyupCount !== 1 || event.stamp < upStamp)) reject('completion_before_key_release');
      }
      // Fold the event-local vector into movement before committing completion.
      observe(snapshot, at);
      if (phase === 'baseline' || phase === 'compared') return summary();
      if (type === 'scroll') {
        if (phase === 'end') {
          if (movement <= endStartMovement || !endMoved || snapshot.vector.top === 0) reject('unmatched_post_key_scroll');
          endScrollSeen = true;
        }
        return summary(); // Same-value notifications do not invalidate completion/stability.
      }
      if (phase === 'ready') reject('ambiguous_extra_completion');
      if (phase === 'preparing') { if (!prepMoved) reject('unmatched_preparation_completion'); }
      else if (phase === 'end') {
        if (keyupCount !== 1 || !endMoved || !endScrollSeen || movement <= endStartMovement) reject('unmatched_end_completion');
      } else reject('completion_wrong_phase');
      if (completion && completion.generation === movement) reject('duplicate_completion');
      completion = {epoch: phase, generation: movement, vector: copy(snapshot.vector), at, stamp: event.stamp};
      completionCount++; stable = 0; return summary();
    }); },
    baseline(snapshot, scalar, at) { return transact(() => {
      if (phase !== 'ready' || baselineCount !== 0 || !candidate) reject('baseline_not_ready_or_repeated');
      observe(snapshot, at);
      if (candidate.generation !== movement || !vectorEqual(snapshot.vector, candidate.vector) || scalar !== snapshot.vector.top || scalar !== candidate.vector.top) reject('baseline_candidate_mismatch');
      if (!nearEnd(snapshot.vector)) reject('baseline_not_near_end');
      baselineCount++; baselineValue = scalar; baselineGeneration = movement; phase = 'baseline'; return scalar;
    }); },
    compare(snapshot, scalar, at) { return transact(() => {
      if (phase !== 'baseline' || baselineCount !== 1) reject('comparison_without_baseline');
      observe(snapshot, at); if (scalar !== snapshot.vector.top) reject('actual_scalar_inconsistent');
      const equal = scalar === baselineValue;
      phase = 'compared'; return {expected: baselineValue, actual: scalar, equal};
    }); },
    inspect() { if (hasFailure) throw failure; return summary(); }
  };
}

// Installed in the existing page with its exact shared logic handle; not a second state machine.
function installHeadingAdapter(logic, options) {
  const clock = performance.now.bind(performance), origin = clock();
  const heading = document.querySelector('#conversationHeading');
  if (!heading) throw new Error('missing_heading');
  const ancestors = []; for (let node = heading.parentElement; node; node = node.parentElement) ancestors.push(node);
  const ids = new WeakMap(); let nextId = 1;
  const id = node => { if (!node) return null; if (!ids.has(node)) ids.set(node, nextId++); return ids.get(node); };
  const now = () => clock() - origin;
  const rect = node => { const r = node.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; };
  const snapshot = () => {
    if (typeof ui !== 'object' || !ui) throw new Error('product_owner_unavailable');
    const current = document.querySelector('#conversationHeading');
    const currentChain=[];for(let node=heading.parentElement;node;node=node.parentElement)currentChain.push(id(node));
    const top = heading.scrollTop; // Exactly one scalar read per snapshot/baseline/actual callback.
    return {node:id(current),connected:heading.isConnected && current === heading,focus:id(document.activeElement),chain:currentChain,
      owner:{run:ui.selectedRun,agent:ui.selectedAgent,generation:ui.selectionGeneration,authenticated:ui.authenticated,
        detailError:Boolean(ui.detailError),loadedDetail:ui.loadedDetail?{run:ui.loadedDetail.run,agent:ui.loadedDetail.agent,generation:ui.loadedDetail.generation}:null},
      vector:{top,height:heading.scrollHeight,client:heading.clientHeight,width:heading.scrollWidth,clientWidth:heading.clientWidth},
      rect:rect(heading),ancestors:ancestors.map(node=>({node:id(node),connected:node.isConnected,top:node.scrollTop,left:node.scrollLeft,rect:rect(node)})),
      window:{x:scrollX,y:scrollY,width:innerWidth,height:innerHeight}};
  };
  let hasError = false, primaryError, disposed = false, raf = null, timer = null;
  let waiter = null; const owned = [];
  const fail = error => { if (!hasError) { hasError = true; primaryError = error; } if (raf !== null) cancelAnimationFrame(raf); raf = null; if (waiter) { waiter.reject(primaryError); waiter = null; } };
  const localDeadline = () => { if (!['baseline','compared'].includes(logic.inspect().phase) && now() >= options.remainingMs) throw new Error('browser_readiness_deadline'); };
  const checked = fn => { if (hasError) throw primaryError; if (disposed) throw new Error('adapter_disposed'); try { localDeadline(); return fn(); } catch (error) { fail(error); throw error; } };
  const settleWaiter = () => { if (waiter && logic.inspect().phase === waiter.phase) { waiter.resolve(logic.inspect()); waiter = null; } };
  const schedule = () => {
    if (disposed || hasError || raf !== null) return;
    const phase = logic.inspect().phase; if (phase !== 'preparing' && phase !== 'end') return;
    raf = requestAnimationFrame(() => { raf = null; try { localDeadline(); logic.frame(snapshot(), now()); settleWaiter(); schedule(); } catch (error) { fail(error); } });
  };
  const listen = (target,type,listener) => { target.addEventListener(type,listener,{passive:true}); owned.push([target,type,listener]); };
  const onHeading = event => {
    try {
      localDeadline();
      if (event.target !== heading) throw new Error('wrong_heading_event_target');
      logic.event(event.type,{target:id(event.target),trusted:event.isTrusted,stamp:event.timeStamp,key:event.key,repeat:event.repeat === true,
        ctrlKey:event.ctrlKey === true,altKey:event.altKey === true,metaKey:event.metaKey === true,shiftKey:event.shiftKey === true},snapshot(),now());
      settleWaiter(); schedule();
    } catch (error) { fail(error); }
  };
  const onEnvironment = event => {
    if (event.target === heading) return; // A bubbling heading completion is owned by its own listener.
    try { localDeadline(); logic.sample(snapshot(),now()); settleWaiter(); } catch (error) { fail(error); }
  };
  try {
    logic.initialize(snapshot(),now());
    for (const type of ['keydown','keyup','scroll','scrollend']) listen(heading,type,onHeading);
    for (const target of [...ancestors,window]) for (const type of ['scroll','scrollend']) listen(target,type,onEnvironment);
    timer = setTimeout(() => { try { if (!['baseline','compared'].includes(logic.inspect().phase)) fail(new Error('browser_readiness_deadline')); } catch (error) { fail(error); } },options.remainingMs);
  } catch (error) { for (const [target,type,listener] of owned) target.removeEventListener(type,listener); throw error; }
  return {
    prepare() { return checked(() => {
      heading.scrollTop = 0;
      logic.reset(snapshot(),now());
      const titleVisible = document.querySelector('#conversationTitle').getBoundingClientRect().top >= heading.getBoundingClientRect().top;
      if (!titleVisible) throw new Error('Beginning of full identity remains reachable above the scroll region');
      return logic.inspect();
    }); },
    focused() { return checked(() => { logic.focused(snapshot(),now());schedule();return logic.inspect(); }); },
    wait(phase) { return checked(() => {
      if (waiter) throw new Error('duplicate_adapter_wait');
      if (logic.inspect().phase === phase) return Promise.resolve(logic.inspect());
      return new Promise((resolve,reject) => { waiter = {phase,resolve,reject}; schedule(); });
    }); },
    nearEnd() { return checked(() => {
      const node = document.querySelector('#conversationHeading');
      return node.scrollTop > 0 && node.scrollHeight - node.clientHeight - node.scrollTop <= 1;
    }); },
    profileVisible() { return checked(() => document.querySelector('#conversationProfile').getBoundingClientRect().bottom <= heading.getBoundingClientRect().bottom); },
    baseline() { return checked(() => {
      const value = snapshot();
      const scalar = value.vector.top;
      const result = logic.baseline(value,scalar,now());
      clearTimeout(timer);timer=null;return result;
    }); },
    actual() { return checked(() => { const value=snapshot();return logic.compare(value,value.vector.top,now()); }); },
    inspect() { return checked(() => logic.inspect()); },
    abort() { fail(new Error('host_readiness_aborted'));return {aborted:true}; },
    dispose() {
      if (disposed) return {disposed:true,listeners:0};
      disposed=true; if(raf!==null)cancelAnimationFrame(raf);if(timer!==null)clearTimeout(timer);
      raf=null;timer=null;for(const [target,type,listener] of owned)target.removeEventListener(type,listener);
      if(waiter){waiter.reject(new Error('adapter_disposed'));waiter=null;}
      return {disposed:true,listeners:0};
    }
  };
}

async function preservePrimary(body, cleanup, noteCleanup = () => {}) {
  let hasPrimaryError = false, primaryError, result;
  try { result = await body(); } catch (error) { hasPrimaryError = true; primaryError = error; }
  try { await cleanup(); } catch (cleanupError) {
    try { noteCleanup(cleanupError); } catch (_) { /* Reporting cannot replace either primary error. */ }
    if (!hasPrimaryError) throw cleanupError;
  }
  if (hasPrimaryError) throw primaryError;
  return result;
}

// Same host-deadline implementation is exercised with a virtual clock by the probe.
function createHostDeadline(clock) {
  const deadline = clock.now() + 10000, pending = new Set(), issuedRows = [];
  let aborted = false;
  const remaining = () => {
    const value = deadline - clock.now();
    if (aborted || !(value > 0)) { aborted = true; throw new Error('host_readiness_deadline'); }
    return value;
  };
  return {
    remaining,
    inspect() { return {aborted,deadline,pending:pending.size,issued:issuedRows.length}; },
    async run(operation, acceptValue = () => {}) {
      const left = remaining(); let timer;
      const row={sequence:issuedRows.length+1,status:'pending'};issuedRows.push(row);
      const issued = Promise.resolve().then(() => { remaining(); return operation(); }).then(value => { acceptValue(value);return value; });
      issued.then(()=>{row.status='fulfilled';},error=>{row.status='rejected';row.error=String(error?.stack||error);});
      pending.add(issued); issued.then(() => pending.delete(issued), () => pending.delete(issued));
      try {
        const result = await Promise.race([issued,new Promise((_,reject) => {
          timer = clock.setTimeout(() => { aborted = true; reject(new Error('host_readiness_deadline')); },left);
        })]);
        remaining(); return result;
      } catch (error) { if(clock.now()>=deadline)aborted=true;throw error; }
      finally { clock.clearTimeout(timer); }
    },
    async drain() { await Promise.allSettled([...pending]);return issuedRows.map(row=>({...row})); }
  };
}

// Finite terminal cleanup is separate from, and cannot renew, readiness.
async function boundedCleanup(clock, operation, receipt, startedAt = clock.now()) {
  const deadline = startedAt + 5000; let expired = false, timer;
  receipt.startedAt = startedAt; receipt.deadline = deadline; receipt.state = 'pending';
  const guard = () => { if (expired || clock.now() >= deadline) throw new Error('cleanup_deadline'); };
  const issued = Promise.resolve().then(() => { guard(); return operation(guard); }).then(value => { guard(); return value; });
  try {
    const value = await Promise.race([issued,new Promise((_,reject) => {
      timer = clock.setTimeout(() => { expired = true; reject(new Error('cleanup_deadline')); },Math.max(0,deadline-clock.now()));
    })]);
    receipt.state = 'verified'; return value;
  } catch (error) {
    receipt.state = 'cleanup_incomplete'; receipt.error = String(error?.stack||error); throw error;
  } finally { clock.clearTimeout(timer); }
}

// Caller validates exact ownership, normally closes that isolated synthetic Page,
// and returns {target: page, owned: true}. No page discovery or direct close here.
async function recoverTimedOutReadiness({page,closeOwnedPageOnTimeout,budget,clock,disposeHandles,receipt = {},startedAt = clock.now()}) {
  if (!budget.inspect().aborted) return {required:false,callbackCalls:0};
  receipt.required = true; receipt.callbackCalls = 0;
  return boundedCleanup(clock,async guard => {
    if (typeof closeOwnedPageOnTimeout !== 'function') throw new Error('missing_owned_page_timeout_capability');
    receipt.callbackCalls++;
    const close = await closeOwnedPageOnTimeout(page); guard();
    if (!close || close.target !== page || close.owned !== true || typeof page.isClosed !== 'function' || page.isClosed() !== true) throw new Error('owned_page_close_unverified');
    receipt.exactOwnedPageClosed = true; receipt.observersEndedByExactPageClosure = true;
    const terminals = await budget.drain(); guard();
    if (budget.inspect().pending !== 0 || terminals.length !== budget.inspect().issued || terminals.some(row=>!['fulfilled','rejected'].includes(row.status))) throw new Error('issued_rpc_not_terminal');
    receipt.rpcTerminals = terminals;
    await disposeHandles(guard); guard();
    return {required:true,callbackCalls:1,exactOwnedPageClosed:true,observersEndedByExactPageClosure:true,rpcTerminals:receipt.rpcTerminals};
  },receipt,startedAt);
}

// Future integration entry point; accepts an already-owned Playwright page only.
// No browser import/launch, routing, fixture mutation, server control, deletion or retry.
async function assertHeadingPollPreservation(page, {closeOwnedPageOnTimeout,recordReceipt} = {}) {
  const assert = require('node:assert/strict');
  assert.equal(typeof closeOwnedPageOnTimeout,'function','Ownership-bound timeout cleanup capability required');
  assert.equal(typeof recordReceipt,'function','Synchronous outer receipt sink required');
  const clock = require('node:perf_hooks').performance;
  const hostClock = {now:()=>clock.now(),setTimeout,clearTimeout};
  const budget = createHostDeadline(hostClock);
  let logicHandle, adapterHandle;
  const receipt = {kind:'bounded_heading_baseline_candidate',cleanupErrors:[],endPresses:0,hostAborted:false};
  const remaining = budget.remaining;
  const bound = budget.run;
  return preservePrimary(async () => {
    try {
    await bound(() => page.evaluateHandle(createHeadingSync,{budgetMs:remaining()}),value=>{logicHandle=value;});
    await bound(() => logicHandle.evaluateHandle(installHeadingAdapter,{remainingMs:remaining()}),value=>{adapterHandle=value;});
    await bound(() => adapterHandle.evaluate(adapter=>adapter.prepare()));
    await bound(() => page.locator('#conversationHeading').focus({timeout:remaining()}));
    await bound(() => adapterHandle.evaluate(adapter=>adapter.focused()));
    receipt.preparation = await bound(() => adapterHandle.evaluate(adapter=>adapter.wait('armed')));
    receipt.endPresses++;await bound(() => page.keyboard.press('End'));
    receipt.candidate = await bound(() => adapterHandle.evaluate(adapter=>adapter.wait('ready')));
    assert(await bound(() => adapterHandle.evaluate(adapter=>adapter.nearEnd())),'Original positive-top / near-end <=1 condition');
    assert(await bound(() => adapterHandle.evaluate(adapter=>adapter.profileVisible())),'Keyboard reaches full model identity and disclaimer');
    const headingScroll = await bound(() => adapterHandle.evaluate(adapter=>adapter.baseline()));
    receipt.expected=headingScroll;
    // Existing post-baseline wait/timeouts and strict comparison remain unchanged.
    const unchangedProfilePoll = await page.waitForResponse(response=>response.url().includes('/api/state?'));
    await unchangedProfilePoll.finished();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const comparison = await adapterHandle.evaluate(adapter=>adapter.actual());
    receipt.actual=comparison.actual;
    receipt.strict=comparison.actual===headingScroll?'PASS':'FAIL';
    assert.equal(comparison.actual,headingScroll,'Unchanged polling preserves keyboard metadata scroll');
    receipt.finalState=await adapterHandle.evaluate(adapter=>adapter.inspect());
    return receipt;
    }catch(error){receipt.primaryFailure={type:typeof error,text:String(error?.stack||error)};throw error;}
  },async () => {
    const cleanupStarted = hostClock.now();
    let hasCleanupError=false,cleanupError;
    receipt.hostAborted=budget.inspect().aborted;
    receipt.cleanup={};
    const disposeHandles = async guard => {
      for(const handle of [adapterHandle,logicHandle])try{guard();await handle?.dispose();}catch(error){receipt.cleanupErrors.push(String(error));if(!hasCleanupError){hasCleanupError=true;cleanupError=error;}}
      if(hasCleanupError)throw cleanupError;
    };
    try {
      if(receipt.hostAborted){
        receipt.timeoutRecovery=await recoverTimedOutReadiness({page,closeOwnedPageOnTimeout,budget,clock:hostClock,disposeHandles,receipt:receipt.cleanup,startedAt:cleanupStarted});
      } else {
        await boundedCleanup(hostClock,async guard=>{
          for(const operation of [()=>adapterHandle?.evaluate(adapter=>adapter.dispose()),()=>disposeHandles(guard)]) {
            try{guard();await operation();}catch(error){receipt.cleanupErrors.push(String(error));if(!hasCleanupError){hasCleanupError=true;cleanupError=error;}}
          }
          if(hasCleanupError)throw cleanupError;
        },receipt.cleanup,cleanupStarted);
      }
    } catch(error) {if(!hasCleanupError){hasCleanupError=true;cleanupError=error;}receipt.cleanupErrors.push(String(error));}
    receipt.cleanup_incomplete=receipt.cleanup.state!=='verified';
    receipt.outerLifecycleVerified=false;
    // Synchronous assignment to the owning runtime report; not file/network IO.
    try{const output=recordReceipt(structuredClone(receipt));if(output&&typeof output.then==='function')throw new Error('receipt_sink_must_be_synchronous');}
    catch(error){if(!hasCleanupError){hasCleanupError=true;cleanupError=error;}}
    if(hasCleanupError)throw cleanupError;
  },error=>{receipt.cleanupErrors.push(String(error));});
}

module.exports = {createHeadingSync, installHeadingAdapter, preservePrimary, createHostDeadline, boundedCleanup, recoverTimedOutReadiness, assertHeadingPollPreservation};
