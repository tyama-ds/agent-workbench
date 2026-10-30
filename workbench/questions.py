"""Server-owned consultation deadlines; timeout is never human authorization."""
import asyncio
import json
import re
import secrets
import time

from .config import effective_config, text

QUESTION_SECONDS = 90.0


class QuestionConflict(ValueError):
    code = 'question_conflict'


class QuestionFallbackMixin:
    @staticmethod
    def _question_monotonic():
        return time.monotonic()

    @staticmethod
    def _question_wall_time():
        return time.time()

    async def _question_sleep(self, seconds):
        await asyncio.sleep(seconds)

    def _question_cancel_timer(self, record):
        task = record.get('task')
        if task is not None and task is not asyncio.current_task() and not task.done() and not task.cancelling():
            task.cancel()

    def _question_resolve(self, agent, record, resolution, reason='', *, clear=False):
        if self._questions.get(agent.id) is not record or record['state']['resolution'] not in {'pending', 'blocked'}:
            return False
        record['state'].update(resolution=resolution, resolved_at=self._question_wall_time(), reason=reason)
        if clear:
            agent.question = ''
        self._question_cancel_timer(record)
        return True

    def _question_notice(self, run, agent, message):
        try:
            self.event(run['id'], agent.id, 'question_resolved', message)
        except Exception:
            # The resolution is already committed; never retry/resend a fallback.
            self.history.error = '質問の状態は更新済みですが通知を保存できません。現在の状態を確認してください。'

    def _ask_question(self, run, agent, args):
        if (self.runs.get(run['id']) is not run or self.agents.get(agent.id) is not agent
                or agent.id not in run['agent_ids'] or agent.run_id != run['id']):
            raise ValueError('質問する担当と作業が一致しません')
        question = text(args['question'], 'question', 4000, False)
        kind = args.get('kind', 'consultation')
        if not isinstance(kind, str) or kind not in {'consultation', 'permission'}:
            raise ValueError('kind は consultation または permission です')
        recommendation = text(args['recommendation'], 'recommendation', 4000, False) if 'recommendation' in args else ''
        if recommendation and not recommendation.strip():
            raise ValueError('recommendation は空白だけにできません')
        automatic = kind == 'consultation' and bool(recommendation)
        asked_at = self._question_wall_time()
        state = {'question_id': 'q-' + secrets.token_hex(16), 'kind': kind,
                 'recommendation': recommendation, 'asked_at': asked_at,
                 'deadline_at': asked_at + QUESTION_SECONDS if automatic else None,
                 'resolution': 'pending', 'resolved_at': None, 'reason': ''}
        # All fallible validation/masking precedes replacing an older question.
        self.redact(question)
        visible = self._redact_tree(state)
        for key in ('question_id', 'kind', 'resolution'):
            visible[key] = state[key]
        previous = self._questions.get(agent.id)
        if previous is not None:
            self._question_resolve(agent, previous, 'cancelled', 'superseded')
        agent.question, agent.question_state = question, state
        record = {'state': state, 'question': question, 'automatic': automatic,
                  'revision': agent.result_revision, 'dependency_epoch': agent.dependency_epoch,
                  'dependencies': dict(agent.dependency_revisions), 'run': run, 'agent': agent,
                  'deadline': self._question_monotonic() + QUESTION_SECONDS if automatic else None,
                  'task': None}
        self._questions[agent.id] = record
        if automatic:
            task = asyncio.create_task(self._question_wait(record), name='question-' + state['question_id'])
            record['task'] = task
            self._question_tasks[task] = run['id']
            task.add_done_callback(lambda finished: self._question_tasks.pop(finished, None))
        self.event(run['id'], agent.id, 'question', question)
        return {'ok': True, 'waiting_for_human': True, 'question_state': visible}

    async def _question_wait(self, record):
        try:
            while record['state']['resolution'] == 'pending':
                remaining = record['deadline'] - self._question_monotonic()
                if remaining <= 0:
                    self._question_timeout(record)
                    return
                await self._question_sleep(remaining)
        except asyncio.CancelledError:
            pass
        except Exception:
            agent = record['agent']
            # An exception while publishing an already committed outcome must
            # not replace that outcome's original reason with timer_error.
            if (record['state']['resolution'] == 'pending'
                    and self._question_resolve(agent, record, 'blocked', 'timer_error')):
                self._question_notice(record['run'], agent, '自動継続を停止しました。人の回答を待っています。')

    def _question_timeout_reason(self, record):
        run, agent = record['run'], record['agent']
        if (self.closed or agent.closing or self.runs.get(run['id']) is not run
                or self.agents.get(agent.id) is not agent or run['status'] not in {'running', 'waiting'}
                or agent.status in {'stopped', 'stopping', 'error'} or agent.last_error):
            return 'stopped_or_error'
        if run['_config'] != effective_config(self.settings.value):
            return 'settings_changed'
        try:
            self.credentials.check_bindings(self.settings.value['providers'])
            self.credentials.require_usable()
            self.history.require_writable()
        except (ValueError, OSError):
            return 'storage_unavailable'
        if (agent.dependency_epoch != record['dependency_epoch'] or agent.dependency_revisions != record['dependencies']
                or (agent.depends_on and (self._dependency_stale(agent) or self._dependency_blockers(agent)))):
            return 'dependency_changed'
        if agent.result_revision != record['revision']:
            return 'new_input'
        limits = run['_config']['limits']
        if self._question_wall_time() - run['created_at'] >= limits['max_run_seconds']:
            return 'time_limit'
        if run['model_calls'] >= limits['max_model_calls']:
            return 'model_limit'
        if run['tool_calls'] >= limits['max_tool_calls']:
            return 'tool_limit'
        if agent.turns >= limits['max_turns_per_agent']:
            return 'turn_limit'
        if len(agent.pending) >= 31:
            return 'queue_full'
        if agent.pending:
            return 'new_input'
        if run.get('_collaboration_blocked'):
            return 'collaboration_limit'
        if self._context_limit_reached(run, agent):
            return 'context_limit'
        return ''

    def _question_timeout(self, record):
        run, agent, state = record['run'], record['agent'], record['state']
        if (self._questions.get(agent.id) is not record or state['resolution'] != 'pending'
                or agent.question != record['question'] or not record['automatic']
                or self._question_monotonic() < record['deadline']):
            return False
        reason = self._question_timeout_reason(record)
        if reason:
            cancelled = reason in {'dependency_changed', 'stopped_or_error'}
            self._question_resolve(agent, record, 'cancelled' if cancelled else 'blocked', reason, clear=cancelled)
            self._question_notice(run, agent, '自動継続を停止しました。質問の状態と作業の制約を確認してください。')
            self._run_status(run)
            return False
        content = ('Application consultation timeout; NOT a human answer or authorization. '
                   'Continue with the recorded recommendation only within the original request, current permissions and remaining budgets. '
                   'Do not treat silence as permission. If permission is needed, ask_user(kind="permission") and wait.\n'
                   + json.dumps({'operation': 'question_fallback', 'source': 'application', 'human_authorization': False,
                                 'question_id': state['question_id'], 'question': record['question'],
                                 'recommendation': state['recommendation']}, ensure_ascii=False))
        self.redact(content)
        self._check_queue(agent)
        # No await from identity check through resolution and enqueue: exactly
        # one answer/timeout wins on the owning event loop.
        self._question_resolve(agent, record, 'fallback', 'unanswered_recommendation', clear=True)
        try:
            self.enqueue(agent, content, human=False)
        except Exception:
            if not any(value == content and not human for value, human in agent.pending):
                state.update(resolution='blocked', reason='enqueue_failed', resolved_at=self._question_wall_time())
                agent.question = record['question']
                self._question_notice(run, agent, '自動継続を開始できませんでした。人の回答を待っています。')
                return False
            # A post-append notification failed. The item is already accepted.
        self._question_notice(run, agent, '約90秒間回答がなかったため、記録した推奨案で継続します。人の許可としては扱いません。\n'
            + json.dumps({'question_id': state['question_id'], 'recommendation': state['recommendation'],
                          'resolution': 'fallback', 'source': 'application', 'human_authorization': False}, ensure_ascii=False))
        self._run_status(run)
        return True

    def _question_check_answer(self, agent, question_id):
        record = self._questions.get(agent.id)
        active = record is not None and agent.question and record['state']['resolution'] in {'pending', 'blocked'}
        if question_id is not None:
            if (not isinstance(question_id, str) or not re.fullmatch(r'q-[0-9a-f]{32}', question_id)
                    or not active or record['state']['question_id'] != question_id):
                raise QuestionConflict('質問が変更または解決済みです。現在の質問を確認してください。')
        elif active and record['automatic']:
            raise QuestionConflict('この質問への回答には現在のquestion_idが必要です。')

    def _question_answered(self, agent):
        record = self._questions.get(agent.id)
        if record is not None:
            self._question_resolve(agent, record, 'answered', 'human_answer')

    def _question_cancel_stale_dependencies(self, run):
        for ident in run['agent_ids']:
            agent = self.agents[ident]
            record = self._questions.get(ident)
            if record is not None and agent.depends_on and self._dependency_stale(agent):
                self._question_resolve(agent, record, 'cancelled', 'dependency_changed', clear=True)

    def _question_stop(self, run=None):
        for ident, record in tuple(self._questions.items()):
            if run is None or record['run'] is run:
                self._question_resolve(record['agent'], record, 'cancelled', 'stopped')
        tasks = [task for task, run_id in self._question_tasks.items() if run is None or run_id == run['id']]
        for task in tasks:
            if task is not asyncio.current_task() and not task.done() and not task.cancelling():
                task.cancel()
        return tasks

    def _restore_question_metadata(self, result):
        # Only opaque application IDs/enums are restored after output masking.
        # Question/recommendation/reason remain masked; no metadata grants tools.
        for agent, row in zip(self.agents.values(), result.get('agents', [])):
            if not agent.question_state or not row.get('question_state'):
                continue
            for key in ('question_id', 'kind', 'resolution'):
                row['question_state'][key] = agent.question_state[key]
        return result
