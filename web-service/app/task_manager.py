import uuid
import threading
from typing import Dict, Optional
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime


class TaskStatus(str, Enum):
    """Task execution status"""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStage(str, Enum):
    """Task execution stages"""
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    TRANSLATING = "translating"
    SAVING = "saving"


@dataclass
class Task:
    """Task data model"""
    task_id: str
    status: TaskStatus
    progress: float  # 0.0 to 1.0
    stage: Optional[TaskStage] = None
    error: Optional[str] = None
    result: Optional[Dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        # Convert enums to strings
        if self.status:
            data['status'] = self.status.value
        if self.stage:
            data['stage'] = self.stage.value
        return data


class TaskManager:
    """
    Thread-safe task manager for tracking async caption generation tasks.
    """

    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.lock = threading.Lock()

    def create_task(self) -> str:
        """
        Create a new task and return its ID.

        Returns:
            str: Task ID (UUID)
        """
        task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        with self.lock:
            self.tasks[task_id] = Task(
                task_id=task_id,
                status=TaskStatus.QUEUED,
                progress=0.0,
                stage=None,
                error=None,
                result=None,
                created_at=now,
                updated_at=now
            )

        return task_id

    def update_progress(self, task_id: str, progress: float, stage: TaskStage):
        """
        Update task progress and stage.

        Args:
            task_id: Task ID
            progress: Progress value (0.0 to 1.0)
            stage: Current execution stage
        """
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id].progress = min(max(progress, 0.0), 1.0)
                self.tasks[task_id].stage = stage
                self.tasks[task_id].status = TaskStatus.RUNNING
                self.tasks[task_id].updated_at = datetime.utcnow().isoformat()

    def complete_task(self, task_id: str, result: Dict):
        """
        Mark task as completed with result data.

        Args:
            task_id: Task ID
            result: Result dictionary containing caption_path, etc.
        """
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id].status = TaskStatus.COMPLETED
                self.tasks[task_id].progress = 1.0
                self.tasks[task_id].result = result
                self.tasks[task_id].error = None
                self.tasks[task_id].updated_at = datetime.utcnow().isoformat()

    def fail_task(self, task_id: str, error: str):
        """
        Mark task as failed with error message.

        Args:
            task_id: Task ID
            error: Error message
        """
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id].status = TaskStatus.FAILED
                self.tasks[task_id].error = error
                self.tasks[task_id].updated_at = datetime.utcnow().isoformat()

    def get_task(self, task_id: str) -> Optional[Task]:
        """
        Get task by ID.

        Args:
            task_id: Task ID

        Returns:
            Task object or None if not found
        """
        with self.lock:
            return self.tasks.get(task_id)

    def delete_task(self, task_id: str) -> bool:
        """
        Delete task by ID.

        Args:
            task_id: Task ID

        Returns:
            bool: True if deleted, False if not found
        """
        with self.lock:
            if task_id in self.tasks:
                del self.tasks[task_id]
                return True
            return False

    def list_tasks(self) -> Dict[str, Task]:
        """
        Get all tasks.

        Returns:
            Dict of task_id -> Task
        """
        with self.lock:
            return dict(self.tasks)


# Global task manager instance
task_manager = TaskManager()
