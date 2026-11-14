from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Optional, get_args

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
    true,
)
from sqlalchemy import Enum as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpkit.core.db.base import Base
from pumpkit.core.ids import ulid_with_prefix
from pumpkit.posts.formats import Format
from pumpkit.posts.plans import DesiredAction, Funnel, Length, Plan, Structure

if TYPE_CHECKING:
    from pumpkit.auth.models import User


class Brief(Base):
    """The text a User wrote to get Posts from, kept as they wrote it."""

    __tablename__ = "briefs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("brief")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The User's Positioning when the Brief was planned, whatever it is now. None, like the
    # three below, on a Brief that was never planned.
    positioning: Mapped[Optional[str]] = mapped_column(Text)
    # Why the planner split the Brief or didn't. Only kept, never shown.
    planning_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    planning_model: Mapped[Optional[str]] = mapped_column(String)
    # The provider's whole usage payload, cost and cache counts included.
    planning_usage: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))

    user: Mapped["User"] = relationship()
    # The single-post Idea first, then the split Ideas in posting order.
    ideas: Mapped[list["Idea"]] = relationship(
        back_populates="brief",
        cascade="all, delete-orphan",
        order_by=lambda: IDEA_ORDER,
    )


class PlanCall(Base):
    """
    One plan call a User's request made, whatever came of it. The hourly cap counts these, since a
    failed plan call stores no Brief and is paid for all the same.
    """

    __tablename__ = "plan_calls"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("plan_call")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Idea(Base):
    """One Post proposed from a Brief, written or not."""

    __tablename__ = "ideas"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("idea")
    )
    brief_id: Mapped[str] = mapped_column(ForeignKey("briefs.id", ondelete="CASCADE"), index=True)
    # Where the Idea comes among the Ideas posted with it, from 1: always 1 for the single-post Idea.
    posting_order: Mapped[int] = mapped_column(Integer)
    # True for the single-post Idea, which covers the whole Brief; False for a split Idea.
    whole_brief: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # The Plan, as columns. All None on an Idea that was never planned.
    core_idea: Mapped[Optional[str]] = mapped_column(Text)
    takeaway: Mapped[Optional[str]] = mapped_column(Text)
    plan_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    funnel: Mapped[Optional[Funnel]] = mapped_column(PgEnum(*get_args(Funnel), name="funnel_enum"))
    desired_action: Mapped[Optional[DesiredAction]] = mapped_column(
        PgEnum(*get_args(DesiredAction), name="desired_action_enum")
    )
    format: Mapped[Optional[Format]] = mapped_column(
        PgEnum(*get_args(Format), name="version_format_enum")
    )
    # None for a Thread.
    length: Mapped[Optional[Length]] = mapped_column(PgEnum(*get_args(Length), name="length_enum"))
    structure: Mapped[Optional[Structure]] = mapped_column(
        PgEnum(*get_args(Structure), name="structure_enum")
    )

    # Read with the Idea, since an async session can't load it lazily.
    brief: Mapped[Brief] = relationship(back_populates="ideas", lazy="selectin")

    def __init__(self, *, plan: Optional[Plan] = None, **fields: Any) -> None:
        super().__init__(**fields)
        if plan is not None:
            self.core_idea = plan.core_idea
            self.takeaway = plan.takeaway
            self.plan_reasoning = plan.reasoning
            self.funnel = plan.funnel
            self.desired_action = plan.desired_action
            self.format = plan.format
            self.length = plan.length
            self.structure = plan.structure

    @property
    def plan(self) -> Optional[Plan]:
        if (
            self.core_idea is None
            or self.takeaway is None
            or self.funnel is None
            or self.desired_action is None
            or self.format is None
            or self.structure is None
        ):
            return None
        return Plan(
            core_idea=self.core_idea,
            takeaway=self.takeaway,
            reasoning=self.plan_reasoning or "",
            funnel=self.funnel,
            desired_action=self.desired_action,
            format=self.format,
            length=self.length,
            structure=self.structure,
        )


# A Brief's Ideas in order, which numbers its Posts too (ADR 0025).
IDEA_ORDER = (Idea.whole_brief.desc(), Idea.posting_order, Idea.id)


