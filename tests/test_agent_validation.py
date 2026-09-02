from services.agent_validation import activity_metrics, binary_metrics, compare_binary_versions


def test_binary_confusion_counts():
    truth = [True, True, False, False]
    pred = [True, False, True, False]
    m = binary_metrics(truth, pred)
    assert (m.tp, m.tn, m.fp, m.fn) == (1, 1, 1, 1)
    assert m.precision == 0.5
    assert m.recall == 0.5


def test_compare_versions_shows_improvement():
    truth = [True, True, False, False, False, False]
    old = [True, False, True, True, False, False]
    new = [True, True, False, False, False, False]
    table = compare_binary_versions(y_true=truth, old_pred=old, new_pred=new)
    assert table.loc["new_agent", "f1"] > table.loc["old_agent", "f1"]
    assert table.loc["new_agent", "fp"] < table.loc["old_agent", "fp"]


def test_activity_confusion_and_metrics():
    truth = ["Drilling", "Drilling", "Reaming", "Reaming"]
    pred = ["Drilling", "Reaming", "Reaming", "Reaming"]
    summary, cm, per_class = activity_metrics(truth, pred)
    assert summary["accuracy"] == 0.75
    assert cm.loc["Drilling", "Drilling"] == 1
    assert cm.loc["Drilling", "Reaming"] == 1
    assert set(per_class["activity"]) == {"Drilling", "Reaming"}
