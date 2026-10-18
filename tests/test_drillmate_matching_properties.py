"""Cross-check event matching cardinality against brute force on small graphs."""
import random
import unittest

from drillmate_validation.events import Event, Interval, _max_cardinality_match


def brute_maximum(edges, n_right):
    def dfs(i, used):
        if i == len(edges):
            return 0
        best = dfs(i + 1, used)
        for j in edges[i]:
            if j not in used:
                best = max(best, 1 + dfs(i+1, used | {j}))
        return best
    return dfs(0, set())


class MatchingProperties(unittest.TestCase):
    def test_random_maximum_cardinality(self):
        random.seed(78011)
        for case in range(150):
            experts, pred = [], []
            for i in range(random.randint(0, 6)):
                a = random.randint(0, 15)
                experts.append(Event(f"e{i}", Interval(a, a + random.randint(1, 8))))
            for j in range(random.randint(0, 6)):
                a = random.randint(0, 15)
                pred.append(Event(f"p{j}", Interval(a, a + random.randint(1, 8))))
            edges = []
            for e in experts:
                row = []
                for j, p in enumerate(pred):
                    overlap = max(0, min(e.interval.end, p.interval.end) - max(e.interval.start, p.interval.start))
                    union = e.interval.duration + p.interval.duration - overlap
                    if overlap > 0 and overlap/union >= 0.1:
                        row.append(j)
                edges.append(row)
            got = _max_cardinality_match(experts, pred, .1, 0)
            self.assertEqual(len(got), brute_maximum(edges, len(pred)), f"random case {case}")
            self.assertEqual(len({e for e, _, _, _ in got}), len(got))
            self.assertEqual(len({p for _, p, _, _ in got}), len(got))

    def test_many_distinct_events_no_recursion(self):
        n = 175
        experts = [Event(f"e{i}", Interval(i*10, i*10+5)) for i in range(n)]
        pred = [Event(f"p{i}", Interval(i*10, i*10+5)) for i in range(n)]
        got = _max_cardinality_match(experts, pred, 0.5, 0)
        self.assertEqual(len(got), n)


if __name__ == "__main__":
    unittest.main()
