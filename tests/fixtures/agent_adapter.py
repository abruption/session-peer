"""Source-registered deterministic adapter, never installed with the product."""


def install(peer):
    class FixtureAdapter(peer.AgentAdapter):
        name = "fixture"

        def list(self, context):
            return {"sessions": [{"agent": self.name, "id": "one", "name": "fixture",
                                  "cwd": "/fixture", "status": "idle"}],
                    "discovery": {"status": "ok"}}

        def submit(self, context, text):
            identity = self.identity(context.options.to, context)
            return {"ok": True, "target": {"id": identity.identifier},
                    "status": "validated" if context.options.dry_run else "submitted",
                    "submitted": not context.options.dry_run,
                    "consumptionConfirmed": False, "chars": len(text), "body": text}

        def diagnose(self, context):
            return {"status": "available", "checks": []}

    peer.AGENTS.register(FixtureAdapter())
