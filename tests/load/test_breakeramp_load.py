import pytest
import threading
import time
import uuid
from unittest.mock import MagicMock
from amprealize.breakeramp import BreakerAmpService, DestroyRequest
from amprealize.action_contracts import Actor
from tests.helpers.load_generator import generate_heavy_blueprint

@pytest.mark.integration
def test_resource_serialization_real_world():
    """
    Verifies that BreakerAmpService correctly serializes concurrent runs
    when the Podman machine's memory is exhausted.

    This test:
    1. Inspects the Podman machine to find total memory.
    2. Launches a 'Load' run consuming ~60% of memory.
    3. Launches a 'Test' run consuming ~50% of memory.
    4. Verifies the 'Test' run blocks (serializes) until resources are freed.
    5. Destroys the 'Load' run.
    6. Verifies the 'Test' run proceeds.
    """
    # 1. Setup Service
    action_service = MagicMock()
    compliance_service = MagicMock()
    metrics_service = MagicMock()
    service = BreakerAmpService(action_service, compliance_service, metrics_service)

    actor = Actor(id="test-agent", role="TESTER", surface="CLI")

    # 2. Check Runtime / Machine Limits
    # We need a valid machine name. Default is usually podman-machine-default.
    # We can try to detect it or just let the service handle it.
    # We'll use a dummy manifest to trigger the machine check helper if needed,
    # but better to just use the internal helper if possible or just run a small check.

    # Let's try to get the machine memory first.
    # Detect machine name
    import subprocess
    machine_name = "podman-machine-default"
    try:
        res = subprocess.run(["podman", "machine", "list"], capture_output=True, text=True)
        lines = res.stdout.strip().splitlines()
        for line in lines[1:]: # skip header
            parts = line.split()
            if parts:
                name = parts[0]
                if name.endswith("*"):
                    machine_name = name[:-1]
                    break
                # If only one machine, use it (and it might not have *)
                if len(lines) == 2:
                     machine_name = name
    except Exception:
        pass

    try:
        inspect = service._inspect_podman_machine(machine_name)
        config = inspect.get("Config", {})
        total_mem_mb = config.get("Memory", 0) // (1024*1024)
    except Exception as e:
        pytest.skip(f"Could not inspect podman machine '{machine_name}': {e}. Is Podman running?")

    if total_mem_mb == 0:
        pytest.skip("Podman machine reports 0 memory. Cannot run load test.")

    if total_mem_mb > 8192:
        pytest.skip(f"Podman machine has {total_mem_mb}MB. Skipping load test to avoid massive allocation on large machines.")

    print(f"\n[LoadTest] Machine Memory: {total_mem_mb}MB")

    # 3. Prepare Blueprints
    # Load: 60% of memory
    load_mem = int(total_mem_mb * 0.6)
    # Test: 50% of memory (Total 1.1 > 1.0, so it must wait)
    test_mem = int(total_mem_mb * 0.5)

    print(f"[LoadTest] Run 1 (Load): {load_mem}MB")
    print(f"[LoadTest] Run 2 (Test): {test_mem}MB")

    bp_load = generate_heavy_blueprint("load-run", load_mem, duration_sec=120)
    bp_test = generate_heavy_blueprint("test-run", test_mem, duration_sec=10)

    manifest_load = {
        "runtime": {
            "provider": "podman",
            "podman_machine": machine_name,
            "auto_scaling_strategy": "serialize"
        },
        "blueprint": bp_load
    }

    manifest_test = {
        "runtime": {
            "provider": "podman",
            "podman_machine": machine_name,
            "auto_scaling_strategy": "serialize"
        },
        "blueprint": bp_test
    }

    # 4. Execution

    # Shared state for threads
    results: dict = {"load": None, "test": None}
    errors = []

    def run_apply(key, manifest):
        try:
            print(f"[{key}] Starting apply...")
            res = service.apply(manifest, actor)
            results[key] = res
            print(f"[{key}] Apply finished: {res.amp_run_id}")
        except Exception as e:
            print(f"[{key}] Failed: {e}")
            errors.append(e)

    # Start Load Run
    t_load = threading.Thread(target=run_apply, args=("load", manifest_load))
    t_load.start()

    # Wait for Load Run to consume memory
    # We poll service._get_current_resource_usage
    print("[LoadTest] Waiting for Load Run to consume memory...")
    start_wait = time.time()
    load_active = False
    while time.time() - start_wait < 60:
        used, _ = service._get_current_resource_usage()
        # We expect used to be at least load_mem (minus some overhead/slack)
        # Let's say 80% of load_mem to be safe (allocation might be slightly less or reported differently)
        if used >= (load_mem * 0.8):
            print(f"[LoadTest] Load detected: {used}MB used.")
            load_active = True
            break
        time.sleep(2)

    if not load_active:
        # Cleanup and fail
        # We can't easily kill the thread but we can try to destroy if it created a run
        pytest.fail("Load run did not consume expected memory in time.")

    # Start Test Run (Should Block)
    print("[LoadTest] Starting Test Run (should block)...")
    t_test = threading.Thread(target=run_apply, args=("test", manifest_test))
    t_test.start()

    # Wait a bit to ensure it's blocked
    time.sleep(5)
    if results["test"] is not None:
        pytest.fail("Test run finished immediately! Serialization failed.")

    print("[LoadTest] Test run is blocked as expected. Destroying Load Run...")

    # Destroy Load Run to free resources
    # We need the run_id from the load result
    # Wait for t_load to finish (it should have finished apply() and be running)
    t_load.join(timeout=10)
    if results["load"] is None:
        pytest.fail("Load run apply() never returned.")

    load_run_id = results["load"].amp_run_id

    destroy_req = DestroyRequest(amp_run_id=load_run_id, reason="Test cleanup", force_podman=True)
    service.destroy(destroy_req, actor)
    print("[LoadTest] Load Run destroyed.")

    # Now Test Run should proceed
    print("[LoadTest] Waiting for Test Run to proceed...")
    t_test.join(timeout=60)

    if results["test"] is None:
        pytest.fail("Test run timed out waiting for resources.")

    print("[LoadTest] Test Run completed successfully.")

    # Cleanup Test Run
    test_run_id = results["test"].amp_run_id
    service.destroy(DestroyRequest(amp_run_id=test_run_id, reason="Test cleanup", force_podman=True), actor)
