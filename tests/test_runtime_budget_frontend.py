"""Public budget snapshots render without guessed limits or a client clock."""
from test_compact_frontend import check_behavior


def test_shared_budget_is_one_team_pool_and_preserves_observed_counts():
    check_behavior(r"""
      seedSelection();const run=ui.state.runs[0];
      run.model_calls=18;run.tool_calls=22;
      run.budget={shared:true,observed_at:1793091600,started_at:1793091000,
        model_calls:{used:18,limit:24,remaining:6},tool_calls:{used:22,limit:60,remaining:38},
        time:{used_seconds:600,limit_seconds:3600,remaining_seconds:3000}};
      renderRun();const text=renderedText($('runMetrics'));
      assert.ok(text.includes('モデル呼び出し（チーム共有）'));
      assert.ok(text.includes('18 / 24（残り 6）'));
      assert.ok(text.includes('22 / 60（残り 38）'));
      assert.ok(text.includes('10分0秒 / 60分0秒（残り 50分0秒）'));
      assert.ok(text.includes('予算の観測時点'));
      assert.equal(run.model_calls,18);assert.equal(run.budget.model_calls.remaining,6);
    """)


def test_legacy_run_does_not_invent_a_budget_or_remaining_time():
    check_behavior(r"""
      seedSelection();const run=ui.state.runs[0];run.model_calls=7;run.tool_calls=9;
      renderRun();const text=renderedText($('runMetrics'));
      assert.ok(text.includes('モデル呼び出し\n7'));
      assert.ok(text.includes('ツール実行\n9'));
      assert.ok(!text.includes('残り'));assert.ok(!text.includes('実行時間'));
      assert.ok(!text.includes('予算の観測時点'));
    """)


def test_archived_budget_is_a_saved_observation_not_a_running_countdown():
    check_behavior(r"""
      const run={archived:true,budget:{shared:true,observed_at:1000,
        time:{used_seconds:90,limit_seconds:120,remaining_seconds:30}}};
      const before=JSON.stringify(sharedBudgetMetrics(run));
      const old=Date.now;Date.now=()=>9999999999999;
      try{assert.equal(JSON.stringify(sharedBudgetMetrics(run)),before);}
      finally{Date.now=old;}
      assert.ok(before.includes('予算の保存時点'));
      assert.ok(before.includes('残り 0分30秒'));
    """)


def test_invalid_snapshot_does_not_display_false_remaining_capacity():
    check_behavior(r"""
      for(const count of [null,{used:1,limit:24,remaining:23},{used:7,limit:24,remaining:24},
        {used:NaN,limit:24,remaining:23},{used:1,limit:-1,remaining:0},
        {used:1,limit:24,remaining:'23'},{used:-1,limit:24,remaining:25}]) {
        assert.equal(sharedBudgetCount({budget:{shared:true,model_calls:count}},'model_calls',7),7);
      }
      for(const time of [{used_seconds:NaN,limit_seconds:60,remaining_seconds:0},
        {used_seconds:1,limit_seconds:60,remaining_seconds:60},
        {used_seconds:-1,limit_seconds:60,remaining_seconds:61},
        {used_seconds:1,limit_seconds:Infinity,remaining_seconds:Infinity}]) {
        assert.deepEqual(sharedBudgetMetrics({budget:{shared:true,time}}),[]);
      }
      assert.deepEqual(sharedBudgetMetrics({budget:{shared:true,observed_at:Infinity}}),[]);
    """)


def test_exhausted_budget_keeps_actual_used_values_without_refill():
    check_behavior(r"""
      const run={budget:{shared:true,model_calls:{used:24,limit:24,remaining:0},
        time:{used_seconds:3601,limit_seconds:3600,remaining_seconds:0}}};
      assert.equal(sharedBudgetCount(run,'model_calls',24),'24 / 24（残り 0）');
      assert.ok(JSON.stringify(sharedBudgetMetrics(run)).includes('60分1秒 / 60分0秒（残り 0分0秒）'));
    """)


def test_typed_stop_reasons_are_distinct_and_unknown_text_is_not_a_label():
    check_behavior(r"""
      const run={stop_reasons:['provider_timeout','model_limit','provider_timeout','<script>bad</script>']};
      const rows=runtimeStopMetrics(run);
      assert.equal(rows[0][0],'担当の停止理由');
      assert.ok(rows[0][1].includes('モデルAPIの応答待ちタイムアウト（自動再試行なし）'));
      assert.ok(rows[0][1].includes('モデル呼び出し回数の上限'));
      assert.ok(!rows[0][1].includes('実行時間の上限'));
      assert.ok(!rows[0][1].includes('<script>'));
      assert.equal(rows[0][1].match(/タイムアウト/g).length,1);
      assert.deepEqual(runtimeStopMetrics({stop_reason:'unknown'}),[]);
      assert.deepEqual(runtimeStopMetrics({stop_reason:'multiple'}),[]);
    """)


def test_budget_observation_does_not_replace_unsent_question_draft():
    check_behavior(r"""
      seedSelection();$('messageInput').value='Preserve my unsent note';saveAgentDraft();
      const run=ui.state.runs[0];
      run.model_calls=23;run.budget={shared:true,model_calls:{used:23,limit:24,remaining:1}};
      renderRun();run.model_calls=24;run.budget.model_calls={used:24,limit:24,remaining:0};renderRun();
      assert.equal($('messageInput').value,'Preserve my unsent note');
      assert.equal(ui.drafts.get(ui.selectedAgent),'Preserve my unsent note');
      assert.ok(renderedText($('runMetrics')).includes('24 / 24（残り 0）'));
    """)
