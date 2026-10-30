"""Opt-in worker prerequisites, bound to current formal reports and PM reviews.

These gates do not undo a file/tool operation that already started. Old outputs
remain observations; invalidation removes their authority as current results.
"""
class DependencyBlocked(ValueError):
    def __init__(self, stale=False):
        self.code = 'dependency_stale' if stale else 'dependency_wait'
        super().__init__('前工程が更新されたため成果は失効しています。前工程の再承認後、PMのsend_messageで再依頼してください。'
                         if stale else '前工程の現在の正式報告がPMに承認されるまで待機しています。')


class WorkerDependenciesMixin:
    def _dependency_ids(self, run, pm, values):
        if not isinstance(values, list) or len(values) > 16 or any(not isinstance(x, str) for x in values):
            raise ValueError('depends_on は既存の自分のworker IDを最大16件指定してください')
        if len(values) != len(set(values)):
            raise ValueError('depends_on のIDは重複できません')
        if values and (run.get('_ordered_work') or any(getattr(self.agents[x], '_ordered_initial_wait', False)
                                                      for x in run['agent_ids'])):
            raise ValueError('depends_on と順番のある仕事は併用できません')
        for ident in values:
            child = self.agents.get(ident)
            if (child is None or child.run_id != run['id'] or ident not in run['agent_ids']
                    or child.parent_id != pm.id or child.closing or child.status == 'stopped'):
                raise ValueError('depends_on は同じ作業・同じPMの既存workerだけを指定できます')
        # Only older workers can be named; dependencies have no mutation tool.
        return tuple(values)

    def _dependency_current_report(self, run, child, seen=None):
        seen = set() if seen is None else seen
        if child.id in seen:
            return False
        seen = seen | {child.id}
        pm = self.agents.get(child.parent_id)
        revision = child.result_revision
        if (pm is None or child.run_id != run['id'] or child.id not in run['agent_ids']
                or pm.id not in run['pm_agent_ids'] or child.closing or child.status != 'done'
                or child.pending or child.question or child.last_error or child.dependency_stale
                or child.finished_revision != revision or revision < 1
                or pm.worker_report_deliveries.get(child.id) != revision
                or pm.worker_report_consumed.get(child.id) != revision
                or pm.worker_report_reviews.get(child.id) != {'result_revision': revision, 'decision': 'accept'}):
            return False
        for ident in child.depends_on:
            upstream = self.agents.get(ident)
            if (upstream is None or upstream.parent_id != child.parent_id
                    or child.dependency_revisions.get(ident) != upstream.result_revision
                    or not self._dependency_current_report(run, upstream, seen)):
                return False
        return True

    def _dependency_blockers(self, agent):
        run = self.runs[agent.run_id]
        return [ident for ident in agent.depends_on if ident not in self.agents
                or not self._dependency_current_report(run, self.agents[ident])]

    def _dependency_vector(self, agent):
        return {ident: self.agents[ident].result_revision for ident in agent.depends_on}

    def _dependency_stale(self, agent):
        return bool(agent.dependency_stale or (agent.dependency_revisions and
                    agent.dependency_revisions != self._dependency_vector(agent)))

    def _dependency_view(self, agent):
        if not agent.depends_on:
            return None
        return {'depends_on': list(agent.depends_on), 'blocked_by': self._dependency_blockers(agent),
                'stale': self._dependency_stale(agent), 'accepted_revisions': dict(agent.dependency_revisions)}

    def _dependency_retry_index(self, agent):
        if not agent.dependency_retry_mail:
            return None
        return next((i for i, (content, human) in enumerate(agent.pending) if not human
                     and agent.pending_mail_metadata.get(content, {}).get('mail_id') == agent.dependency_retry_mail), None)

    def _dependency_can_start(self, agent):
        return not agent.depends_on or (not self._dependency_blockers(agent)
            and (not self._dependency_stale(agent) or self._dependency_retry_index(agent) is not None))

    def _dependency_require(self, agent):
        if agent.depends_on and (not agent.dependency_revisions or self._dependency_stale(agent) or self._dependency_blockers(agent)
                or (getattr(agent, '_dependency_turn_epoch', agent.dependency_epoch) != agent.dependency_epoch)):
            raise DependencyBlocked(self._dependency_stale(agent))

    def _dependency_begin(self, agent):
        if not agent.depends_on:
            return
        if not self._dependency_can_start(agent):
            raise DependencyBlocked(self._dependency_stale(agent))
        if self._dependency_stale(agent):
            # Consume the exact accepted PM reassignment first. Keep all other
            # inputs and their relative order; human/peer text alone cannot resume.
            index = self._dependency_retry_index(agent)
            item = agent.pending[index]
            del agent.pending[index]
            agent.pending.appendleft(item)
            agent.dependency_stale = False
            agent.dependency_retry_mail = ''
        agent.dependency_revisions = self._dependency_vector(agent)
        agent._dependency_turn_epoch = agent.dependency_epoch

    def _dependency_invalidate(self, changed):
        run = self.runs[changed.run_id]
        affected, frontier = set(), {changed.id}
        while frontier:
            following = {ident for ident in run['agent_ids'] if ident not in affected
                         and set(self.agents[ident].depends_on) & frontier}
            affected.update(following)
            frontier = following
        for ident in affected:
            child = self.agents[ident]
            if not child.dependency_revisions:
                continue  # Initial waiting assignment has never used old input.
            child.dependency_epoch += 1
            child.dependency_stale = True
            child.dependency_retry_mail = ''
            child.result_revision += 1
            child.finished_revision = None
            pm = self.agents[child.parent_id]
            pm.worker_report_reviews.pop(ident, None)
            pm.worker_report_deliveries.pop(ident, None)
            pm.worker_report_consumed.pop(ident, None)
            pm.finished_revision = None
            if pm.status == 'done':
                pm.status = 'idle'
            if child.status not in {'working', 'stopped', 'error'}:
                child.status = 'idle'

    def _dependency_reassign(self, actor, target, receipt):
        if (target.depends_on and self._dependency_stale(target) and actor.id == target.parent_id
                and receipt.get('queued') is True and not self._dependency_blockers(target)):
            target.dependency_retry_mail = receipt['mail_id']
            try:
                self.kick(target)
            except Exception:
                # The explicit reassignment mail was already accepted. Never
                # report it as undelivered or invite a duplicate send.
                receipt['warning'] = '再依頼は受理済みですが起動通知に問題がありました。再送せず状態を確認してください。'

    def _dependency_wake(self, run, pm):
        for child in self._owned_workers(run, pm):
            if child.depends_on:
                self.kick(child)

    def _dependency_pm_issue(self, run, pm):
        children = self._owned_workers(run, pm)
        if pm.parent_id is not None or not any(child.depends_on for child in children):
            return None
        if not all(self._dependency_current_report(run, child) for child in children):
            return ('worker_dependency_pending', '依存する工程があります。全workerの現在の正式報告を確認・承認してから完了してください。')
        return None
