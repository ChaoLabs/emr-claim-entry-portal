-- CMS-1500 Claim Capture Schema
-- Current normalized schema for the Electronic Claim Entry Portal.
-- This schema mirrors the Django models at the current development stage.

CREATE TABLE patients (
    id UUID PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    middle_name VARCHAR(100),
    last_name VARCHAR(100) NOT NULL,
    date_of_birth DATE,
    sex VARCHAR(20),
    address_line_1 VARCHAR(255),
    address_line_2 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(2),
    zip_code VARCHAR(20),
    phone_number VARCHAR(30),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE insured_parties (
    id UUID PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    middle_name VARCHAR(100),
    last_name VARCHAR(100) NOT NULL,
    date_of_birth DATE,
    sex VARCHAR(20),
    address_line_1 VARCHAR(255),
    address_line_2 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(2),
    zip_code VARCHAR(20),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE payers (
    id UUID PRIMARY KEY,
    payer_name VARCHAR(255) NOT NULL,
    payer_type VARCHAR(50) NOT NULL,
    payer_identifier VARCHAR(100),
    medicare_administrative_contractor VARCHAR(255),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE insurance_policies (
    id UUID PRIMARY KEY,
    insured_party_id UUID NOT NULL REFERENCES insured_parties(id),
    payer_id UUID NOT NULL REFERENCES payers(id),
    member_id VARCHAR(100),
    group_number VARCHAR(100),
    plan_name VARCHAR(255),
    policy_type VARCHAR(50) NOT NULL,
    effective_start_date DATE,
    effective_end_date DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE claims (
    id UUID PRIMARY KEY,
    claim_number VARCHAR(100) UNIQUE,
    patient_id UUID NOT NULL REFERENCES patients(id),
    status VARCHAR(50) NOT NULL,
    validation_status VARCHAR(50),
    validation_message TEXT,
    service_start_date DATE,
    service_end_date DATE,
    total_charge_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    submitted_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE claim_coverages (
    id UUID PRIMARY KEY,
    claim_id UUID NOT NULL REFERENCES claims(id),
    insurance_policy_id UUID NOT NULL REFERENCES insurance_policies(id),
    payer_sequence VARCHAR(50) NOT NULL,
    relationship_to_patient VARCHAR(50),
    assignment_of_benefits BOOLEAN NOT NULL DEFAULT TRUE,
    release_of_information BOOLEAN NOT NULL DEFAULT TRUE,
    prior_authorization_number VARCHAR(100),
    other_payer_paid_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE providers (
    id UUID PRIMARY KEY,
    organization_name VARCHAR(255),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    npi VARCHAR(20),
    taxonomy_code VARCHAR(20),
    tax_id VARCHAR(50),
    address_line_1 VARCHAR(255),
    address_line_2 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(2),
    zip_code VARCHAR(20),
    phone_number VARCHAR(30),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE claim_providers (
    id UUID PRIMARY KEY,
    claim_id UUID NOT NULL REFERENCES claims(id),
    provider_id UUID NOT NULL REFERENCES providers(id),
    provider_role VARCHAR(50) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE claim_diagnoses (
    id UUID PRIMARY KEY,
    claim_id UUID NOT NULL REFERENCES claims(id),
    diagnosis_code VARCHAR(20) NOT NULL,
    diagnosis_order INTEGER NOT NULL,
    description VARCHAR(255),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE service_lines (
    id UUID PRIMARY KEY,
    claim_id UUID NOT NULL REFERENCES claims(id),
    service_from_date DATE,
    service_to_date DATE,
    place_of_service VARCHAR(10),
    procedure_code VARCHAR(20) NOT NULL,
    modifier_1 VARCHAR(10),
    modifier_2 VARCHAR(10),
    modifier_3 VARCHAR(10),
    modifier_4 VARCHAR(10),
    diagnosis_pointer_1 INTEGER,
    diagnosis_pointer_2 INTEGER,
    diagnosis_pointer_3 INTEGER,
    diagnosis_pointer_4 INTEGER,
    charge_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    units INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE claim_audit_events (
    id UUID PRIMARY KEY,
    claim_id UUID NOT NULL REFERENCES claims(id),
    event_type VARCHAR(100) NOT NULL,
    event_description TEXT,
    changed_by VARCHAR(100),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_patients_name ON patients(last_name, first_name);
CREATE INDEX idx_patients_dob ON patients(date_of_birth);

CREATE INDEX idx_insured_parties_name ON insured_parties(last_name, first_name);

CREATE INDEX idx_payers_identifier ON payers(payer_identifier);

CREATE INDEX idx_insurance_policies_insured_party ON insurance_policies(insured_party_id);
CREATE INDEX idx_insurance_policies_payer ON insurance_policies(payer_id);
CREATE INDEX idx_insurance_policies_member_id ON insurance_policies(member_id);
CREATE INDEX idx_insurance_policies_policy_type ON insurance_policies(policy_type);
CREATE INDEX idx_insurance_policies_is_active ON insurance_policies(is_active);

CREATE INDEX idx_claims_status ON claims(status);
CREATE INDEX idx_claims_patient ON claims(patient_id);
CREATE INDEX idx_claims_service_dates ON claims(service_start_date, service_end_date);

CREATE INDEX idx_claim_coverages_claim ON claim_coverages(claim_id);
CREATE INDEX idx_claim_coverages_policy ON claim_coverages(insurance_policy_id);
CREATE INDEX idx_claim_coverages_sequence ON claim_coverages(payer_sequence);

CREATE INDEX idx_providers_npi ON providers(npi);
CREATE INDEX idx_providers_taxonomy ON providers(taxonomy_code);

CREATE UNIQUE INDEX idx_unique_claim_provider_role
    ON claim_providers(claim_id, provider_id, provider_role);

CREATE UNIQUE INDEX idx_unique_claim_diagnosis_order
    ON claim_diagnoses(claim_id, diagnosis_order);

CREATE UNIQUE INDEX idx_unique_claim_payer_sequence
    ON claim_coverages(claim_id, payer_sequence);

CREATE UNIQUE INDEX idx_unique_claim_insurance_policy
    ON claim_coverages(claim_id, insurance_policy_id);
