"""
The community package's binding of `services.db`.

The three helpers used to live here in full. They moved to `services/db.py`
when the admin service needed the same wrapper; this module keeps the exact
names and signatures the community package already calls, so nothing else in
the package changed.
"""

from services.db import SupabaseOps

from .errors import UpstreamFailure

_ops = SupabaseOps(domain="community", wrap=UpstreamFailure)

# Bound methods exposed under the original module-level names: call sites stay
# `_db.table_op(..., what="...")`.
run = _ops.run
rpc = _ops.rpc
table_op = _ops.table_op
