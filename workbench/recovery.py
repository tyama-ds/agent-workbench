"""Parent-directed, bounded recovery of a rejected output-limit response.

A worker ID is a persistent assignment slot. Replacing its executor changes the
allowed profile, never its authority, evidence, ancestry or consumed budgets.
"""
import copy
import time

from .config import text
from .context import groups, request_size

WORKER_RECOVERY_LIMIT = 2
RUN_RECOVERY_LIMIT = 4
RECOVERY_POLICY = '''
Output-limit recovery: A worker_error with stop_reason=provider_output_limit
means that response was rejected before any of its tools ran. Earlier successful
operations may still exist: inspect receipts/current files before repeating work.
The direct parent decides: recover_worker(action=split) gives the same executor
one smaller concrete next task; action=handoff replaces that slot's executor with
a DIFFERENT allowed worker profile and carries forward the task and evidence.
Include the required input, remaining deliverable and verification in task. Keep
the original assignment's outstanding work; a small subtask is not full completion.
Use the current failure_id from list_team. The same worker ID, hierarchy and
budgets remain. At most 2 recoveries per worker and 4 per run, also charged to the
shared collaboration budget. Never repeat an accepted recovery or infer success
from queueing. At exhaustion explain the blocker and ask the human; do not spin,
increase budgets or spawn replacements to evade the cap. Normal mail does not
restart an error worker. Truncated responses never authorize tools or completion.
'''


def recovery_view(agent):
    return {'failure_id': agent.output_limit_failures, 'attempts': agent.recovery_attempts,
            'max_attempts': WORKER_RECOVERY_LIMIT,
            'remaining': max(0, WORKER_RECOVERY_LIMIT - agent.recovery_attempts),
            'history': copy.deepcopy(agent.recovery_history)}


class WorkerRecoveryMixin:
    def _recover_worker(self, run, actor, args):
        if (self.runs.get(run['id']) is not run or self.agents.get(actor.id) is not actor
                or actor.run_id != run['id'] or actor.id not in run['agent_ids']
                or self.closed or actor.closing or actor.question
                or actor.status in {'error', 'stopped', 'stopping', 'done'}
                or run['status'] in {'stopped', 'stopping', 'done'}):
            raise ValueError('稼働中の直属の親だけが復旧を判断できます')
        if run.get('_ordered_work') or run.get('_ordered_reference'):
            raise ValueError('順番のある仕事の手番はこの復旧操作で変更できません')
        ident = text(args['worker_id'], 'worker_id', 100, False)
        target = self.agents.get(ident)
        if (target is None or target.run_id != run['id'] or ident not in run['agent_ids']
                or target.parent_id != actor.id or self._formation_reviewer(run, target)):
            raise ValueError('同じ仕事の自分の直属workerを指定してください')
        failure = args['failure_id']
        if (type(failure) is not int or failure < 1 or failure != target.output_limit_failures
                or target.status != 'error' or target.stop_reason != 'provider_output_limit'
                or target.closing or target.question or target.task is not None and not target.task.done()):
            raise ValueError('現在の出力上限エラーとfailure_idを確認してください。受理済み復旧の再送は不要です')
        if any(human for _, human in target.pending):
            raise ValueError('未処理の人の指示があります。自動復旧で先回りせず、人の指示による再開を待ってください')
        if (target.recovery_attempts >= WORKER_RECOVERY_LIMIT
                or run.get('worker_recoveries', 0) >= RUN_RECOVERY_LIMIT):
            return {'ok': False, 'code': 'worker_recovery_limit', 'requires_human': True,
                    'error': '自動復旧の上限（担当2回・仕事全体4回）です。再試行せず、残る作業と保存済み成果を人に報告してください。'}
        action = args['action']
        task = text(args['task'], 'recovery task', 8000, False)
        profile = args.get('profile_id', target.profile_id)
        if action not in {'split', 'handoff'} or action == 'split' and 'profile_id' in args:
            raise ValueError('splitには小さい次の作業だけを指定し、handoffには別のprofile_idを指定してください')
        if (action == 'handoff' and ('profile_id' not in args or profile == target.profile_id)
                or profile not in run['worker_profiles']):
            raise ValueError('担当交代にはこの仕事で許可済みの別のworker APIを指定してください')
        eligibility = self.message_eligibility(target)
        if not eligibility['allowed']:
            raise ValueError(eligibility['message'])
        self._check_run_budget(run, tools=True)
        self._check_collaboration(run, actor)
        self._check_queue(target)
        if not self._hierarchy_ancestors_ready(target) or self._dependency_blockers(target):
            raise ValueError('上位担当と前工程の現在の承認を確認してから復旧してください')
        # A complete prior tool batch may have saved files before a later length
        # response. Preserve its canonical results, never replay native envelopes
        # into another provider or mutate shared original_history records.
        conversation = target.conversation
        if action == 'handoff':
            conversation = copy.deepcopy(conversation)
            for row in conversation:
                row.pop('provider_raw', None)
            groups(conversation)  # Reject an incomplete tool/result boundary.
            selected = next(p for p in run['_config']['providers'] if p['id'] == profile)
            request_size(selected, conversation, [], '')  # Protocol validation only.
        record = {'attempt': target.recovery_attempts + 1, 'failure_id': failure,
                  'action': action, 'from_profile_id': target.profile_id, 'to_profile_id': profile,
                  'task': task, 'error': target.last_error, 'at': time.time()}
        self._redact_tree(record)  # All fallible masks before accepting delivery.
        content = ('PM-directed output-limit recovery. Original assignment remains outstanding. '
                   'Earlier successful tool results remain evidence; the rejected response executed no tools. '
                   'Check existing outputs before edits. Next bounded task and checks:\n' + task)
        receipt = self._mail(actor, target, content, subject='出力上限からの復旧: ' + action)
        # _mail is synchronous and leaves an error target asleep. Commit once,
        # before the scheduler can dispatch anything or notifications can fail.
        target.recovery_attempts += 1
        run['worker_recoveries'] = run.get('worker_recoveries', 0) + 1
        target.recovery_history.append(record)
        target.profile_id = profile
        target.conversation = conversation
        if action == 'handoff':
            target._provider_observation = None  # Old call must not appear under the new profile.
        for index, (body, human) in enumerate(target.pending):
            if not human and target.pending_mail_metadata.get(body, {}).get('mail_id') == receipt['mail_id']:
                item = target.pending[index]
                del target.pending[index]
                target.pending.appendleft(item)
                break
        target.last_error = target.stop_reason = ''
        target.status = 'queued'
        try:
            self._dependency_reassign(actor, target, receipt)
            self.kick(target)
            run['status'] = 'running'
            self.log(target, 'notice', f'PMによる復旧 {target.recovery_attempts}/{WORKER_RECOVERY_LIMIT}: '
                     f'{action} / {record["from_profile_id"]} → {profile}。担当ID・履歴・消費予算を維持。')
            self._persist_run(run['id'])
        except Exception:
            receipt['warning'] = '復旧は受理済みです。通知処理に問題があります。再送せず状態を確認してください。'
        return {**receipt, 'worker_id': target.id, 'action': action, 'profile_id': profile,
                'recovery': recovery_view(target), 'run_recoveries': run['worker_recoveries'],
                'run_recovery_limit': RUN_RECOVERY_LIMIT}
