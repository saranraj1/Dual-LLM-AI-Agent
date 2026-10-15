"""
memory/episodic_memory.py — Episodic task trajectory recorder and query engine.
Captures multi-step agent plans, tool calls, observations, blast radii, and checkpoint links.
"""

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

from memory.storage import get_db, normalize_workspace


@dataclass
class Episode:
    """Represents a full multi-step task execution trajectory."""
    task_goal: str = ""
    workspace: str = ""
    trajectory: List[Dict[str, Any]] = field(default_factory=list)
    files_touched: List[str] = field(default_factory=list)
    blast_radius: Dict[str, Any] = field(default_factory=dict)
    checkpoint_id: Optional[str] = None
    status: str = "SUCCESS"  # SUCCESS, FAILED, PARTIAL, REVERTED
    error_summary: Optional[str] = None
    duration_sec: float = 0.0
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_type: str = "general"
    created_at: str = field(default_factory=lambda: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))

    @property
    def task(self) -> str:
        return self.task_goal

    @property
    def steps(self) -> List[Dict[str, Any]]:
        return self.trajectory

    @property
    def duration_secs(self) -> float:
        return self.duration_sec

    @property
    def success(self) -> bool:
        return self.status == "SUCCESS"

    @property
    def git_commit(self) -> Optional[str]:
        return self.checkpoint_id

    def __getitem__(self, item: str) -> Any:
        if item == "task":
            return self.task_goal
        if item == "steps":
            return self.trajectory
        if item == "duration_secs":
            return self.duration_sec
        if item == "success":
            return self.status == "SUCCESS"
        if item == "git_commit":
            return self.checkpoint_id
        return getattr(self, item)


class EpisodicMemory:
    """Persistent store and query interface for autonomous task episodes."""

    def __init__(self, workspace: str = "", storage: Optional[Any] = None):
        self.workspace = normalize_workspace(workspace)
        self.storage = storage

    def _get_db(self):
        if self.storage and hasattr(self.storage, "get_db"):
            return self.storage.get_db()
        return get_db()

    def record_episode(
        self,
        episode: Optional[Episode] = None,
        task: Optional[str] = None,
        task_goal: Optional[str] = None,
        task_type: str = "general",
        success: bool = True,
        steps: Optional[List[Dict[str, Any]]] = None,
        trajectory: Optional[List[Dict[str, Any]]] = None,
        workspace: Optional[str] = None,
        duration_secs: float = 0.0,
        git_commit: Optional[str] = None,
        error_summary: Optional[str] = None,
        files_touched: Optional[List[str]] = None,
        blast_radius: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """Persist a completed task trajectory to SQLite."""
        if episode is None:
            goal = task or task_goal or ""
            traj = steps if steps is not None else (trajectory or [])
            st = "SUCCESS" if success else "FAILED"
            episode = Episode(
                task_goal=goal,
                workspace=workspace or self.workspace,
                trajectory=traj,
                files_touched=files_touched or [],
                blast_radius=blast_radius or {},
                checkpoint_id=git_commit,
                status=st,
                error_summary=error_summary,
                duration_sec=duration_secs,
                task_type=task_type
            )

        ws = normalize_workspace(episode.workspace or self.workspace)
        with self._get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO episodic_tasks
                (id, workspace, task_goal, trajectory, files_touched, blast_radius, checkpoint_id, status, error_summary, turns_count, duration_sec)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.id,
                    ws,
                    episode.task_goal,
                    json.dumps(episode.trajectory),
                    json.dumps(episode.files_touched),
                    json.dumps(episode.blast_radius),
                    episode.checkpoint_id,
                    episode.status,
                    episode.error_summary,
                    len(episode.trajectory),
                    round(episode.duration_sec, 2)
                )
            )
            conn.commit()
        return episode.id

    def get_episodes(
        self,
        workspace: Optional[str] = None,
        limit: int = 10,
        status: Optional[str] = None
    ) -> List[Episode]:
        """Retrieve recent task trajectories for workspace."""
        ws = normalize_workspace(workspace or self.workspace)
        with self._get_db() as conn:
            query = """
            SELECT id, workspace, task_goal, trajectory, files_touched, blast_radius, checkpoint_id, status, error_summary, turns_count, duration_sec, created_at
            FROM episodic_tasks
            WHERE (? = '' OR workspace = ?)
            """
            params = [ws, ws]
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, tuple(params)).fetchall()
            episodes = []
            for r in rows:
                episodes.append(Episode(
                    id=r["id"],
                    workspace=r["workspace"],
                    task_goal=r["task_goal"],
                    trajectory=json.loads(r["trajectory"]),
                    files_touched=json.loads(r["files_touched"]),
                    blast_radius=json.loads(r["blast_radius"] or "{}"),
                    checkpoint_id=r["checkpoint_id"],
                    status=r["status"],
                    error_summary=r["error_summary"],
                    duration_sec=r["duration_sec"],
                    created_at=r["created_at"],
                ))
            return episodes

    def search_episodes(
        self,
        query: str,
        workspace: Optional[str] = None,
        limit: int = 5
    ) -> List[Episode]:
        """Find past episodes matching a task goal or touched file."""
        ws = normalize_workspace(workspace or self.workspace)
        tokens = [t.strip() for t in query.split() if t.strip()]
        if not tokens:
            return []

        token_clauses = " AND ".join(["(task_goal LIKE ? OR files_touched LIKE ?)"] * len(tokens))
        params = [ws, ws]
        for t in tokens:
            like_pat = f"%{t}%"
            params.extend([like_pat, like_pat])
        params.append(limit)

        sql = f"""
        SELECT id, workspace, task_goal, trajectory, files_touched, blast_radius, checkpoint_id, status, error_summary, duration_sec, created_at
        FROM episodic_tasks
        WHERE (? = '' OR workspace = ?)
          AND ({token_clauses})
        ORDER BY created_at DESC LIMIT ?
        """

        with self._get_db() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [
                Episode(
                    id=r["id"],
                    workspace=r["workspace"],
                    task_goal=r["task_goal"],
                    trajectory=json.loads(r["trajectory"]) if "trajectory" in r.keys() and r["trajectory"] else [],
                    files_touched=json.loads(r["files_touched"]),
                    blast_radius=json.loads(r["blast_radius"] or "{}") if "blast_radius" in r.keys() else {},
                    checkpoint_id=r["checkpoint_id"],
                    status=r["status"],
                    error_summary=r["error_summary"],
                    duration_sec=r["duration_sec"] if "duration_sec" in r.keys() else 0.0,
                    created_at=r["created_at"]
                )
                for r in rows
            ]
