# /eval/attestation_tests/

Attestation deny-list validation test cases.

## Purpose

Assert that **every** known attestation keyword and canonical question ID correctly triggers ATTESTATION classification, preventing auto-fill.

## Test categories

- Work authorization / visa / sponsorship variations
- Criminal history / background check variations
- Education verification (GPA, degree dates)
- Employment date/title verification
- Professional licences / security clearances
- EEO/OFCCP demographics (race, gender, veteran, disability)
- Salary history
- Certification checkboxes ("I certify the above is true")

## Critical rule

> Unknown fields must default to ATTESTATION, never GENERATIVE. Test this explicitly.
