"""Bounded delegation units, rooted in immutable application parent links."""


class UnitChanged(ValueError):
    code = 'unit_stale'

    def __init__(self):
        super().__init__('担当ユニットの前提が変わりました。現在の子報告・親の再依頼を確認してください。既実行操作は取り消していません。')


class AgentHierarchyMixin:
    def _hierarchy_lineage(self, run, agent):
        lineage, seen, current = [], set(), agent
        for _ in range(4):
            if (current.id in seen or self.agents.get(current.id) is not current
                    or current.run_id != run['id'] or current.id not in run['agent_ids']):
                raise ValueError('担当の親子関係が不正です')
            seen.add(current.id)
            lineage.append(current)
            if current.parent_id is None:
                if current.id not in run['pm_agent_ids'] and not self._formation_reviewer(run, current):
                    raise ValueError('ユニットの起点PMが一致しません')
                return lineage
            current = self.agents.get(current.parent_id)
            if current is None:
                break
        raise ValueError('委任の親子関係が深さ上限を超えています')

    def _hierarchy_nested(self, run):
        return any(self.agents[x].parent_id in self.agents
                   and self.agents[self.agents[x].parent_id].parent_id is not None for x in run['agent_ids'])

    def _hierarchy_dependency_epochs(self, agent):
        return {parent.id: parent.dependency_epoch for parent in self._hierarchy_lineage(self.runs[agent.run_id], agent)[1:]
                if parent.depends_on}

    def _hierarchy_stale(self, agent):
        return getattr(agent, '_unit_dependency_epochs', {}) != self._hierarchy_dependency_epochs(agent)

    def _hierarchy_retry_index(self, agent):
        ident = getattr(agent, '_unit_retry_mail', '')
        return next((i for i, (content, human) in enumerate(agent.pending)
                     if ident and not human and agent.pending_mail_metadata.get(content, {}).get('mail_id') == ident), None)

    def _hierarchy_ancestors_ready(self, agent):
        for parent in self._hierarchy_lineage(self.runs[agent.run_id], agent)[1:]:
            if (parent.closing or parent.status in {'stopped', 'stopping', 'error'}
                    or (parent.depends_on and (not parent.dependency_revisions
                        or self._dependency_stale(parent) or self._dependency_blockers(parent)))):
                return False
        return True

    def _hierarchy_can_start(self, agent):
        return self._hierarchy_ancestors_ready(agent) and (not self._hierarchy_stale(agent)
                                                          or self._hierarchy_retry_index(agent) is not None)

    def _hierarchy_require(self, agent):
        if (not self._hierarchy_ancestors_ready(agent) or self._hierarchy_stale(agent)
                or getattr(agent, '_unit_turn_epoch', getattr(agent, '_unit_epoch', 0)) != getattr(agent, '_unit_epoch', 0)):
            raise UnitChanged()

    def _hierarchy_begin(self, agent):
        if not self._hierarchy_can_start(agent):
            raise UnitChanged()
        if self._hierarchy_stale(agent):
            index = self._hierarchy_retry_index(agent)
            item = agent.pending[index]
            del agent.pending[index]
            agent.pending.appendleft(item)
            agent._unit_retry_mail = ''
        agent._unit_dependency_epochs = self._hierarchy_dependency_epochs(agent)
        agent._unit_turn_epoch = getattr(agent, '_unit_epoch', 0)

    def _hierarchy_reassign(self, actor, target, receipt):
        if (actor.id == target.parent_id and self._hierarchy_stale(target) and receipt.get('queued') is True
                and self._hierarchy_ancestors_ready(target) and not self._dependency_blockers(target)):
            target._unit_retry_mail = receipt['mail_id']
            try:
                self.kick(target)
            except Exception:
                receipt['warning'] = '再依頼は受理済みです。起動状態を確認し、同じメールを再送しないでください。'

    def _hierarchy_clear_report(self, agent):
        agent.finished_revision = None
        parent = self.agents.get(agent.parent_id)
        if parent is not None:
            for field in ('worker_report_reviews', 'worker_report_deliveries', 'worker_report_consumed'):
                getattr(parent, field).pop(agent.id, None)
        if agent.status == 'done':
            agent.status = 'idle'
        agent.waiting_for_workers = bool(self._owned_workers(self.runs[agent.run_id], agent))

    def _hierarchy_invalidate_ancestors(self, changed, seen):
        run = self.runs[changed.run_id]
        if not self._hierarchy_nested(run):
            return
        for parent in self._hierarchy_lineage(run, changed)[1:]:
            if parent.id in seen:
                continue
            parent.result_revision += 1
            parent._unit_epoch = getattr(parent, '_unit_epoch', 0) + 1
            self._hierarchy_clear_report(parent)
            self._dependency_invalidate(parent, _seen=seen)

    def _hierarchy_invalidate_descendants(self, changed, seen):
        run = self.runs[changed.run_id]
        for ident in run['agent_ids']:
            child = self.agents[ident]
            if not self._hierarchy_stale(child):
                continue
            signature = tuple(self._hierarchy_dependency_epochs(child).items())
            if getattr(child, '_unit_invalidated', None) == signature:
                continue
            child._unit_invalidated = signature
            child._unit_retry_mail = ''
            child.result_revision += 1
            child._unit_epoch = getattr(child, '_unit_epoch', 0) + 1
            self._hierarchy_clear_report(child)
            self._dependency_invalidate(child, _seen=seen)

    def _hierarchy_child_added(self, run, parent):
        self._formation_invalidate(parent, '新しい子担当により候補が失効しました。')
        if not self._hierarchy_nested(run):
            return
        previous = parent.result_revision
        parent.result_revision += 1
        self._hierarchy_clear_report(parent)
        # This deliberate tool action updates its caller's own current result.
        # Ancestors/in-flight teammates retain their original epoch binding.
        if getattr(parent, '_turn_revision', previous) == previous:
            parent._turn_revision = parent.result_revision
        self._dependency_invalidate(parent)

    def _hierarchy_report_ready(self, run, agent, seen=None):
        seen = set() if seen is None else seen
        if agent.id in seen or self._hierarchy_stale(agent) or not self._hierarchy_ancestors_ready(agent):
            return False
        seen = seen | {agent.id}
        return all(self._dependency_current_report(run, child, seen) for child in self._owned_workers(run, agent))

    def _hierarchy_unit_required(self, run, agent):
        children = self._owned_workers(run, agent)
        return bool(children and (agent.parent_id is not None or any(self._owned_workers(run, child) for child in children)))

    def _hierarchy_spawn_issue(self, run, agent):
        if self._formation_reviewer(run, agent):
            return '独立reviewerは委任できません'
        lineage = self._hierarchy_lineage(run, agent)
        if self.closed or agent.closing or agent.question or run['status'] in {'stopped', 'stopping', 'error', 'done'}:
            return '停止中・質問待ちの担当は増員できません'
        if len(lineage) - 1 >= run.get('max_delegation_depth', 1):
            return 'この仕事の委任の深さ上限のため増員できません'
        if run.get('_ordered_work') or (agent.parent_id and any(self.agents[x].participant_key
                or getattr(self.agents[x], '_ordered_initial_wait', False) for x in run['agent_ids'])):
            return '順番のある仕事は階層委任と併用できません'
        if not self._hierarchy_can_start(agent) or (agent.depends_on and (not agent.dependency_revisions
                or self._dependency_stale(agent) or self._dependency_blockers(agent))):
            return '担当の前提が未承認または失効しています'
        if getattr(agent, '_unit_turn_epoch', getattr(agent, '_unit_epoch', 0)) != getattr(agent, '_unit_epoch', 0):
            return '現在のユニット情報を確認してから委任してください'
        total = sum(self.agents[x].parent_id is not None or self._formation_reviewer(run, self.agents[x])
                    for x in run['agent_ids'])
        if total >= run['max_workers']:
            return 'この仕事の最大 worker 数に達しました。既存 worker に send_message で依頼してください'
        policy = self._orchestration(run['_config'], run)
        if policy['delegation_level'] == 2 and not run.get('adaptive_team'):
            reserved = sum(max(0, policy['workers_per_pm'] - len(self._owned_workers(run, self.agents[x])))
                           for x in run['pm_agent_ids'] if x != agent.id)
            if total + 1 > run['max_workers'] - reserved:
                return '他のPMの必要worker枠を確保しています。自分の既存workerを再利用してください。'
        return ''

    def _hierarchy_view(self, agent):
        run = self.runs[agent.run_id]
        lineage = self._hierarchy_lineage(run, agent)
        return {'depth': len(lineage) - 1, 'root_pm_id': lineage[-1].id, 'unit_id': agent.parent_id or agent.id,
                'direct_children': [child.id for child in self._owned_workers(run, agent)],
                'can_delegate': not bool(self._hierarchy_spawn_issue(run, agent))
                    and not (run.get('adaptive_team') and agent.id in run['pm_agent_ids'])}

    def _restore_hierarchy_metadata(self, result):
        for agent, row in zip(self.agents.values(), result.get('agents', [])):
            if self._formation_reviewer(self.runs[agent.run_id], agent):
                row.pop('hierarchy', None)
            else:
                row['hierarchy'] = self._hierarchy_view(agent)
        return result
