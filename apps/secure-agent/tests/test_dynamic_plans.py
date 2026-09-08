"""SP-01..08: lawful subsets and denial before tool materialization."""

import unittest
from dataclasses import asdict, replace

from secure_agent.contracts import (
    AgentError,
    TaskPlan,
    UserTask,
    canonical,
    strict_json,
)
from secure_agent.models import FixtureProvider
from secure_agent.routing import ModelRouter
from secure_agent.skills import SkillRegistry


class DynamicPlanTest(unittest.TestCase):
    def setUp(self):
        self.task = UserTask('Review selected files', 'example/repo', 'Review', ('README.md',), '/work/report.md')
        self.model = FixtureProvider(mode='test')
        self.raw = strict_json(canonical(asdict(self.model.plan(self.task, SkillRegistry.catalog()))))

    def test_sp01_sp02_sp03_valid_subsets(self):
        for output, count in [('research', 1), ('report', 2), ('delivery', 3)]:
            task = replace(self.task, requested_output=output)
            plan = ModelRouter(self.model).plan(task, SkillRegistry.catalog())
            self.assertEqual(len(plan.skills), count)
            self.assertEqual([s.name for s in plan.skills], [s['name'] for s in SkillRegistry.catalog()[:count]])

    def test_sp04_missing_dependency_is_not_repaired(self):
        for skills in ([self.raw['skills'][2]], self.raw['skills'][1:], self.raw['skills'][::-1]):
            with self.assertRaisesRegex(AgentError, 'plan_dependency_invalid'):
                TaskPlan.parse({**self.raw, 'skills': skills})

    def test_sp05_sp07_sp08_unknown_tool_and_authority_skills_denied(self):
        for name in ('secure-upload-to-dropbox', 'shell', 'web_fetch', 'approval', 'sign-intent'):
            with self.assertRaisesRegex(AgentError, 'skill_unregistered'):
                TaskPlan.parse({**self.raw, 'skills': [{'name': name, 'input': {}}]})

    def test_sp06_duplicate_denied(self):
        with self.assertRaisesRegex(AgentError, 'plan_skill_duplicate'):
            TaskPlan.parse({**self.raw, 'skills': self.raw['skills'][:1] * 2})

    def test_model_may_not_expand_research_only_operator_scope(self):
        class Expanding(FixtureProvider):
            def plan(self, task, catalog):
                return super().plan(replace(task, requested_output='delivery'), catalog)

        with self.assertRaisesRegex(AgentError, 'plan_exceeds_task_scope'):
            ModelRouter(Expanding(mode='test')).plan(replace(self.task, requested_output='research'), SkillRegistry.catalog())

    def test_model_may_not_drop_operator_required_delivery(self):
        class Truncating(FixtureProvider):
            def plan(self, task, catalog):
                return super().plan(replace(task, requested_output='research'), catalog)

        with self.assertRaisesRegex(AgentError, 'plan_goal_incomplete'):
            ModelRouter(Truncating(mode='test')).plan(self.task, SkillRegistry.catalog())

    def test_registry_is_closed_and_dependencies_are_explicit(self):
        registry = SkillRegistry.catalog()
        self.assertEqual([s['requires'] for s in registry], [[], ['secure-research'], ['secure-report']])
        for item in registry:
            self.assertTrue({'input_schema', 'output_schema', 'allowed_tools', 'security_requirements'} <= item.keys())
