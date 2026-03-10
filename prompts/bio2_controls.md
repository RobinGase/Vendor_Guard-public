# BIO2 — Baseline Informatiebeveiliging Overheid 2

## Context
BIO2 is the mandatory information security baseline for Dutch government organizations (Rijk, provincies, gemeenten, waterschappen). It is based on ISO 27001/27002 with government-specific extensions.

## Applicability for vendor assessment
When the SAAF participating organization is a Dutch government entity, vendors processing government data or providing services to government must meet BIO2-aligned requirements.

## Key control areas

### Organisational security
- Information security policy aligned with BIO2
- Security roles and responsibilities defined
- Supplier agreements include BIO2 requirements

### Physical and environmental security
- Data centers meet Dutch government physical security standards
- Clear desk / clear screen policy

### Access control
- Identity and access management per BIO2 (role-based, least privilege)
- MFA mandatory for remote access and privileged accounts
- Periodic access reviews (at minimum annually)

### Cryptography
- Encryption algorithms approved by NCSC (see NCSC publication on cryptographic standards)
- Key management documented

### Operations security
- Change management process documented
- Vulnerability management: critical patches within 72h, high within 30 days
- Logging and monitoring: minimum retention 1 year

### Incident management
- Aligned with government CERT / NCSC reporting requirements

### Business continuity
- Recovery Time Objective (RTO) and Recovery Point Objective (RPO) documented
- Tested at minimum annually

## Key questions to assess
1. Has the vendor signed or accepted BIO2-aligned processing agreements?
2. Are NCSC-approved cryptographic algorithms used?
3. Are critical patches applied within 72 hours?
4. Is logging retained for at least 1 year?
5. Are RTO/RPO defined and tested?
