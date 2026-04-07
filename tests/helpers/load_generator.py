from typing import Dict, Any
from amprealize.breakeramp import Blueprint, ServiceSpec

def generate_heavy_blueprint(name: str, memory_mb: int, duration_sec: int = 60) -> Dict[str, Any]:
    """
    Generates a blueprint dictionary that defines a service consuming specified memory.
    Uses a standard Python image to allocate memory via a bytearray.
    """
    # Python command to allocate memory and sleep
    # We use bytearray because it's a mutable sequence of integers,
    # and allocating it immediately consumes RAM (unlike some lazy allocations).
    cmd = (
        f"python -c \"import time, sys; "
        f"print('Allocating {memory_mb}MB...'); "
        f"x = bytearray({memory_mb} * 1024 * 1024); "
        f"print('Allocated. Sleeping...'); "
        f"time.sleep({duration_sec})\""
    )

    return {
        "name": name,
        "version": "1.0.0",
        "services": {
            "load-generator": {
                "image": "python:3.9-slim",
                "command": ["/bin/sh", "-c", cmd],
                "memory_mb": memory_mb,
                "cpu_cores": 0.5
            }
        }
    }
