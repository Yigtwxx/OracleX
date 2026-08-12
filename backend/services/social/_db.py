"""
The social package's binding of `services.db`.

Mirrors `services/community/_db.py` exactly, so call sites in this package read
`_db.table_op(..., what="...")` the same way they do over there.
"""

from services.db import SupabaseOps

from .errors import UpstreamFailure

_ops = SupabaseOps(domain="social", wrap=UpstreamFailure)

run = _ops.run
rpc = _ops.rpc
table_op = _ops.table_op
