-- CMS-1500 Claim Capture Schema
-- Normalized CMS-1500 data model for the Electronic Claim Entry Portal.
-- PostgreSQL-oriented review artifact; Django migrations are executable truth.

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
    address_line_1 VARCHAR(255) NOT NULL,
    address_line_2 VARCHAR(255),
    city VARCHAR(100) NOT NULL,
    state VARCHAR(2) NOT NULL,
    zip_code VARCHAR(5) NOT NULL,
    zip_code_extension VARCHAR(4),
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

CREATE TABLE reference_data_updates (
    id UUID PRIMARY KEY,
    dataset_name VARCHAR(50) NOT NULL,
    source_name VARCHAR(255) NOT NULL,
    source_version VARCHAR(100),
    source_url VARCHAR(200),
    status VARCHAR(20) NOT NULL,
    records_loaded INTEGER NOT NULL DEFAULT 0 CHECK (records_loaded >= 0),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    triggered_by VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE npi_references (
    npi VARCHAR(10) PRIMARY KEY,
    entity_type VARCHAR(20) NOT NULL,
    provider_name VARCHAR(255) NOT NULL,
    primary_taxonomy_code VARCHAR(20),
    city VARCHAR(100),
    state VARCHAR(2),
    zip_code VARCHAR(20),
    enumeration_date DATE,
    source_last_updated_date DATE,
    deactivation_date DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    source_update_id UUID REFERENCES reference_data_updates(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE icd10_codes (
    code VARCHAR(10) PRIMARY KEY,
    short_description VARCHAR(255) NOT NULL,
    long_description TEXT,
    effective_start_date DATE,
    effective_end_date DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    source_update_id UUID REFERENCES reference_data_updates(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE procedure_codes (
    code VARCHAR(10) PRIMARY KEY,
    code_system VARCHAR(30) NOT NULL,
    short_description VARCHAR(255) NOT NULL,
    long_description TEXT,
    effective_start_date DATE,
    effective_end_date DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    source_update_id UUID REFERENCES reference_data_updates(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE providers (
    id UUID PRIMARY KEY,
    organization_name VARCHAR(255),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    npi VARCHAR(20),
    npi_reference_id VARCHAR(10) REFERENCES npi_references(npi) ON DELETE SET NULL,
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
    icd10_reference_id VARCHAR(10) REFERENCES icd10_codes(code) ON DELETE SET NULL,
    diagnosis_order INTEGER NOT NULL,
    description VARCHAR(255),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE service_lines (
    id UUID PRIMARY KEY,
    claim_id UUID NOT NULL REFERENCES claims(id),
    rendering_provider_id UUID REFERENCES providers(id) ON DELETE SET NULL,
    service_from_date DATE,
    service_to_date DATE,
    place_of_service VARCHAR(10),
    procedure_code VARCHAR(20) NOT NULL,
    procedure_reference_id VARCHAR(10) REFERENCES procedure_codes(code) ON DELETE SET NULL,
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

CREATE INDEX idx_reference_updates_dataset_status
    ON reference_data_updates(dataset_name, status);
CREATE INDEX idx_reference_updates_completed
    ON reference_data_updates(completed_at);

CREATE INDEX idx_npi_reference_name ON npi_references(provider_name);
CREATE INDEX idx_npi_reference_taxonomy ON npi_references(primary_taxonomy_code);
CREATE INDEX idx_npi_reference_active ON npi_references(is_active);

CREATE INDEX idx_icd10_active ON icd10_codes(is_active);
CREATE INDEX idx_icd10_effective_dates
    ON icd10_codes(effective_start_date, effective_end_date);

CREATE INDEX idx_procedure_system_active
    ON procedure_codes(code_system, is_active);
CREATE INDEX idx_procedure_effective_dates
    ON procedure_codes(effective_start_date, effective_end_date);

CREATE INDEX idx_providers_npi ON providers(npi);
CREATE INDEX idx_providers_taxonomy ON providers(taxonomy_code);
CREATE INDEX idx_providers_npi_reference ON providers(npi_reference_id);

CREATE INDEX idx_claim_diagnoses_reference ON claim_diagnoses(icd10_reference_id);
CREATE INDEX idx_service_lines_procedure_reference ON service_lines(procedure_reference_id);
CREATE INDEX idx_service_lines_rendering_provider ON service_lines(rendering_provider_id);

CREATE UNIQUE INDEX idx_unique_claim_provider_role
    ON claim_providers(claim_id, provider_id, provider_role);

CREATE UNIQUE INDEX idx_unique_claim_diagnosis_order
    ON claim_diagnoses(claim_id, diagnosis_order);

CREATE UNIQUE INDEX idx_unique_claim_payer_sequence
    ON claim_coverages(claim_id, payer_sequence);

CREATE UNIQUE INDEX idx_unique_claim_insurance_policy
    ON claim_coverages(claim_id, insurance_policy_id);

CREATE UNIQUE INDEX idx_unique_policy_when_member_or_group_present
    ON insurance_policies(insured_party_id, payer_id, member_id, group_number)
    WHERE member_id <> '' OR group_number <> '';
