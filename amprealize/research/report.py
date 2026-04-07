"""Report renderer - OSS Stub. Full implementation in amprealize-enterprise."""

try:
    from amprealize_enterprise.research.report import render_report
except ImportError:
    def render_report(*args, **kwargs):
        raise ImportError(
            "Research report rendering requires amprealize-enterprise[research]. "
            "Install with: pip install amprealize-enterprise[research]"
        )
