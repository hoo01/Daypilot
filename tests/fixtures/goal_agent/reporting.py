from contextlib import contextmanager


@contextmanager
def step(label: str):
    print(f"\n  ▶  {label}")
    yield
    print(f"  ✓  {label}")
