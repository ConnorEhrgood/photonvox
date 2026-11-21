"""Publishing a phone system to its engine: the order of the steps (ARCHITECTURE §5). The synthetic check, versions and undo build on this.

1. The domain exists, or is created and seeded with FusionPBX's standard dial plans (vox-agent), before anything refers to it.
2. One transaction writes the whole build (app/engine/writer.py): either all of it is on the engine or none of it.
3. What was written is recorded (`on_written`) as soon as the transaction commits, before anything else can fail (audit VOX-B-5): a failed cache
   clear then leaves a record that matches the engine, so putting the previous version back removes what this one added, and the secrets it
   gave new extensions are kept.
4. vox-agent clears the cache entries the build touched, so the next call reads the new configuration.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from sqlalchemy.engine import Engine

from app.engine import fusionpbx, writer
from app.engine.agent import Agent


def publish(engine: Engine, agent: Agent, plan: Mapping[str, Any], target: fusionpbx.Target,
            previous: Sequence[Mapping[str, str]] = (), on_written: Optional[Callable[[writer.Result], None]] = None) -> writer.Result:
    built = fusionpbx.build(plan, target)
    with engine.begin() as conn:
        created = writer.ensure_domain(conn, target.domain_uuid, plan["domain"])
    if created:
        agent.seed_domain()
    with engine.begin() as conn:
        result = writer.write(conn, built, target.domain_uuid, previous)
        if result.cache and not getattr(agent, "available", True):
            # No vox-agent on this engine (decision 32): a change FreeSWITCH would only see after its cache is cleared is not committed.
            raise RuntimeError("this instance has no vox-agent: the change needs the engine's cache cleared, so nothing was written")
    if on_written is not None:
        on_written(result)
    agent.clear_cache(result.cache)
    return result
