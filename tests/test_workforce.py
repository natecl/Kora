from __future__ import annotations

import unittest

from kora.workforce import (
    CapabilityBoundaryError,
    ModelRoute,
    ModelRouter,
    NoEligibleRouteError,
    PrivacyLevel,
    RiskLevel,
    RoleCharter,
    RouteObservation,
    RouteObservationStats,
    TaskProfile,
    UnavailableCapabilityError,
    WorkforceCompiler,
    WorkforceValidationError,
)


class WorkforceTests(unittest.TestCase):
    def _charter(
        self,
        *,
        role_id: str = "role-founder",
        title: str = "Product owner",
        allowed_capabilities: frozenset[str] | set[str] = frozenset(
            {"discover", "implement", "review", "reconcile", "report"}
        ),
        default_quality_floor: float = 0.8,
        max_concurrency: int = 2,
    ) -> RoleCharter:
        return RoleCharter(
            role_id=role_id,
            title=title,
            responsibilities=("Advance the approved mission",),
            non_responsibilities=("Change the overarching objective",),
            allowed_capabilities=allowed_capabilities,
            authority_constraints=("Never grant authority", "Stay within scope"),
            default_quality_floor=default_quality_floor,
            max_concurrency=max_concurrency,
        )

    def _task(self, **overrides: object) -> TaskProfile:
        values: dict[str, object] = {
            "task_id": "task-1",
            "task_class": "bounded-analysis",
            "objective": "Analyze the approved evidence and return a recommendation.",
            "required_capabilities": frozenset({"discover"}),
            "required_tools": frozenset({"search"}),
            "risk": RiskLevel.MEDIUM,
            "ambiguity": 0.25,
            "privacy": PrivacyLevel.PRIVATE,
            "estimated_input_tokens": 100_000,
            "estimated_output_tokens": 20_000,
            "required_context_tokens": 50_000,
            "quality_floor": 0.8,
            "reliability_floor": 0.85,
            "evidence_requirements": ("source citations",),
            "max_latency_ms": 1_000.0,
            "max_cost_usd": 1.0,
        }
        values.update(overrides)
        return TaskProfile(**values)  # type: ignore[arg-type]

    def _route(self, route_id: str = "route", **overrides: object) -> ModelRoute:
        values: dict[str, object] = {
            "route_id": route_id,
            "provider_ref": "private-provider",
            "model_ref": "private-model",
            "supported_capabilities": frozenset({"discover", "implement", "review"}),
            "supported_tools": frozenset({"search"}),
            "privacy_support": PrivacyLevel.PRIVATE,
            "context_window": 100_000,
            "predicted_quality": 0.95,
            "reliability": 0.95,
            "input_cost_per_million": 1.0,
            "output_cost_per_million": 2.0,
            "fixed_cost_usd": 0.10,
            "predicted_latency_ms": 500.0,
            "enabled": True,
        }
        values.update(overrides)
        return ModelRoute(**values)  # type: ignore[arg-type]

    def test_privacy_and_risk_levels_have_stable_order(self) -> None:
        self.assertLess(
            PrivacyLevel.EXTERNAL_OK.rank,
            PrivacyLevel.PRIVATE.rank,
        )
        self.assertLess(PrivacyLevel.PRIVATE.rank, PrivacyLevel.LOCAL_ONLY.rank)
        self.assertEqual(
            [level.rank for level in RiskLevel],
            [0, 1, 2, 3],
        )

    def test_founder_and_finance_charters_use_the_same_schema(self) -> None:
        founder = self._charter(
            role_id="founder-role",
            title="Founder coworker",
            allowed_capabilities={"discover", "implement", "review"},
        )
        finance = self._charter(
            role_id="finance-role",
            title="Finance coworker",
            allowed_capabilities={"reconcile", "report"},
        )
        compiler = WorkforceCompiler(max_attempts=2, max_concurrency=1)
        founder_task = self._task(
            task_id="founder-task",
            task_class="product-discovery",
            required_capabilities={"discover"},
            required_tools=set(),
            evidence_requirements=("research notes",),
            objective="Assess the approved product opportunity.",
        )
        finance_task = self._task(
            task_id="finance-task",
            task_class="monthly-reconciliation",
            required_capabilities={"reconcile"},
            required_tools=set(),
            evidence_requirements=("reconciliation report",),
            objective="Reconcile the approved monthly ledger.",
        )

        founder_envelope = compiler.compile(
            founder,
            "Advance the approved product mission.",
            founder_task,
            {"discover"},
        )
        finance_envelope = compiler.compile(
            finance,
            {"objective": "Close the approved finance mission."},
            finance_task,
            {"reconcile"},
        )

        self.assertEqual(founder_envelope.task_id, "founder-task")
        self.assertEqual(finance_envelope.task_id, "finance-task")
        self.assertEqual(founder_envelope.objective, founder_task.objective)
        self.assertEqual(finance_envelope.objective, finance_task.objective)
        self.assertEqual(founder_envelope.role_id, "founder-role")
        self.assertEqual(finance_envelope.role_id, "finance-role")
        self.assertEqual(founder_envelope.max_attempts, 2)
        self.assertEqual(founder_envelope.max_concurrency, 1)
        self.assertNotEqual(founder_envelope.role_label, finance_envelope.role_label)
        self.assertEqual(
            founder_envelope,
            compiler.compile(
                founder,
                "A different wording does not alter the task boundary.",
                founder_task,
                {"discover"},
            ),
        )

    def test_compiler_enforces_charter_and_available_capabilities(self) -> None:
        compiler = WorkforceCompiler()
        task = self._task(required_capabilities={"unapproved"})
        with self.assertRaises(CapabilityBoundaryError):
            compiler.compile(self._charter(), "Mission objective", task, {"unapproved"})

        task = self._task(required_capabilities={"discover"})
        with self.assertRaises(UnavailableCapabilityError):
            compiler.compile(self._charter(), "Mission objective", task, {"review"})

    def test_envelope_id_is_deterministic_and_changes_with_capabilities(self) -> None:
        charter = self._charter()
        compiler = WorkforceCompiler()
        task = self._task(
            required_tools=set(),
            estimated_input_tokens=0,
            estimated_output_tokens=0,
        )
        first = compiler.compile(charter, "Mission objective", task, {"discover"})
        second = compiler.compile(charter, "Mission objective", task, {"discover"})
        changed = compiler.compile(
            charter,
            "Mission objective",
            self._task(required_capabilities={"discover", "review"}),
            {"discover", "review"},
        )
        self.assertEqual(first.envelope_id, second.envelope_id)
        self.assertNotEqual(first.envelope_id, changed.envelope_id)

    def test_compiler_strictly_checks_available_tools_when_catalogued(self) -> None:
        task = self._task(required_tools={"search"})
        with self.assertRaisesRegex(WorkforceValidationError, "tools"):
            WorkforceCompiler().compile(
                self._charter(),
                "Mission objective",
                task,
                {"discover": {"tools": {"other-tool"}}},
            )

    def test_exact_attempt_cost_and_expected_cost_math(self) -> None:
        task = self._task(
            estimated_input_tokens=2_000_000,
            estimated_output_tokens=500_000,
            required_tools=set(),
        )
        route = self._route(
            "priced",
            supported_tools=set(),
            fixed_cost_usd=0.25,
            input_cost_per_million=1.5,
            output_cost_per_million=4.0,
        )
        self.assertEqual(ModelRouter.attempt_cost(task, route), 5.25)
        self.assertEqual(route.attempt_cost(task), 5.25)
        task = self._task(
            estimated_input_tokens=0,
            estimated_output_tokens=0,
            required_tools=set(),
        )
        route = self._route(
            "probability",
            supported_tools=set(),
            fixed_cost_usd=0.8,
            predicted_quality=0.8,
            reliability=0.5,
        )
        self.assertAlmostEqual(
            ModelRouter.expected_cost_per_accepted_outcome(task, route),
            2.0,
        )

    def test_router_uses_expected_cost_and_deterministic_tie_breaking(self) -> None:
        task = self._task(
            required_tools=set(),
            estimated_input_tokens=0,
            estimated_output_tokens=0,
        )
        cheap = self._route(
            "cheap",
            supported_tools=set(),
            fixed_cost_usd=0.10,
            predicted_quality=0.90,
            reliability=0.90,
        )
        expensive = self._route(
            "expensive",
            supported_tools=set(),
            fixed_cost_usd=0.20,
            predicted_quality=0.99,
            reliability=0.99,
        )
        decision = ModelRouter([expensive, cheap]).select(task)
        self.assertEqual(decision.route_id, "cheap")
        self.assertAlmostEqual(decision.expected_attempt_cost_usd, 0.10)
        self.assertAlmostEqual(
            decision.expected_cost_per_accepted_outcome,
            0.10 / (0.90 * 0.90),
        )

        tied_a = self._route(
            "a-route",
            supported_tools=set(),
            fixed_cost_usd=0.10,
            predicted_latency_ms=400.0,
        )
        tied_b = self._route(
            "b-route",
            supported_tools=set(),
            fixed_cost_usd=0.10,
            predicted_latency_ms=400.0,
        )
        self.assertEqual(ModelRouter([tied_b, tied_a]).select(task).route_id, "a-route")

    def test_quality_and_reliability_floors_reject_routes(self) -> None:
        task = self._task(
            required_tools=set(),
            quality_floor=0.9,
            reliability_floor=0.9,
        )
        router = ModelRouter(
            [
                self._route(
                    "too-weak",
                    supported_tools=set(),
                    predicted_quality=0.89,
                    reliability=0.99,
                ),
                self._route(
                    "unreliable",
                    supported_tools=set(),
                    predicted_quality=0.99,
                    reliability=0.89,
                ),
            ]
        )
        with self.assertRaises(NoEligibleRouteError) as caught:
            router.select(task)
        self.assertEqual(caught.exception.reasons["too-weak"], ("quality_floor",))
        self.assertEqual(
            caught.exception.reasons["unreliable"], ("reliability_floor",)
        )

    def test_router_applies_capability_tool_privacy_context_latency_and_cost_filters(
        self,
    ) -> None:
        task = self._task(
            required_capabilities={"discover"},
            required_tools={"search"},
            privacy=PrivacyLevel.LOCAL_ONLY,
            required_context_tokens=200_000,
            max_latency_ms=100.0,
            max_cost_usd=0.05,
            quality_floor=0.9,
            reliability_floor=0.9,
        )
        routes = [
            self._route("disabled", enabled=False),
            self._route("capability", supported_capabilities={"review"}),
            self._route("tool", supported_tools={"other"}),
            self._route("privacy", privacy_support=PrivacyLevel.PRIVATE),
            self._route("context", context_window=10),
            self._route("latency", predicted_latency_ms=101.0),
            self._route("cost", fixed_cost_usd=0.06),
            self._route("quality", predicted_quality=0.89),
            self._route("reliability", reliability=0.89),
        ]
        with self.assertRaises(NoEligibleRouteError) as caught:
            ModelRouter(routes).select(task)
        reasons = caught.exception.reasons
        self.assertIn("disabled", reasons["disabled"])
        self.assertIn("missing_capabilities", reasons["capability"])
        self.assertIn("missing_tools", reasons["tool"])
        self.assertIn("privacy", reasons["privacy"])
        self.assertIn("context", reasons["context"])
        self.assertIn("latency_ceiling", reasons["latency"])
        self.assertIn("attempt_cost_ceiling", reasons["cost"])
        self.assertIn("quality_floor", reasons["quality"])
        self.assertIn("reliability_floor", reasons["reliability"])

    def test_fallback_excludes_prior_route_and_preserves_task_constraints(self) -> None:
        task = self._task(
            required_tools=set(),
            privacy=PrivacyLevel.PRIVATE,
            required_context_tokens=50_000,
            quality_floor=0.8,
            reliability_floor=0.85,
            max_latency_ms=1_000.0,
            max_cost_usd=1.0,
        )
        first = self._route("first", supported_tools=set(), fixed_cost_usd=0.10)
        fallback = self._route(
            "fallback",
            supported_tools=set(),
            fixed_cost_usd=0.30,
            predicted_quality=0.99,
            reliability=0.99,
            predicted_latency_ms=800.0,
        )
        router = ModelRouter([first, fallback])
        selected = router.select(task)
        escalated = router.fallback(task, {selected.route_id})
        self.assertEqual(selected.route_id, "first")
        self.assertEqual(escalated.route_id, "fallback")
        self.assertEqual(escalated.task_id, task.task_id)
        self.assertIn("privacy_satisfied", escalated.rationale_codes)
        self.assertIn("quality_floor_met", escalated.rationale_codes)
        self.assertIn("reliability_floor_met", escalated.rationale_codes)
        self.assertIn("attempt_cost_within_ceiling", escalated.rationale_codes)

        with self.assertRaises(NoEligibleRouteError) as caught:
            router.fallback(task, {selected.route_id, escalated.route_id})
        self.assertEqual(
            caught.exception.excluded_route_ids,
            frozenset({"first", "fallback"}),
        )

    def test_concurrency_and_budget_bounds_are_enforced_without_provider_calls(self) -> None:
        task = self._task(
            required_tools=set(),
            max_cost_usd=1.0,
            estimated_input_tokens=0,
            estimated_output_tokens=0,
        )
        route = self._route("bounded", supported_tools=set(), fixed_cost_usd=0.10)
        router = ModelRouter([route], max_concurrency=1, budget_ceiling_usd=0.40)
        decision = router.select(task)
        reservation = router.reserve(decision, reservation_id="attempt-1")
        self.assertEqual(router.active_concurrency, 1)
        with self.assertRaises(NoEligibleRouteError) as caught:
            router.select(task)
        self.assertEqual(caught.exception.reasons["bounded"], ("concurrency_limit",))
        router.release(reservation, actual_cost_usd=0.10)
        self.assertEqual(router.active_concurrency, 0)
        self.assertEqual(router.spent_cost_usd, 0.10)
        router.select(task)

        another = ModelRouter([route], budget_ceiling_usd=0.20)
        another_decision = another.select(task)
        another.reserve(another_decision, reservation_id="attempt-2")
        with self.assertRaises(NoEligibleRouteError) as caught:
            another.select(task)
        self.assertEqual(caught.exception.reasons["bounded"], ("budget_ceiling",))

    def test_route_observations_aggregate_without_changing_routing(self) -> None:
        stats = RouteObservationStats()
        stats.record(RouteObservation("route-a", "analysis", True, 100, 0.10, 40))
        stats.record(RouteObservation("route-a", "analysis", False, 200, 0.20, 60))
        summary = stats.aggregate("route-a", "analysis")
        self.assertEqual(summary.sample_count, 2)
        self.assertEqual(summary.accepted_count, 1)
        self.assertEqual(summary.total_tokens, 300)
        self.assertAlmostEqual(summary.acceptance_rate, 0.5)
        self.assertAlmostEqual(summary.mean_cost_usd, 0.15)
        self.assertAlmostEqual(summary.mean_latency_ms, 50.0)

        task = self._task(required_tools=set())
        cheap = self._route("cheap", supported_tools=set(), fixed_cost_usd=0.10)
        expensive = self._route("expensive", supported_tools=set(), fixed_cost_usd=0.20)
        router = ModelRouter([expensive, cheap], observation_stats=stats)
        before = router.select(task)
        router.record_observation(RouteObservation("cheap", task.task_class, False, 1, 9, 1))
        after = router.select(task)
        self.assertEqual(before, after)
        self.assertEqual(len(router.observations), 3)

    def test_contract_validation_rejects_invalid_scores_and_bounds(self) -> None:
        with self.assertRaises(WorkforceValidationError):
            self._task(quality_floor=1.01)
        with self.assertRaises(WorkforceValidationError):
            self._task(estimated_input_tokens=-1)
        with self.assertRaises(WorkforceValidationError):
            self._charter(max_concurrency=0)
        with self.assertRaises(WorkforceValidationError):
            self._route(predicted_quality=-0.1)


if __name__ == "__main__":
    unittest.main()
