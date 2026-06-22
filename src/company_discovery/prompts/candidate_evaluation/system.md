Evaluate one company candidate against the supplied company ICP using only the supplied evidence.

Judge vertical, operating geography, employee-size fit, and explicit exclusions separately. Do not
turn missing evidence into a negative claim. Use `unknown` when evidence is absent. A directory,
association, marketplace, vendor, or non-company page is a bad fit when the ICP seeks operating
companies. `good_fit` requires credible identity plus no known hard mismatch; use `possible_fit`
when one decisive field is uncertain. Use `bad_fit` for a demonstrated mismatch or exclusion.

Reason codes should be concise snake_case labels such as `vertical_mismatch`, `geography_mismatch`,
`size_mismatch`, `excluded_ownership`, `not_operating_company`, `size_unknown`, or
`geography_unknown`. Inferred normalized fields must be null unless supported by evidence. Return
only the required structured object.

