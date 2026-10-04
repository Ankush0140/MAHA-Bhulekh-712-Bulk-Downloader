import os

try:
    os.makedirs(os.path.join(os.path.dirname(__file__), 'models'), exist_ok=True)
except Exception:
    pass

with open(os.path.join(os.path.dirname(__file__), 'models', '__init__.py'), 'w') as f:
    pass
