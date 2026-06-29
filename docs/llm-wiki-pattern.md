# LLM Wiki — Building a Personal Knowledge Base with AI

> Adapted from Karpathy's "LLM Wiki" pattern

## Core Idea

**How it differs from RAG**:

| Approach | Mechanism | Problem |
|----------|-----------|---------|
| RAG (NotebookLM, ChatGPT file upload) | Retrieves from raw documents on every query | Knowledge doesn't accumulate; re-discovered each time |
| LLM Wiki | LLM incrementally builds and maintains a persistent wiki | Knowledge compiled once, continuously updated, compounds over time |

The wiki is a **persistent, compounding** artifact. Cross-references are already built, contradictions are already flagged, synthesis already reflects everything you've read. Every new source makes the wiki richer.

## Three-Layer Architecture

```
Raw sources (articles, data, documents)
    ↓ Read-only, immutable, source of truth
Wiki (LLM-generated markdown files)
    ↓ LLM writes and maintains; humans read
Schema (CLAUDE.md / config files)
    ↓ Tells LLM the wiki's structure, conventions, and workflows
```

## Three Core Operations

### Ingest
Feed a source → LLM reads → extracts key information → integrates into existing wiki (updates entity pages, concept pages, flags contradictions) → updates index → writes log.

A single source may touch **10-15 wiki pages**.

### Query
Ask a question → LLM searches relevant pages → reads → synthesizes an answer (with citations).

**Key insight**: A good answer can itself be stored back into the wiki as a new page. Comparisons, discovered relationships — these valuable outputs shouldn't disappear into chat history.

### Lint
Periodically let the LLM check wiki health:
- Contradictions between pages
- Outdated claims superseded by newer sources
- Orphan pages with no inbound links
- Important concepts mentioned but lacking their own page
- Missing cross-references

## Why It Works

The tedious part of maintaining a knowledge base isn't reading and thinking — it's the **bookkeeping**: updating cross-references, keeping summaries current, flagging contradictions, maintaining consistency across dozens of pages. Humans abandon wikis because maintenance burden grows faster than value. LLMs don't get tired, don't forget to update cross-references, and can modify 15 files at once.

- **Human's job**: Curate sources, guide analysis, ask good questions, think about implications
- **LLM's job**: Everything else
