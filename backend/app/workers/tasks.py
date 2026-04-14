"""Worker task skeletons."""

from app.workers.celery_app import celery_app


@celery_app.task(name="engageai.run_engagement_pipeline")
def run_engagement_pipeline(topic: str, actor_id: str) -> dict[str, str] | None:
    """Run engagement pipeline task."""

    # TODO: implement background task execution.
    pass
