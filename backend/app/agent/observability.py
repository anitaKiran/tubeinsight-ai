"""Optional, restricted LangSmith spans; never export prompts or source text."""
from contextlib import contextmanager
from contextvars import ContextVar
import logging
import os

from langsmith import Client, tracing_context
from langsmith.run_helpers import trace
from urllib3 import Retry
from app.schemas.error import ApiException

logger = logging.getLogger(__name__)
_observer = ContextVar("tubeinsight_observer", default=None)


class SafeSdkLog(logging.Filter):
    def filter(self, record):
        # The SDK otherwise includes masked API-key fragments in network errors.
        # Keep all SDK diagnostics generic, including embedded exception strings.
        record.msg = "Optional LangSmith SDK operation could not complete."
        record.args = ()
        record.exc_info = record.exc_text = None
        return True


for _name in ("langsmith.client", "langsmith.run_helpers", "langsmith.run_trees", "langsmith._internal._background_thread", "langsmith._internal._compressed_traces"):
    logging.getLogger(_name).addFilter(SafeSdkLog())


class Observer:
    def __init__(self, video_id):
        self.video_id = video_id
        self.client = None
        self.project = os.getenv("LANGSMITH_PROJECT", "tubeInsight-ai").strip() or "tubeInsight-ai"
        if os.getenv("LANGSMITH_TRACING", "").strip().lower() not in {"true", "1"}:
            return
        key = os.getenv("LANGSMITH_API_KEY", "").strip()
        if not key:
            logger.warning("Optional LangSmith tracing disabled: missing API key.")
            return
        try:
            self.client = Client(api_key=key, hide_inputs=True, hide_outputs=True,
                timeout_ms=500, retry_config=Retry(total=0), auto_batch_tracing=True,
                omit_traced_runtime_info=True)
        except Exception:
            logger.warning("Optional LangSmith tracing could not initialize.")


@contextmanager
def operation(name, run_type="chain"):
    observer = _observer.get()
    context = manager = run = None
    metadata = {}
    if observer is not None and observer.client is not None:
        try:
            context = tracing_context(enabled=True, client=observer.client, project_name=observer.project)
            context.__enter__()
            manager = trace(name, run_type=run_type, inputs={}, client=observer.client,
                project_name=observer.project, metadata={
                    "operation": name, "video_id": observer.video_id,
                    "environment": os.getenv("APP_ENV", "development") if os.getenv("APP_ENV", "development") in {"development", "production", "test", "staging"} else "other",
                })
            run = manager.__enter__()
        except Exception:
            logger.warning("Optional LangSmith span could not start.")
    error_code = None
    try:
        # Deliberately disable automatic LangChain/OpenAI payload tracing. Only
        # explicit spans above are exported, with empty inputs and outputs.
        with tracing_context(enabled=False):
            yield metadata
    except BaseException as error:
        error_code = error.code if isinstance(error, ApiException) else "OPERATION_FAILED"
        raise
    finally:
        try:
            if run is not None:
                run.end(outputs={}, error=error_code, metadata=metadata)
                manager.__exit__(None, None, None)
        except Exception:
            logger.warning("Optional LangSmith span could not finish.")
        finally:
            if context is not None:
                try:
                    context.__exit__(None, None, None)
                except Exception:
                    pass


@contextmanager
def observe_request(video_id):
    observer = Observer(video_id)
    token = _observer.set(observer)
    try:
        with operation("chat.request"):
            yield
    finally:
        try:
            if observer.client is not None:
                observer.client.flush(timeout=.5)
        except Exception:
            logger.warning("Optional LangSmith export flush could not complete.")
        finally:
            _observer.reset(token)
