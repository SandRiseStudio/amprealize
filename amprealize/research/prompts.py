"""Research prompts - OSS Stub. Full implementation in amprealize-enterprise."""

try:
    from amprealize_enterprise.research.prompts import (
        COMPREHENSION_SYSTEM_PROMPT,
        COMPREHENSION_USER_PROMPT,
        EVALUATION_SYSTEM_PROMPT,
        EVALUATION_USER_PROMPT,
        RECOMMENDATION_SYSTEM_PROMPT,
        RECOMMENDATION_USER_PROMPT,
        format_comprehension_prompt,
        format_evaluation_prompt,
        format_recommendation_prompt,
    )
except ImportError:
    COMPREHENSION_SYSTEM_PROMPT = ""
    COMPREHENSION_USER_PROMPT = ""
    EVALUATION_SYSTEM_PROMPT = ""
    EVALUATION_USER_PROMPT = ""
    RECOMMENDATION_SYSTEM_PROMPT = ""
    RECOMMENDATION_USER_PROMPT = ""

    def format_comprehension_prompt(*args, **kwargs):
        raise ImportError("Research prompts require amprealize-enterprise[research]")

    def format_evaluation_prompt(*args, **kwargs):
        raise ImportError("Research prompts require amprealize-enterprise[research]")

    def format_recommendation_prompt(*args, **kwargs):
        raise ImportError("Research prompts require amprealize-enterprise[research]")
