"""Campaign model skeleton."""

from app.database import Base
from app.models.base import TimestampMixin


class Campaign(Base, TimestampMixin):
    """Persistence model for campaigns."""

    # TODO: add campaign fields.
    pass
