from sqlalchemy import String, Double, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Quarantine(Base):
    """业务负责人对失真数据批次的一次隔离处置。

    一个数据批次最多只有一条隔离记录：重试隔离请求时复用同一条记录，
    避免重复记账。隔离是单向处置，原批次不会因为记录变化而恢复。
    """
    __tablename__ = 'quarantines'
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), unique=True, index=True)
    reason: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[float] = mapped_column(Double)
    effective_at: Mapped[float] = mapped_column(Double)
    replacement_dataset_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
