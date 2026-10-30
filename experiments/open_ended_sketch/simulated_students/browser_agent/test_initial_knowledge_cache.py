"""Offline cache isolation, invalidation and cross-process initialization tests."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from initial_knowledge_cache import InitialKnowledgeCache, InitialKnowledgeCacheError


class InitialKnowledgeCacheContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.cache = InitialKnowledgeCache(self.directory / "cache")
        self.binding = {"task": "Represent A then B.", "response": "I labeled A and B.",
                        "image_sha256": "a" * 64, "prompt_sha256": "b" * 64,
                        "schema_sha256": "c" * 64, "model": "fixture-model", "effort": "low"}
        self.calls = 0

    def create(self):
        self.calls += 1
        return {"reply": {"knowledge_state": {"known": ["Can label A and B."]}},
                "origin": {"response_id": "scripted-original-initialization"}}

    def test_reuses_exact_initial_state_without_another_model_call(self):
        first, hit1, path1 = self.cache.get_or_create(self.binding, self.create)
        second, hit2, path2 = self.cache.get_or_create(deepcopy(self.binding), self.create)
        self.assertEqual(self.calls, 1)
        self.assertFalse(hit1)
        self.assertTrue(hit2)
        self.assertEqual(first, second)
        self.assertEqual(path1, path2)
        self.assertEqual(first["knowledge_state"], {
            "known": ["Can label A and B."], "unknown": [], "possibly_known": []})

    def test_local_updates_do_not_mutate_k0_or_another_copy(self):
        first, _, _ = self.cache.get_or_create(self.binding, self.create)
        second, _, _ = self.cache.get_or_create(self.binding, self.create)
        second["knowledge_state"]["known"].append("A later Teacher-supported relation.")
        third, _, _ = self.cache.get_or_create(self.binding, self.create)
        self.assertEqual(first["knowledge_state"], third["knowledge_state"])
        self.assertNotEqual(second["knowledge_state"], third["knowledge_state"])

    def test_changed_response_task_image_or_initialization_settings_get_new_entries(self):
        self.cache.get_or_create(self.binding, self.create)
        for field in self.binding:
            changed = {**self.binding, field: "a different " + field}
            with self.subTest(field=field):
                _, hit, _ = self.cache.get_or_create(changed, self.create)
                self.assertFalse(hit)
        self.assertEqual(self.calls, 1 + len(self.binding))

    def test_persists_across_cache_instances_and_preserves_original_provenance(self):
        first, _, _ = self.cache.get_or_create(self.binding, self.create)
        second, hit, _ = InitialKnowledgeCache(self.cache.directory).get_or_create(
            self.binding, lambda: self.fail("A persisted cache must not call the model."))
        self.assertTrue(hit)
        self.assertEqual(second["origin"], first["origin"])

    def test_tampered_cache_fails_without_silently_reinitializing(self):
        _, _, path = self.cache.get_or_create(self.binding, self.create)
        data = json.loads(path.read_text())
        data["knowledge_state"]["known"].append("Unrecorded knowledge.")
        path.write_text(json.dumps(data))
        with self.assertRaises(InitialKnowledgeCacheError):
            self.cache.get_or_create(self.binding, self.create)
        self.assertEqual(self.calls, 1)

    def test_malformed_cache_is_not_overwritten(self):
        _, _, path = self.cache.get_or_create(self.binding, self.create)
        path.write_text("incomplete JSON")
        with self.assertRaises(InitialKnowledgeCacheError):
            self.cache.get_or_create(self.binding, self.create)
        self.assertEqual(path.read_text(), "incomplete JSON")

    def test_failed_or_schema_invalid_producer_does_not_publish_k0(self):
        def failed():
            raise RuntimeError("Scripted endpoint failure")
        with self.assertRaises(RuntimeError):
            self.cache.get_or_create(self.binding, failed)
        with self.assertRaises(Exception):
            self.cache.get_or_create(self.binding, lambda: {
                "reply": {"knowledge_state": {"known": [""]}}, "origin": {}})
        self.assertFalse(list(self.cache.directory.glob("*.json")))
        _, hit, _ = self.cache.get_or_create(self.binding, self.create)
        self.assertFalse(hit)

    def test_concurrent_processes_generate_only_one_initialization(self):
        # Separate Python helpers model the runner's concurrent profile workers.
        script = r'''
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from initial_knowledge_cache import InitialKnowledgeCache
root, index = Path(sys.argv[2]), sys.argv[3]
(root / ('ready-' + index)).write_text('ready')
deadline = time.monotonic() + 8
while not (root / 'start').exists():
    if time.monotonic() > deadline: raise RuntimeError('Start barrier timed out')
    time.sleep(.01)
def produce():
    counter = root / 'created_count'
    counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')
    time.sleep(.1)
    return {'reply': {'knowledge_state': {'known': ['Common original Response.']}},
            'origin': {'response_id': 'scripted-single-call'}}
entry, hit, _ = InitialKnowledgeCache(root / 'cache').get_or_create({'response': 'same'}, produce)
(root / ('result-' + index + '.json')).write_text(json.dumps({'hit': hit, 'state': entry['knowledge_state']}))
'''
        workers = [subprocess.Popen([sys.executable, "-B", "-c", script, str(HERE),
                                      str(self.directory), str(i)], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True) for i in range(3)]
        try:
            deadline = time.monotonic() + 8
            while len(list(self.directory.glob("ready-*"))) != 3:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            (self.directory / "start").write_text("start")
            for worker in workers:
                stdout, stderr = worker.communicate(timeout=10)
                self.assertEqual(worker.returncode, 0, stderr or stdout)
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.kill()
                    worker.communicate()
        results = [json.loads((self.directory / ("result-" + str(i) + ".json")).read_text()) for i in range(3)]
        self.assertEqual((self.directory / "created_count").read_text(), "1")
        self.assertEqual(sum(not item["hit"] for item in results), 1)
        self.assertTrue(all(item["state"] == results[0]["state"] for item in results))


if __name__ == "__main__":
    unittest.main()
