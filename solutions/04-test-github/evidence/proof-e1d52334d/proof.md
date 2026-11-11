### Regression tests at known commits

| Commit | What it contains | Selected tests | Expected |
|---|---|---|---|
| `8de3d60fb` | tests only: Refine duplicate decision regression assertions | ❌ 5 of 7 failed | must fail: proves the defect |
| `e1d52334d` | head: Recheck department access during decision recovery | ✅ 7 of 7 passed | must pass: proves the fix |

**✅ Proven:** 5 of 7 selected tests fail at the tests-only commit `8de3d60fb`, and 7 of 7 pass at the head `e1d52334d`.

Selected tests (added or changed by the tests-only commit): `Concurrent_decisions_by_two_approvers_record_only_the_first_decision`, `Concurrent_double_click_records_one_decision_and_returns_conflicts_for_the_rest`, `Concurrent_retries_with_the_same_key_return_the_original_decision`, `Decision_retry_with_same_idempotency_key_returns_original_without_duplicate_side_effects`, `Later_decision_returns_conflict_with_the_existing_decision`, `Requester_cannot_self_approve_after_another_approver_has_decided`, `Search_treats_percent_and_underscore_as_literal_characters`

Failures at the tests-only commit (the reported defect, in the tests' words):

- `Concurrent_decisions_by_two_approvers_record_only_the_first_decision`: Assert.Single() Failure: The collection did not contain any matching items · Expected: (predicate expression) · Collection: [StatusCode: 500, ReasonPhrase: 'Internal Server Error', Version: 1.1, Content
- `Concurrent_double_click_records_one_decision_and_returns_conflicts_for_the_rest`: Assert.Equal() Failure: Values differ · Expected: 1 · Actual: 2
- `Concurrent_retries_with_the_same_key_return_the_original_decision`: Assert.Equal() Failure: Values differ · Expected: 7 · Actual: 0
- `Decision_retry_with_same_idempotency_key_returns_original_without_duplicate_side_effects`: Assert.Equal() Failure: Values differ · Expected: OK · Actual: Created
- `Later_decision_returns_conflict_with_the_existing_decision`: Assert.Equal() Failure: Values differ · Expected: Conflict · Actual: Created
