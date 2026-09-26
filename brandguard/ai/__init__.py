"""Gemini (design §5.4): reviewing possible misspellings and reading text in images.

Two fixed workflows, not an agent: each is a structured-JSON call per batch/image. Every call
goes through llm.Gemini, which logs usage, enforces the limits from Settings and caches answers.
"""
