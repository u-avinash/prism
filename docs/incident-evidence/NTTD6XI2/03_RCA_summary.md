# RCA Summary -- NTTD6XI2

## Incident
CRITICAL Production failure in `order-processing-service`. DataWeave tried to coerce `payload.orderDate` to a Date, but the field was absent (or the payload was a String).

## Root cause
The `validate-order-payload` sub-flow accessed `payload.orderDate` without first checking its existence or type. When the field was missing, the strict `as Date` coercion failed.

## Proposed remediation (from generated patch)
```dataweave
parsedOrderDate: if (payload.orderDate?) payload.orderDate as Date {format: "yyyy-MM-dd"} else now()
```

## Review considerations
- Verify the business-correct default: `now()` prevents the coercion crash but may not be   domain-correct for every order type.
- Add MUnit tests for missing, null, and non-object `orderDate` inputs.
- Consider enforcing a RAML/JSON-Schema contract before the transform.

## Prevention
- CI/CD DataWeave static analysis to flag unsafe coercions.
- Structured logging for validation failures without exposing payload data.

## Evidence limits
This summary is derived from local Prism artifacts. Jira, GitHub, and Slack were not authenticated or independently captured during this documentation run.
