# TASKFLEX — AI Layer

How TASKFLEX turns a sentence like *"collect my passport from the regional office
tomorrow 11am, ₹600"* into a structured, confirmable task — without ever trusting
raw LLM output.

---

## 1. Provider abstraction

```
AIProvider (interface: parse_task)
 ├── OpenAIProvider        (AI_PROVIDER=openai,  OPENAI_API_KEY)
 ├── AnthropicProvider     (AI_PROVIDER=anthropic, ANTHROPIC_API_KEY)
 └── MockAIProvider        (AI_PROVIDER=mock — default, zero config)
```

- Selected once at startup from settings; everything downstream depends on the
  interface, never a concrete provider.
- OpenAI/Anthropic SDKs are **imported lazily** inside their providers — the app
  runs fine with neither installed (falls back to mock).
- The mock provider is deterministic: rule-based keyword/date/budget extraction
  that produces the same schema, so the entire product (and the test suite) works
  offline with no API keys.

## 2. Task taxonomy

The parser must classify into a **closed set** of task types
(`app/models/enums.py`):

| Type | Typical example |
|------|-----------------|
| `appointment_assistance` | "register my mother at KLE hospital at 9am" |
| `queue_standing` | "stand in line at the RTO from 9am" |
| `government_office` | "submit my PAN application at the office" |
| `document_submission` / `document_collection` | "hand over/collect documents" |
| `courier_pickup` / `parcel_collection` | "pick up my parcel from Delhivery hub" |
| `grocery_pickup` | "buy the list from More supermarket" |
| `bank_assistance` | "get my passbook updated (non-financial)" |
| `form_submission`, `office_errand`, `college_work`, `local_errand`, `other` | |

The task classifier backs this with keyword/pattern scoring; the LLM is asked to
choose from the same list, and its answer is validated against the enum — an
unknown type is coerced to `other`, never accepted as-is.

## 3. The parse pipeline

`POST /api/v1/tasks/parse` → `TaskService.parse`:

1. **Prompt** the provider with the user text + customer's approximate location.
   The prompt instructs the model to return strict JSON with the fields below and
   to mark unknown fields as missing rather than inventing values.
2. **Parse the response** through Pydantic (`app/ai/schemas.py`) — malformed JSON
   or schema violations become a structured parse failure, not a 500.
3. **Post-validate (never trust the LLM):**
   - task type must be in the taxonomy (else `other`),
   - coordinates sanity-checked and, when possible, re-geocoded via the maps
     provider so addresses and pins agree,
   - budget values normalized into `budget_min/max`,
   - scheduled times coerced to UTC and required to be in the future,
   - **eligibility guard**: tasks that are financial (money transfer), medical
     (diagnosis/medication), or otherwise prohibited are flagged `ineligible`
     with a reason instead of becoming a task.
4. **Score confidence** per field and overall. Low confidence (< threshold) adds
   clarification questions.
5. **Return the interpretation** — nothing is persisted, no worker is contacted.

## 4. Missing fields & clarification

`app/ai/clarification.py` generates targeted questions for what's genuinely
missing, e.g.:

- no time → "When should this task happen? Pick a date and time."
- no address → "Where exactly should the runner go?"
- budget far from typical for the type → "Tasks like this usually cost ₹X–₹Y. Is
  ₹Z comfortable?"
- ambiguous document type → "Which document needs to be collected?"

The customer UI renders the interpretation (type, place, time, budget,
confidence) and the questions; the customer can fix fields or re-describe the
task. **Only after the customer presses Confirm** does `POST /tasks` create the
task, and **only `POST /tasks/{id}/confirm`** dispatches it to matching. This
gate is enforced by the backend state machine, not the UI.

## 5. Confidence model

- Each extracted field carries a confidence in `[0,1]` (LLM self-reported for real
  providers; heuristic for mock).
- Overall confidence is a weighted combination emphasizing task type and location.
- UI surfaces it as a percentage badge; admin task lists show the same badge so
  support staff can spot bad parses.

## 6. Provenance & auditability

Every created task stores `parsed_by_ai`, `ai_confidence`, and the provider's
raw response (`ai_raw_response`, admin-visible) so any task can be traced back
to exactly what the AI produced and what the customer confirmed.

## 7. Extending

Add a provider by implementing `AIProvider.parse_task` and registering it in the
provider factory. Nothing else changes — routes, services, and tests all target
the interface.
