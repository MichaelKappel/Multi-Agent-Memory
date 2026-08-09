import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts" / "audit_uai_memory.py"


spec = importlib.util.spec_from_file_location("audit_uai_memory", AUDIT_PATH)
audit_uai_memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_uai_memory)


class UaiAuditContractTests(unittest.TestCase):
    def test_startup_order_has_no_catch_all_active_memory_file(self):
        forbidden = audit_uai_memory.FORBIDDEN_ACTIVE_MEMORY_FILENAMES
        read_order_names = {
            Path(item).name for item in audit_uai_memory.STARTUP_READ_ORDER
        }
        self.assertEqual({name.lower() for name in forbidden}, forbidden)
        self.assertIn("active-memory.uai", forbidden)
        self.assertIn("current-state.uai", forbidden)
        self.assertIn("short-term-memory.uai", forbidden)
        self.assertFalse(read_order_names & forbidden)
        self.assertEqual(
            ".uai/startup-packet.uai", audit_uai_memory.STARTUP_READ_ORDER[0]
        )
        self.assertEqual(
            ".uai/memory-maintenance.uai", audit_uai_memory.STARTUP_READ_ORDER[1]
        )
        self.assertIn(".uai/totem.uai", audit_uai_memory.STARTUP_READ_ORDER)
        self.assertIn(".uai/taboo.uai", audit_uai_memory.STARTUP_READ_ORDER)
        self.assertIn(".uai/talisman.uai", audit_uai_memory.STARTUP_READ_ORDER)
        self.assertIn(
            ".uai/agents/memoryendpoints-frontend-agent.uai",
            audit_uai_memory.STARTUP_READ_ORDER,
        )
        self.assertIn(
            ".uai/agents/memoryendpoints-backend-agent.uai",
            audit_uai_memory.STARTUP_READ_ORDER,
        )
        self.assertNotIn(
            ".uai/short-term-memory.uai", audit_uai_memory.STARTUP_READ_ORDER
        )
        self.assertNotIn(".uai/current-state.uai", audit_uai_memory.STARTUP_READ_ORDER)
        self.assertNotIn(
            ".uai/short-term-memory.uai", audit_uai_memory.manifest_read_order()
        )
        self.assertNotIn(
            ".uai/current-state.uai", audit_uai_memory.manifest_read_order()
        )

    def test_cross_product_workspace_checkpoint_follows_complete_uai_manifest(self):
        agents = " ".join((ROOT / "AGENTS.md").read_text(encoding="utf-8").split())
        workspace = " ".join(
            (ROOT / "workspace.uai").read_text(encoding="utf-8").split()
        )
        receiver = " ".join(
            (ROOT / ".uai" / "receiver-brief.uai").read_text(encoding="utf-8").split()
        )
        handoff = " ".join(
            (ROOT / ".uai" / "handoff-brief.uai").read_text(encoding="utf-8").split()
        )
        human = " ".join(
            (ROOT / ".uai" / "readme.human").read_text(encoding="utf-8").split()
        )
        full_export = " ".join(
            (ROOT / ".uai" / "exports" / "llms-full.uai")
            .read_text(encoding="utf-8")
            .split()
        )
        compact_export = " ".join(
            (ROOT / ".uai" / "exports" / "llms.uai").read_text(encoding="utf-8").split()
        )
        memory = " ".join(
            (ROOT / ".uai" / "memory.uai").read_text(encoding="utf-8").split()
        )

        self.assertIn(
            "After the complete governed `.uai` manifest is loaded, read root "
            "`workspace.uai`",
            agents,
        )
        self.assertIn(
            "Read `AGENTS.md`, then `.uai/startup-packet.uai`, then every file "
            "in the packet's complete declared order.",
            workspace,
        )
        self.assertIn(
            "After the governed repository startup manifest is loaded, read this "
            "cross-product `workspace.uai` coordinator checkpoint",
            workspace,
        )
        self.assertIn(
            "Start at `AGENTS.md`, then `.uai/startup-packet.uai`",
            receiver,
        )
        self.assertIn(
            "Read `AGENTS.md`, then `.uai/startup-packet.uai`",
            handoff,
        )
        for brief in (receiver, handoff):
            self.assertIn("then read root `workspace.uai`", brief)
        self.assertIn(
            "load the governed `.uai` manifest and root `workspace.uai` first",
            human,
        )
        self.assertIn(
            "This public checkout does not prove the current private "
            "MemoryEndpoints.com production source or deployment",
            human,
        )
        export_read_first = full_export.split("Read first:", 1)[1].split(
            "Durable evidence roots:", 1
        )[0]
        self.assertLess(
            export_read_first.index("`.uai/startup-packet.uai`"),
            export_read_first.index("`workspace.uai`"),
        )
        self.assertLess(
            export_read_first.index("`workspace.uai`"),
            export_read_first.index("`.uai/readme.human`"),
        )
        self.assertIn(
            "load the manifest and complete active `.uai` read order, then root "
            "`workspace.uai`",
            compact_export,
        )
        self.assertIn(
            "read `AGENTS.md`, then `.uai/startup-packet.uai` and its complete "
            "manifest, then root `workspace.uai`",
            memory,
        )

    def test_active_briefs_do_not_promote_historical_deploys_to_current(self):
        startup = (ROOT / ".uai" / "startup-packet.uai").read_text(encoding="utf-8")
        architecture = (ROOT / ".uai" / "architecture.uai").read_text(encoding="utf-8")
        stack = (ROOT / ".uai" / "stack.uai").read_text(encoding="utf-8")
        risks = (ROOT / ".uai" / "risk-register.uai").read_text(encoding="utf-8")
        context = (ROOT / ".uai" / "context.uai").read_text(encoding="utf-8")
        operations = (ROOT / ".uai" / "operations.uai").read_text(encoding="utf-8")
        progress = (ROOT / ".uai" / "progress.uai").read_text(encoding="utf-8")

        for memory in (context, operations):
            self.assertNotIn("Latest-code MemoryEndpoints.com", memory)
            self.assertIn("historical", memory.lower())
        self.assertIn(
            "this checkout cannot prove the private commercial implementation bytes",
            progress,
        )
        self.assertIn(
            "The current FileZilla inventory has no target-bound "
            "`multiagentmemory` profile",
            progress,
        )
        self.assertIn(
            "free single-organization private-intranet Multi-Agent Memory MATM "
            "reference",
            startup,
        )
        self.assertIn("private source and deployment are not present here", startup)
        self.assertNotIn("real MATM product/API surface", architecture)
        self.assertNotIn("verified production backend", stack)
        self.assertNotIn("MultiAgentMemory.com is live", risks)

    def test_active_uai_rejects_protected_ids_and_private_intake_paths(self):
        rules = dict(audit_uai_memory.SECRET_PATTERNS)
        samples = {
            "protected_room_id": "room-0123456789abcdef",
            "protected_meeting_message_id": "meetmsg-0123456789abcdef",
            "protected_memory_id": "mem-0123456789abcdef",
            "protected_routing_id": "route-0123456789abcdef",
            "protected_goal_scope_id": "goal-private-workstream",
            "protected_project_scope_id": "project-private-workspace",
            "private_intake_path": r"D:\DownloadArchive\report.md",
            "private_ftp_credential_handoff_path": r"E:\ftp_Deploy.txt",
        }
        for name, sample in samples.items():
            self.assertIn(name, rules)
            self.assertRegex(sample, rules[name])

        active_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / ".uai").rglob("*.uai"))
        )
        for name in samples:
            self.assertIsNone(rules[name].search(active_text), name)

    def test_continuation_requires_current_target_authority(self):
        next_actions = (ROOT / ".uai" / "next-actions.uai").read_text(encoding="utf-8")
        recursive = (ROOT / ".uai" / "next-recursive-prompt.uai").read_text(
            encoding="utf-8"
        )
        progress = (ROOT / ".uai" / "progress.uai").read_text(encoding="utf-8")

        self.assertIn("Historical FTPS success authorizes nothing", next_actions)
        self.assertIn("Otherwise perform a safe no-op", next_actions)
        self.assertIn(
            "deploy only when that specific target's authority and later gates "
            "are present",
            recursive,
        )
        self.assertNotIn("exact-SHA FTPS deployment is live", progress)
        self.assertNotIn("the current release is pushed and published", progress)
        self.assertIn("Historical-evidence boundary:", progress)
        self.assertNotIn("project-memoryendpoints-com", progress)

    def test_forbidden_active_memory_names_are_exact_filename_bans(self):
        paths = {
            ".uai/context.uai",
            ".uai/current-state.uai",
            ".uai/short-term-memory.uai",
            ".uai/archives/current-state.uai",
            ".uai/exports/llms-full.uai",
        }
        forbidden_paths = set(audit_uai_memory.forbidden_active_memory_paths(paths))
        self.assertEqual(
            {
                ".uai/current-state.uai",
                ".uai/short-term-memory.uai",
                ".uai/archives/current-state.uai",
            },
            forbidden_paths,
        )
        self.assertIn(
            "actual local files", audit_uai_memory.FORBIDDEN_ACTIVE_MEMORY_POLICY
        )
        self.assertIn(
            "creates no local file", audit_uai_memory.FORBIDDEN_ACTIVE_MEMORY_POLICY
        )

    def test_active_uai_files_are_date_free_and_typed(self):
        items = [
            audit_uai_memory.audit_file(path)
            for path in sorted((ROOT / ".uai").rglob("*.uai"))
        ]
        self.assertTrue(items)
        self.assertTrue(all(item["dateFree"] for item in items))
        active_names = {Path(item["path"]).name.lower() for item in items}
        self.assertFalse(
            active_names & audit_uai_memory.FORBIDDEN_ACTIVE_MEMORY_FILENAMES
        )

    def test_active_handoff_buckets_have_no_guidance_or_payload_files(self):
        items = audit_uai_memory.audit_handoff_buckets()
        self.assertTrue(items)
        self.assertTrue(all(item["ok"] for item in items), items)

    def test_pre_publication_clean_slate_policy_is_explicit_in_taboo_and_totem(self):
        taboo = (ROOT / ".uai" / "taboo.uai").read_text(encoding="utf-8")
        totem = (ROOT / ".uai" / "totem.uai").read_text(encoding="utf-8")

        for memory in (taboo, totem):
            self.assertIn("pre-publication-clean-slate-v1", memory)
            self.assertIn("HTTP 410 tombstones", memory)
            self.assertIn("obsolete-route recognizers", memory)
            self.assertIn("aliases", memory)
            self.assertIn("translators", memory)
            self.assertIn("inert handlers", memory)
            self.assertIn("migration", memory)
            self.assertIn("ordinary current-router 404", memory)

    def test_hosted_swarm_identity_and_writer_exclusivity_are_explicit(self):
        taboo = " ".join(
            (ROOT / ".uai" / "taboo.uai").read_text(encoding="utf-8").split()
        )
        totem = " ".join(
            (ROOT / ".uai" / "totem.uai").read_text(encoding="utf-8").split()
        )
        combined = f"{taboo} {totem}".lower()

        for required in (
            "unique normalized name",
            "immutable `.uai` memory identity",
            "exactly one current writer lease",
            "true branches receive distinct immutable identities",
            "parent identity, parent digest, and complete lineage",
            "monotonic fencing tokens",
            "without imposing a global singleton",
        ):
            self.assertIn(required, combined)


if __name__ == "__main__":
    unittest.main()