class Post(Base):
    """One piece of writing made from one Idea of a Brief, with every attempt at a Version of it."""

    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("post")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # An Idea has at most one Post.
    idea_id: Mapped[str] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"), unique=True)
    # Unused: the author post ids of the corpus Posts were once written from. SQL NULL, never JSON null.
    corpus_post_ids: Mapped[Optional[list[str]]] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")
    )
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
    # Whether the Text's last Part is a single post's first reply (ADR 0027).
    text_first_reply: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # When Feedback's Version started being written, which then becomes the Text; None otherwise.
    writing_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # The Feedback being written, kept once its write fails or times out, so the page offers it again
    # until the User sends Feedback, changes the Text or dismisses it; None otherwise.
    unwritten_feedback: Mapped[Optional[str]] = mapped_column(Text)
    unwritten_feedback_format: Mapped[Optional[Format]] = mapped_column(
        PgEnum(*get_args(Format), name="version_format_enum")
    )

    user: Mapped["User"] = relationship()
    # Read with the Post, since the Brief's text is read through it.
    idea: Mapped[Idea] = relationship(lazy="selectin")
    attempts: Mapped[list["VersionAttempt"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="VersionAttempt.sequence"
    )
    # Every Part's Media references, read with the Post, since the Text shows them.
    text_media: Mapped[list["TextMedia"]] = relationship(
        cascade="all, delete-orphan",
        order_by="(TextMedia.part_index, TextMedia.position)",
        lazy="selectin",
    )

    def __init__(self, *, brief: Optional[str] = None, **fields: Any) -> None:
        """`brief` starts the Post from a new Brief with that text and one Idea."""
        super().__init__(**fields)
        if brief is not None:
            owner = {"user": fields["user"]} if "user" in fields else {"user_id": self.user_id}
            self.idea = Idea(
                brief=Brief(text=brief, created_at=self.created_at, **owner), posting_order=1
            )

    @property
    def brief(self) -> str:
        return self.idea.brief.text


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
    # The Sketch's Part texts in order; a single X post has one, and its first reply. Only kept.
    sketch_parts: Mapped[Optional[list[str]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    parts: Mapped[Optional[list[str]]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    # Whether the last of `parts` is a single post's first reply (ADR 0027).
    first_reply: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # The model of the call that wrote the Sketch: the merge on a first Version, the revise call
    # after Feedback, or on older Versions the call that wrote from a corpus.
    sketch_model: Mapped[Optional[str]] = mapped_column(String)
    humanizing_model: Mapped[Optional[str]] = mapped_column(String)
    # The provider's whole usage payload, cost and cache counts included.
    sketch_usage: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    humanizing_usage: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    # Why the writing call opened the post as it did, or the revise call's reasoning, and the
    # library Hook it opened with; the name is None for an opening with no library Hook.
    hook_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    hook_name: Mapped[Optional[str]] = mapped_column(String)
    # The psychological levers, hook types and CTA type the merge chose, or the revise call's CTA
    # type, on a Version written from a Plan. These and the sketches and merge below are kept, never shown.
    hook_levers: Mapped[Optional[list[str]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    hook_types: Mapped[Optional[list[str]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    cta_type: Mapped[Optional[str]] = mapped_column(String)
    # Every sketch call, failed ones with their error, each with its model and usage.
    sketches: Mapped[Optional[list[dict]]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    # The merge's reviews of the sketches, its reasoning and the first reply it wrote, if any.
    merge: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    # The Starting text: the Post's Text the Feedback was given on, kept only when it differs from
    # the Version before. The number is the Version that Text came from.
    starting_text_format: Mapped[Optional[Format]] = mapped_column(
        PgEnum(*get_args(Format), name="version_format_enum")
    )
    starting_text_parts: Mapped[Optional[list[str]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    starting_text_version_number: Mapped[Optional[int]] = mapped_column(Integer)
    starting_text_first_reply: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
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


class AccountFileDeletion(Base):
    __tablename__ = "account_file_deletions"

    key: Mapped[str] = mapped_column(String, primary_key=True)
