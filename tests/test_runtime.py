import subprocess
import sys

from src.agent.runtime import AgentRuntime, RuntimeState


class TestAgentRuntime:
    def test_noisy_agent_output_is_redirected_without_deadlock(self):
        runtime = AgentRuntime()
        agent_id = "noisy-agent"
        code = (
            "import os\n"
            "chunk = b'x' * 65536\n"
            "for _ in range(128):\n"
            "    os.write(1, chunk)\n"
            "for _ in range(128):\n"
            "    os.write(2, chunk)\n"
        )
        command = [sys.executable, "-c", code]

        assert runtime.start(agent_id, command)
        proc = runtime._processes[agent_id]
        assert proc.stdout is None
        assert proc.stderr is None

        try:
            assert proc.wait(timeout=5) == 0
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise

    def test_stop_preserves_stopped_state_for_redirected_process(self):
        runtime = AgentRuntime()
        agent_id = "stoppable-agent"

        command = [sys.executable, "-c", "import time; time.sleep(30)"]

        assert runtime.start(agent_id, command)
        assert runtime.stop(agent_id, timeout=1)
        assert runtime.get_state(agent_id) == RuntimeState.STOPPED
