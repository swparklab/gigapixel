import asyncio
import shutil
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..errors import WorkflowError
from ..models import Session as SessionModel, SourceImage
from .exporter import build_download_filename, resolve_optimized_image_path, resolve_raw_image_path
from .storage import node_upload_dir, node_upload_path, upload_dir
from .tasks import run_pipeline


class WorkflowExecutionError(WorkflowError):
    pass


EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


class GraphRunner:
    def __init__(self, db: Session, graph_payload: dict[str, Any], emit: EmitFn):
        self.db = db
        self.graph_payload = graph_payload
        self.emit = emit

        nodes = graph_payload.get("nodes") or []
        self.nodes_by_id: dict[int, dict[str, Any]] = {int(n["id"]): n for n in nodes if "id" in n}
        self.links = self._normalize_links(graph_payload.get("links") or [])
        self.incoming: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        self.flow_outgoing: dict[int, list[int]] = defaultdict(list)
        self.output_cache: dict[tuple[int, int], Any] = {}

        for link in self.links:
            target_key = (link["target_id"], link["target_slot"])
            self.incoming[target_key].append(link)
            if link["type"] == "flow":
                self.flow_outgoing[link["origin_id"]].append(link["target_id"])

        for key in self.incoming:
            self.incoming[key].sort(key=lambda x: x["id"])
        for key in self.flow_outgoing:
            self.flow_outgoing[key] = sorted(set(self.flow_outgoing[key]))

    @staticmethod
    def _normalize_links(raw_links: Any) -> list[dict[str, Any]]:
        links: list[dict[str, Any]] = []
        iterable = raw_links.values() if isinstance(raw_links, dict) else raw_links
        for item in iterable:
            if isinstance(item, dict):
                try:
                    links.append(
                        {
                            "id": int(item["id"]),
                            "type": str(item.get("type") or "any"),
                            "origin_id": int(item["origin_id"]),
                            "origin_slot": int(item["origin_slot"]),
                            "target_id": int(item["target_id"]),
                            "target_slot": int(item["target_slot"]),
                        }
                    )
                except Exception:
                    continue
            elif isinstance(item, (list, tuple)) and len(item) >= 6:
                try:
                    if isinstance(item[1], str):
                        # [id, type, origin_id, origin_slot, target_id, target_slot]
                        link = {
                            "id": int(item[0]),
                            "type": str(item[1] or "any"),
                            "origin_id": int(item[2]),
                            "origin_slot": int(item[3]),
                            "target_id": int(item[4]),
                            "target_slot": int(item[5]),
                        }
                    else:
                        # LiteGraph classic: [id, origin_id, origin_slot, target_id, target_slot, type]
                        link = {
                            "id": int(item[0]),
                            "type": str(item[5] or "any"),
                            "origin_id": int(item[1]),
                            "origin_slot": int(item[2]),
                            "target_id": int(item[3]),
                            "target_slot": int(item[4]),
                        }
                    links.append(
                        link
                    )
                except Exception:
                    continue
        return links

    def _node(self, node_id: int) -> dict[str, Any]:
        node = self.nodes_by_id.get(node_id)
        if not node:
            raise WorkflowExecutionError(f"Node not found: {node_id}")
        return node

    async def _node_state(self, node_id: int, state: str, message: str | None = None) -> None:
        payload: dict[str, Any] = {"node_id": node_id, "state": state}
        if message:
            payload["message"] = message
        await self.emit("node_state", payload)

    def _input_value(self, node_id: int, input_slot: int) -> Any:
        links = self.incoming.get((node_id, input_slot)) or []
        if not links:
            return None
        link = links[0]
        return self.output_cache.get((link["origin_id"], link["origin_slot"]))

    def _set_output(self, node_id: int, slot: int, value: Any) -> None:
        self.output_cache[(node_id, slot)] = value

    def _get_prop(self, node: dict[str, Any], key: str, default: Any = None) -> Any:
        props = node.get("properties") or {}
        return props.get(key, default)

    def _collect_ordered_upload_files(self, upload_id: str) -> list[Path]:
        base = node_upload_dir(upload_id)
        files = [p for p in base.iterdir() if p.is_file()]
        files.sort(key=lambda p: p.name.lower())
        return files

    def _create_session_from_upload(self, session_name: str, upload_id: str) -> SessionModel:
        upload_files = self._collect_ordered_upload_files(upload_id)
        if len(upload_files) < 2:
            raise WorkflowExecutionError("At least 2 uploaded images are required for a workflow run")

        session = SessionModel(name=session_name)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        target_dir = upload_dir(session.id)
        current_count = (
            self.db.query(func.count(SourceImage.id))
            .filter(SourceImage.session_id == session.id)
            .scalar()
            or 0
        )

        for idx, source_path in enumerate(upload_files):
            safe_name = source_path.name.replace("..", "_").replace("/", "_").replace("\\", "_")
            target = target_dir / f"{current_count + idx:05d}_{safe_name}"
            shutil.copyfile(source_path, target)

            row = SourceImage(
                session_id=session.id,
                filename=source_path.name,
                file_path=str(target),
                sort_order=current_count + idx,
            )
            self.db.add(row)

        session.status = "uploaded"
        self.db.commit()
        self.db.refresh(session)
        return session

    async def _execute_node(self, node_id: int, flow_name: str) -> None:
        node = self._node(node_id)
        node_type = node.get("type", "")

        await self._node_state(node_id, "running")

        # Display-only diagram nodes document the agent architecture and are not
        # executable; acknowledge and skip them so richer graphs still run.
        if node_type.startswith("display/") or node_type in {"annotation", "comment"}:
            await self._node_state(node_id, "done")
            return

        if node_type == "workflow/start":
            session_name = str(self._get_prop(node, "session_name", f"{flow_name}_{uuid.uuid4().hex[:8]}"))
            stitch_mode = str(self._get_prop(node, "stitch_mode", "scans"))
            flow_ctx = {"flow_name": flow_name, "session_name": session_name, "stitch_mode": stitch_mode}
            self._set_output(node_id, 0, flow_ctx)
            self._set_output(node_id, 1, flow_ctx)
            await self._node_state(node_id, "done", "Start emitted")
            return

        if node_type == "data/upload_ref":
            upload_id = str(self._get_prop(node, "upload_id", "")).strip()
            if not upload_id:
                raise WorkflowExecutionError("upload_ref node requires upload_id")
            if not node_upload_path(upload_id).exists():
                raise WorkflowExecutionError(f"upload_id not found: {upload_id}")
            self._set_output(node_id, 0, {"upload_id": upload_id})
            await self._node_state(node_id, "done", f"upload_id={upload_id}")
            return

        if node_type == "data/int":
            self._set_output(node_id, 0, int(self._get_prop(node, "value", 0)))
            await self._node_state(node_id, "done")
            return

        if node_type == "data/float":
            self._set_output(node_id, 0, float(self._get_prop(node, "value", 0.0)))
            await self._node_state(node_id, "done")
            return

        if node_type == "data/string":
            self._set_output(node_id, 0, str(self._get_prop(node, "value", "")))
            await self._node_state(node_id, "done")
            return

        if node_type == "math/add_int":
            a = int(self._input_value(node_id, 0) or 0)
            b = int(self._input_value(node_id, 1) or 0)
            self._set_output(node_id, 0, a + b)
            await self._node_state(node_id, "done", f"{a}+{b}={a+b}")
            return

        if node_type == "math/add_float":
            a = float(self._input_value(node_id, 0) or 0.0)
            b = float(self._input_value(node_id, 1) or 0.0)
            out = a + b
            self._set_output(node_id, 0, out)
            await self._node_state(node_id, "done", f"{a}+{b}={out}")
            return

        if node_type == "workflow/run_pipeline":
            start_ctx = self._input_value(node_id, 0) or self._input_value(node_id, 1) or {}
            upload_ref = self._input_value(node_id, 2) or {}
            session_name_data = self._input_value(node_id, 3)
            mode_data = self._input_value(node_id, 4)

            session_name = str(
                session_name_data
                or start_ctx.get("session_name")
                or self._get_prop(node, "session_name", "Untitled Session")
            )
            stitch_mode = str(
                mode_data
                or start_ctx.get("stitch_mode")
                or self._get_prop(node, "stitch_mode", "scans")
            )
            upload_id = str(upload_ref.get("upload_id") or self._get_prop(node, "upload_id", "")).strip()
            if not upload_id:
                raise WorkflowExecutionError("run_pipeline node requires upload_id via upload_ref input or property")

            await self.emit(
                "session_created",
                {
                    "node_id": node_id,
                    "session_name": session_name,
                    "upload_id": upload_id,
                    "mode": stitch_mode,
                },
            )

            session = self._create_session_from_upload(session_name, upload_id)
            result = run_pipeline(self.db, session, mode=stitch_mode)
            if result.status != "ready":
                raise WorkflowExecutionError(result.error_message or "Pipeline failed")

            self._set_output(node_id, 0, {"ok": True, "session_id": result.id})
            self._set_output(node_id, 1, {"session_id": result.id})
            await self._node_state(node_id, "done", f"session={result.id}")
            return

        if node_type == "workflow/download":
            primary_session_ref = self._input_value(node_id, 1) or {}
            fallback_session_ref = self._input_value(node_id, 0) or {}

            session_id = ""
            if isinstance(primary_session_ref, dict):
                session_id = str(primary_session_ref.get("session_id") or "").strip()
            if not session_id and isinstance(fallback_session_ref, dict):
                session_id = str(fallback_session_ref.get("session_id") or "").strip()
            if not session_id and isinstance(primary_session_ref, str):
                session_id = primary_session_ref.strip()
            if not session_id and isinstance(fallback_session_ref, str):
                session_id = fallback_session_ref.strip()

            if not session_id:
                raise WorkflowExecutionError("download node requires session input")

            session = self.db.get(SessionModel, session_id)
            if not session:
                raise WorkflowExecutionError(f"Session not found: {session_id}")
            if session.status != "ready":
                raise WorkflowExecutionError(f"Session is not ready: {session_id}")
            try:
                raw_path = resolve_raw_image_path(session)
                optimized_path = resolve_optimized_image_path(session)
            except HTTPException as exc:
                raise WorkflowExecutionError(str(exc.detail))

            raw_download_url = f"/api/sessions/{session_id}/download/raw"
            optimized_download_url = f"/api/sessions/{session_id}/download/optimized"
            raw_name = build_download_filename(session, variant="raw", file_path=raw_path)
            optimized_name = build_download_filename(session, variant="optimized", file_path=optimized_path)

            self._set_output(node_id, 0, {"ok": True})
            self._set_output(node_id, 1, raw_download_url)
            await self.emit(
                "package_ready",
                {
                    "node_id": node_id,
                    "session_id": session_id,
                    "download_url": raw_download_url,
                    "raw_download_url": raw_download_url,
                    "optimized_download_url": optimized_download_url,
                    "filename": raw_name,
                    "raw_filename": raw_name,
                    "optimized_filename": optimized_name,
                },
            )
            await self._node_state(node_id, "done", f"raw={raw_name} / optimized={optimized_name}")
            return

        raise WorkflowExecutionError(f"Unsupported node type: {node_type}")

    async def _run_flow(self, start_node_id: int) -> None:
        start_node = self._node(start_node_id)
        flow_name = str(self._get_prop(start_node, "flow_name", f"flow_{start_node_id}"))
        await self.emit("flow_started", {"start_node_id": start_node_id, "flow_name": flow_name})

        queue: list[int] = [start_node_id]
        visited: set[int] = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            await self._execute_node(current, flow_name)
            for next_node_id in self.flow_outgoing.get(current, []):
                queue.append(next_node_id)

        await self.emit("flow_finished", {"start_node_id": start_node_id, "flow_name": flow_name})

    async def run(self) -> None:
        start_nodes = [
            n_id
            for n_id, node in self.nodes_by_id.items()
            if node.get("type") == "workflow/start"
        ]
        if not start_nodes:
            raise WorkflowExecutionError("At least one workflow/start node is required")

        # Pre-compute non-flow data nodes so typed data links are available before flow executes.
        data_nodes = [
            n_id
            for n_id, node in self.nodes_by_id.items()
            if node.get("type") in {"data/upload_ref", "data/int", "data/float", "data/string", "math/add_int", "math/add_float"}
        ]
        for node_id in data_nodes:
            await self._execute_node(node_id, flow_name="data")

        for start_node_id in sorted(start_nodes):
            await self._run_flow(start_node_id)
            await asyncio.sleep(0)


async def execute_graph(db: Session, graph_payload: dict[str, Any], emit: EmitFn) -> None:
    runner = GraphRunner(db=db, graph_payload=graph_payload, emit=emit)
    await runner.run()
