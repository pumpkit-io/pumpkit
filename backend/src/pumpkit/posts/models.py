from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional, get_args

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy import Enum as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpkit.core.db.base import Base
from pumpkit.core.ids import ulid_with_prefix
from pumpkit.posts.formats import Format

if TYPE_CHECKING:
    from pumpkit.auth.models import User


class Post(Base):
    """One piece of writing made from one Brief, with every attempt at a Version of it."""

    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("post")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    brief: Mapped[str] = mapped_column(Text)
    # The corpus's author post ids in the order the calls get them, fixed when the Post starts
    # so changing the User's Inspiration authors later doesn't change it.
    corpus_post_ids: Mapped[list[str]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The Text, set from each new Version; None only while the Post has no Version.
    text_format: Mapped[Optional[Format]] = mapped_column(
        PgEnum(*get_args(Format), name="version_format_enum")
    )
    text_parts: Mapped[Optional[list[str]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    # Versions are never removed, so the number names the one the Text came from for good.
    text_version_number: Mapped[Optional[int]] = mapped_column(Integer)
    text_edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # When Feedback's Version started being written, which then becomes the Text; None otherwise.
    writing_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship()
    attempts: Mapped[list["VersionAttempt"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="VersionAttempt.sequence"
    )
    # Every Part's Media references, read with the Post, since the Text shows them.
    text_media: Mapped[list["TextMedia"]] = relationship(
        cascade="all, delete-orphan",
        order_by="(TextMedia.part_index, TextMedia.position)",
        lazy="selectin",
    )


VersionAttemptStatus = Literal[
    "succeeded",
    "failed",
]
ATTEMPT_SUCCEEDED: VersionAttemptStatus = "succeeded"
ATTEMPT_FAILED: VersionAttemptStatus = "failed"


class VersionAttempt(Base):
    """
    One try at writing a Version of a Post. Only a succeeded attempt is a Version; a failed
    one keeps its error instead.
    """

    __tablename__ = "version_attempts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("version_attempt")
    )
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    # Counts every attempt on the Post, failed ones included.
    sequence: Mapped[int] = mapped_column(Integer)
    # None for the first Version, which comes from the Brief.
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    # Stored on a failed attempt too, so a retry can ask for the same Format.
    format: Mapped[Format] = mapped_column(PgEnum(*get_args(Format), name="version_format_enum"))
    status: Mapped[VersionAttemptStatus] = mapped_column(
        PgEnum(*get_args(VersionAttemptStatus), name="version_attempt_status_enum")
    )
    # Counts succeeded attempts only: the number the User sees.
    version_number: Mapped[Optional[int]] = mapped_column(Integer)
    # The Sketch's Part texts in order; a single X post has one. Only kept, never shown.
    sketch_parts: Mapped[Optional[list[str]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    parts: Mapped[Optional[list[str]]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    # The sketch call's model on a first Version, the revision call's on a later one.
    sketch_model: Mapped[Optional[str]] = mapped_column(String)
    humanizing_model: Mapped[Optional[str]] = mapped_column(String)
    # The provider's whole usage payload, cost and cache counts included.
    sketch_usage: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    humanizing_usage: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    # Why the writing call opened the post as it did, and the library Hook it opened with; the
    # name is None for an opening with no library Hook or one the library doesn't have.
    hook_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    hook_name: Mapped[Optional[str]] = mapped_column(String)
    # The Starting text: the Post's Text the Feedback was given on, kept only when it differs from
    # the Version before. The number is the Version that Text came from.
    starting_text_format: Mapped[Optional[Format]] = mapped_column(
        PgEnum(*get_args(Format), name="version_format_enum")
    )
    starting_text_parts: Mapped[Optional[list[str]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    starting_text_version_number: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    post: Mapped["Post"] = relationship(back_populates="attempts")

    __table_args__ = (
        # Named here: the naming convention uses only the first column, so the two would clash.
        UniqueConstraint("post_id", "sequence", name="uq_version_attempts_post_id_sequence"),
        UniqueConstraint(
            "post_id", "version_number", name="uq_version_attempts_post_id_version_number"
        ),
    )


MediaKind = Literal["image", "gif", "video"]
MEDIA_IMAGE: MediaKind = "image"
MEDIA_GIF: MediaKind = "gif"
MEDIA_VIDEO: MediaKind = "video"


class Media(Base):
    """
    One file a User attached, kept by the Instance until its X post is Published (ADR 0021). The
    Text and Scheduled post Parts reference it; it never belongs to a Version.
    """

    __tablename__ = "media"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("media")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[MediaKind] = mapped_column(PgEnum(*get_args(MediaKind), name="media_kind_enum"))
    # Read from the file's own bytes, never from its name or the upload's declared type.
    content_type: Mapped[str] = mapped_column(String)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    alt_text: Mapped[Optional[str]] = mapped_column(Text)
    # A video's length as the browser read it; the server never measures one.
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    # The file to publish, in the FileStorage; None once it is deleted after publishing.
    file_key: Mapped[Optional[str]] = mapped_column(String)
    # A small image the web app shows, kept after the file is gone.
    preview_key: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TextMedia(Base):
    """One Media's place on a Post's Text: its Part, and its order among that Part's Media."""

    __tablename__ = "text_media"

    # A Media sits on one Text, once.
    media_id: Mapped[str] = mapped_column(
        ForeignKey("media.id", ondelete="CASCADE"), primary_key=True
    )
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    # Counted from 0, as the Text's Parts are stored.
    part_index: Mapped[int] = mapped_column(Integer)
    # Orders the Part's Media; gaps left by removals don't matter.
    position: Mapped[int] = mapped_column(Integer)

    media: Mapped["Media"] = relationship(lazy="joined")


class MediaUploadLink(Base):
    """
    A one-time link an AI app sends a Media file to with no other credentials, made by
    `attach_media` for one Part of one of the User's Posts.
    """

    __tablename__ = "media_upload_links"

    # The token in the link, hashed: the row, not the URL, names the User, Post and Part.
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    # Counted from 0, as the Text's Parts are stored.
    part_index: Mapped[int] = mapped_column(Integer)
    alt_text: Mapped[Optional[str]] = mapped_column(Text)
    # The app that asked for it: disconnecting the app stops the link.
    app_connection_id: Mapped[str] = mapped_column(
        ForeignKey("app_connections.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Set when an upload starts through it, whatever comes of that upload.
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
