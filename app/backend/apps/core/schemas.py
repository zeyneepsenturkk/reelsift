from ninja import Schema


class ErrorOut(Schema):
    detail: str
    code: str


class GpuOut(Schema):
    available: bool
    name: str | None = None


class HealthOut(Schema):
    status: str
    database: bool
    pgvector_version: str
    gpu: GpuOut
    data_mounted: bool
    models_mounted: bool
