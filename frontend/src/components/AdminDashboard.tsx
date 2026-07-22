import { useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import type { AppDispatch, RootState } from "../app/store";
import { fetchRules, saveRule } from "../features/rules/rulesSlice";
import type { FraudRule } from "../types";

/**
 * This is the "adjust strictness without redeploying" surface. Saving a
 * rule PUTs it to Postgres (source of truth) and refreshes the Redis cache
 * that Celery workers read on every transaction - the next transaction
 * scored uses the new threshold, no deploy involved.
 */
export function AdminDashboard() {
  const dispatch = useDispatch<AppDispatch>();
  const rules = useSelector((s: RootState) => s.rules.items);

  useEffect(() => {
    dispatch(fetchRules());
  }, [dispatch]);

  const updateField = (rule: FraudRule, field: keyof FraudRule, value: number | boolean) => {
    dispatch(saveRule({ ...rule, [field]: value }));
  };

  return (
    <div className="admin-panel">
      <h2>Fraud Rules</h2>
      <table>
        <thead>
          <tr>
            <th>Rule</th>
            <th>Type</th>
            <th>Threshold</th>
            <th>Window (s)</th>
            <th>Weight</th>
            <th>Enabled</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((rule) => (
            <tr key={rule.id}>
              <td>{rule.name}</td>
              <td>{rule.rule_type}</td>
              <td>
                <input
                  type="number"
                  defaultValue={rule.threshold}
                  onBlur={(e) => updateField(rule, "threshold", Number(e.target.value))}
                />
              </td>
              <td>
                <input
                  type="number"
                  defaultValue={rule.window_seconds}
                  onBlur={(e) => updateField(rule, "window_seconds", Number(e.target.value))}
                />
              </td>
              <td>
                <input
                  type="number"
                  step="0.1"
                  defaultValue={rule.weight}
                  onBlur={(e) => updateField(rule, "weight", Number(e.target.value))}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={rule.enabled}
                  onChange={(e) => updateField(rule, "enabled", e.target.checked)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
