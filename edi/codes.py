SEX = {"female": "F", "male": "M", "other": "U", "unknown": "U", "": "U"}

PAYER_SEQUENCE = {"primary": "P", "secondary": "S", "tertiary": "T", "other": "U"}

FILING_INDICATOR = {
    "medicare": "MB",
    "medicaid": "MC",
    "commercial": "CI",
    "tricare": "CH",
    "other": "ZZ",
}

RELATIONSHIP = {
    "self": "18",
    "spouse": "01",
    "child": "19",
    "son": "19",
    "daughter": "19",
    "other": "G8",
}

RELATIONSHIP_SELF = "18"

ENTITY_PERSON = "1"
ENTITY_ORGANISATION = "2"

HL_BILLING_PROVIDER = "20"
HL_SUBSCRIBER = "22"
HL_DEPENDENT = "23"

QUALIFIER_NPI = "XX"
QUALIFIER_MEMBER_ID = "MI"
QUALIFIER_PAYER_ID = "PI"
QUALIFIER_EIN = "EI"
QUALIFIER_TAXONOMY = "PXC"
QUALIFIER_PROCEDURE = "HC"

DIAGNOSIS_PRINCIPAL = "ABK"
DIAGNOSIS_OTHER = "ABF"

CLAIM_FREQUENCY_ORIGINAL = "1"
FACILITY_CODE_QUALIFIER = "B"
UNIT_BASIS_UNITS = "UN"
