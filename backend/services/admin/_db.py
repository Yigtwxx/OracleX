"""The admin package's binding of `services.db`."""

from services.db import SupabaseOps

from .errors import UpstreamFailure

_ops = SupabaseOps(domain="admin", wrap=UpstreamFailure)

run = _ops.run
rpc = _ops.rpc
table_op = _ops.table_op
