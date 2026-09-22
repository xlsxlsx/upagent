"""Chat runner: executes the `agent` pipeline and streams events to the UI."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from agent.communication.event import Event, EventType
from agent.runner import run_llm_project


class ChatRunner:
    """Runs one agent task per thread and emits chat events through a broker."""

    def __init__(self, broker, get_workspace: Callable[[], Path]) -> None:
        self._broker = broker
        self._get_workspace = get_workspace
        self._threads: dict[int, threading.Thread] = {}

    def start(self, run_id: int, goal: str, tech_stack: str, app) -> None:
        """Start the agent in a background thread; returns immediately."""
        thread = threading.Thread(
            target=self._run,
            args=(run_id, goal, tech_stack, app),
            name=f"agent-run-{run_id}",
            daemon=True,
        )
        self._threads[run_id] = thread
        thread.start()

    def _run(self, run_id: int, goal: str, tech_stack: str, app) -> None:
        broker = self._broker
        try:
            broker.emit(run_id, "system", "解析目标并生成执行计划…")
            provider = app.provider()
            events = _event_bus_for(broker, run_id)
            outcome = run_llm_project(
                goal,
                tech_stack,
                provider=provider,
                workspace=self._get_workspace(),
                output_dir=self._get_workspace(),
                events=events,
                step_observer=lambda agent_name, entry: broker.emit(
                    run_id, "step", f"{agent_name} · {entry}"
                ),
            )
            broker.emit(run_id, "done", outcome.summary())
            if outcome.report_path:
                broker.emit(run_id, "system", f"终审报告: {outcome.report_path}")
        except Exception as exc:  # noqa: BLE001 - surface any failure in the chat panel
            broker.emit(run_id, "error", f"执行失败: {exc}")
        finally:
            app.clear_active_run(run_id)
            broker.close(run_id)


def _event_bus_for(broker, run_id: int):
    """EventBus that forwards plan/review events into the chat stream."""
    from agent.communication.event import EventBus

    bus = EventBus()
    labels = {
        EventType.PLAN_CREATED: "执行计划已生成",
        EventType.TASK_ASSIGNED: "开始任务",
        EventType.REVIEW_PASSED: "审查通过",
        EventType.REVIEW_FAILED: "审查未通过",
        EventType.PHASE_ROLLED_BACK: "阶段回退",
        EventType.DELIVERY_ACCEPTED: "交付通过",
        EventType.DELIVERY_REJECTED: "交付被拒绝",
    }
    for event_type, label in labels.items():
        bus.subscribe(
            event_type,
            _make_forwarder(broker, run_id, event_type, label),
        )
    return bus


def _make_forwarder(broker, run_id: int, event_type: EventType, label: str):
    def forward(event: Event) -> None:
        if event_type in {
            EventType.REVIEW_PASSED,
            EventType.REVIEW_FAILED,
            EventType.TASK_ASSIGNED,
            EventType.PHASE_ROLLED_BACK,
        }:
            broker.emit(run_id, "task", f"{label}: {event.payload}")
        else:
            broker.emit(run_id, "system", f"{label}")

    return forward
