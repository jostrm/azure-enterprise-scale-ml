"""App layer: orchestration that composes base + domain into test lifecycles.

Provides repeatable deploy->verify->cleanup lifecycles with guaranteed
teardown so the suite can run over and over. Tests use these context managers
instead of calling domain functions directly.
"""
