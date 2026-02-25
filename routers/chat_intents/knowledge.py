"""Knowledge base intents: KB stats, search, semantic search, index, learn incident, feedback."""

import re
from typing import Optional

from routers.deps import get_scanner, get_current_region, logger


async def handle(message: str, message_lower: str) -> Optional[str]:
    """Route knowledge-base intents. Returns None if not matched."""

    # --- KB Stats ---
    if any(kw in message_lower for kw in ['kb stats', 'knowledge stats', '知识库统计']):
        return _kb_stats()

    # --- KB Semantic Search (before keyword search) ---
    if any(kw in message_lower for kw in ['kb semantic', 'semantic search', '语义搜索']):
        return _kb_semantic(message)

    # --- KB Search (keyword) ---
    if any(kw in message_lower for kw in ['kb search', 'knowledge search', '知识搜索']) and 'semantic' not in message_lower:
        return _kb_search(message)

    # --- KB Index ---
    if any(kw in message_lower for kw in ['kb index', 'kb init', 'create index']):
        return _kb_index()

    # --- Learn from incident ---
    if any(kw in message_lower for kw in ['learn incident', '学习故障', 'learn from']):
        return _learn_incident()

    # --- Feedback ---
    if any(kw in message_lower for kw in ['feedback', '反馈']):
        return _feedback(message, message_lower)

    return None


# =========================================================================
# Private helpers
# =========================================================================

def _kb_stats() -> str:
    try:
        from src.knowledge_search import get_knowledge_store
        store = get_knowledge_store()
        stats = store.get_stats()

        response = f"""📚 **知识库统计**

| 项目 | 值 |
|------|-----|
| 总 Patterns | {stats['total_patterns']} |
| 平均置信度 | {stats['avg_confidence']:.2f} |

**按分类:**
"""
        for cat, count in stats.get('by_category', {}).items():
            response += f"- {cat}: {count}\n"

        response += "\n**按服务:**\n"
        for svc, count in stats.get('by_service', {}).items():
            response += f"- {svc}: {count}\n"

        return response
    except Exception as e:
        return f"❌ 获取知识库统计失败: {str(e)}"


def _kb_search(message: str) -> str:
    try:
        from src.knowledge_search import get_knowledge_store
        store = get_knowledge_store()

        match = re.search(r'search\s+(.+)', message, re.IGNORECASE)
        if not match:
            return """**知识搜索**

用法: `kb search <关键词>`

示例: 
- `kb search high cpu`
- `kb search ec2 timeout`

**语义搜索:** `kb semantic <问题描述>`"""

        query = match.group(1).strip()
        keywords = query.lower().split()

        patterns = store.search_patterns(keywords=keywords, limit=5)

        if not patterns:
            return f"🔍 未找到匹配 '{query}' 的知识条目\n\n💡 试试语义搜索: `kb semantic {query}`"

        response = f"""🔍 **知识搜索结果: '{query}'**

找到 {len(patterns)} 条匹配:

"""
        for p in patterns:
            response += f"""**{p.title}** ({p.pattern_id})
- 分类: {p.category} | 服务: {p.service} | 置信度: {p.confidence:.2f}
- 症状: {', '.join(p.symptoms[:3])}...
- 解决方案: {p.remediation[:100]}...

"""
        return response
    except Exception as e:
        return f"❌ 知识搜索失败: {str(e)}"


def _kb_semantic(message: str) -> str:
    try:
        match = re.search(r'(?:semantic|语义搜索)\s+(.+)', message, re.IGNORECASE)
        if not match:
            return """**语义搜索 (AI 驱动)**

用法: `kb semantic <问题描述>`

示例: 
- `kb semantic 服务器响应很慢怎么办`
- `kb semantic database connection timeout`
- `kb semantic lambda 函数执行失败`

使用 AI 向量匹配，支持自然语言查询"""

        query = match.group(1).strip()

        from src.vector_search import get_vector_search
        search = get_vector_search()

        if not search._initialized:
            return "⚠️ 向量搜索服务未初始化，请稍后再试"

        results = search.hybrid_search(query, limit=5)

        if not results:
            return f"🔍 未找到与 '{query}' 语义相关的知识"

        response = f"""🧠 **语义搜索结果: '{query}'**

找到 {len(results)} 条相关知识:

"""
        for r in results:
            response += f"""**{r.get('title', 'N/A')}** ({r.get('type', 'unknown')})
- 服务: {r.get('service', 'N/A')} | 相关度: {r.get('score', 0):.2f}
- {r.get('description', '')[:100]}...

"""
        return response
    except Exception as e:
        return f"❌ 语义搜索失败: {str(e)}"


def _kb_index() -> str:
    try:
        from src.vector_search import get_vector_search
        search = get_vector_search()

        if search.create_index():
            return "✅ **知识库向量索引创建成功！**\n\n现在可以使用 `kb semantic <查询>` 进行语义搜索"
        else:
            return "❌ 索引创建失败，请检查 OpenSearch 连接"
    except Exception as e:
        return f"❌ 索引创建失败: {str(e)}"


def _learn_incident() -> str:
    return """📚 **学习故障/Incident**

用法: 通过 API 提交 Incident 记录

```
POST /api/knowledge/learn
{
  "incident_id": "INC-001",
  "title": "EC2 High CPU",
  "description": "Instance CPU utilization exceeded 90%",
  "service": "ec2",
  "severity": "high",
  "symptoms": ["high cpu", "slow response"],
  "root_cause": "Memory leak in application",
  "resolution": "Restarted application",
  "resolution_steps": ["Identified leak", "Restarted app", "Monitored"]
}
```

或使用: `POST /api/knowledge/learn`"""


def _feedback(message: str, message_lower: str) -> str:
    try:
        # Format: feedback <pattern_id> good/bad
        match = re.search(r'feedback\s+([a-f0-9]+)\s+(good|bad|helpful|not helpful)', message_lower)
        if not match:
            return """**提交 Pattern 反馈**

用法: `feedback <pattern_id> good/bad`

示例:
- `feedback abc123 good` - 标记为有帮助
- `feedback abc123 bad` - 标记为无帮助"""

        pattern_id = match.group(1)
        is_helpful = match.group(2) in ['good', 'helpful']

        from src.knowledge_search import get_feedback_handler
        handler = get_feedback_handler()

        if handler.submit_feedback(pattern_id, is_helpful):
            return f"✅ 反馈已提交: Pattern {pattern_id} {'👍 有帮助' if is_helpful else '👎 无帮助'}"
        else:
            return f"❌ Pattern {pattern_id} 不存在"
    except Exception as e:
        return f"❌ 提交反馈失败: {str(e)}"
