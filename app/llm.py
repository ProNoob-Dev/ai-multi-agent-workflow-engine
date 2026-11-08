"""LLM provider abstraction.

The Mock provider is the DEFAULT: deterministic and rule-based, so the
whole system (including tests and evals) runs with no API key and no cost.
Azure OpenAI activates automatically when AZURE_OPENAI_ENDPOINT,
AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT are all set.
"""

import re

import httpx

from . import config


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token). Used for cost tracking."""
    return max(1, len(text) // 4)


class MockLLM:
    """Deterministic rule-based stand-in for a real LLM.

    It never calls any external service. Drafting and summarising are
    template-based so behaviour is identical on every run.
    """

    name = "mock"

    def complete(self, prompt: str, system: str = "") -> tuple[str, int]:
        text = (system + "\n" + prompt).lower()
        if "draft" in text and "report" in text:
            out = (
                "DRAFT REPORT\n"
                "This report was drafted from the seeded business data. "
                "All figures are traceable to the source records cited below. "
                "A human reviewer should verify the totals before distribution."
            )
        elif "summar" in text:
            sentences = re.split(r"(?<=[.!?])\s+", prompt.strip())
            out = " ".join(sentences[:2]) if sentences else prompt.strip()
        elif "invoice" in text:
            out = (
                "Invoice summary: the invoice was validated against its "
                "purchase order and vendor record. See the validation "
                "details for amounts, due date and duplicate checks."
            )
        else:
            out = (
                "Mock response: the request was processed by the rule-based "
                "mock provider. Connect Azure OpenAI to get model-generated text."
            )
        return out, estimate_tokens(prompt) + estimate_tokens(out)

    def draft_report(self, report_type: str, period: str, figures: dict) -> str:
        lines = [
            f"{report_type} — {period}",
            "",
            "Summary",
            "-------",
        ]
        for key, value in figures.items():
            lines.append(f"- {key}: {value}")
        lines += [
            "",
            "Notes",
            "-----",
            (
                "Figures are computed from the seeded ledger and invoice records. "
                "This draft was produced by the deterministic mock provider; "
                "connect Azure OpenAI for model-generated narrative."
            ),
        ]
        text = "\n".join(lines)
        return text


class AzureOpenAIProvider:
    """Thin Azure OpenAI client over plain HTTPS (no SDK dependency)."""

    name = "azure-openai"

    def __init__(self) -> None:
        self.endpoint = config.AZURE_OPENAI_ENDPOINT.rstrip("/")
        self.api_key = config.AZURE_OPENAI_API_KEY
        self.deployment = config.AZURE_OPENAI_DEPLOYMENT
        self.api_version = config.AZURE_OPENAI_API_VERSION

    def complete(self, prompt: str, system: str = "") -> tuple[str, int]:
        url = (
            f"{self.endpoint}/openai/deployments/{self.deployment}"
            f"/chat/completions?api-version={self.api_version}"
        )
        payload = {
            "messages": [
                {"role": "system", "content": system or "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        with httpx.Client(timeout=60) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        tokens = int(data.get("usage", {}).get("total_tokens", 0)) or estimate_tokens(
            prompt + text
        )
        return text, tokens

    def draft_report(self, report_type: str, period: str, figures: dict) -> str:
        figure_lines = "\n".join(f"- {k}: {v}" for k, v in figures.items())
        prompt = (
            f"Draft a short business report.\nType: {report_type}\n"
            f"Period: {period}\nFigures:\n{figure_lines}\n"
            "Keep it factual, cite the figures, and end with a one-line "
            "recommendation."
        )
        text, _ = self.complete(prompt, system="You write concise business reports.")
        return text


def get_llm():
    """Return the configured provider: Azure OpenAI if fully configured,
    otherwise the deterministic mock provider."""
    if (
        config.AZURE_OPENAI_ENDPOINT
        and config.AZURE_OPENAI_API_KEY
        and config.AZURE_OPENAI_DEPLOYMENT
    ):
        return AzureOpenAIProvider()
    return MockLLM()
