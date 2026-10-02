"""PostgreSQL pgvector column declaration without a new driver dependency."""

from sqlalchemy.types import UserDefinedType


class Vector768(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kwargs):
        return "vector(768)"
