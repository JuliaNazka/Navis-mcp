"""nwd_* tools: a Python port of the bimwright nwd-mcp server (v1.0.0).

The original server is a .NET 8 process that talks to the nwd Navisworks
plug-in over loopback TCP (one NDJSON request/response per connection). This
package speaks the same wire protocol to the same, unmodified plug-in, so the
nwd_* tools live inside the Navis-mcp process next to NavisCoord's navis_*
tools instead of in a second server.

Ported from https://github.com/bimwright/nwd-mcp (Apache-2.0); see
THIRD_PARTY_NOTICES.md at the repository root for the licence and the list of
changes.
"""

from .config import NwdConfig
from .tools import register

__all__ = ["NwdConfig", "register"]
